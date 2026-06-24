"""Autonomous Medtronic CarePartner (Connect) sync orchestrator.

Ties the pieces together for one user, one cycle:

    refresh token (rotating) -> access token  [connect_auth]
        -> POST display/message -> RecentData   [connect_client]
        -> map RecentData -> MappedRecords       [connect_mapper]
        -> upsert glucose + pump events          [storage]

and updates the user's ``MedtronicConnectState`` (freshness, status, error,
cumulative counter) -- crucially persisting the **rotated** refresh token (Auth0
rotation invalidates the old one, so a missed rotation = a dead connection on
the next tick).

CarePartner ``datetime`` strings are timezone-aware, so unlike the manual CSV
import this path needs no per-user timezone localization before storage.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.encryption import decrypt_credential, encrypt_credential
from src.logging_config import get_logger
from src.models.medtronic_connect_state import (
    STATUS_CONNECTED,
    STATUS_DISCONNECTED,
    STATUS_ERROR,
    MedtronicConnectState,
)
from src.services.glucose_unit import resolve_glucose_unit

from .connect_auth import ConnectTokenError, ConnectTokenProvider, get_region
from .connect_client import CareLinkConnectClient, ConnectAuthError, ConnectError
from .connect_mapper import map_recent_data
from .storage import store_carelink_records

logger = get_logger(__name__)

# Per-user in-flight locks. A manual "Sync now" (POST /connect/sync) and the
# scheduled tick can both fire for the same user; without serialization they
# race on the rotating Auth0 refresh token -- one cycle rotates it, the other
# then presents the now-stale token, gets invalid_grant, and the connection is
# marked disconnected (forcing a full browser+captcha re-pair). Mirrors the
# Nightscout per-connection lock. In-process only; cross-replica overlap is
# bounded by the scheduler tick spacing + per-user pacing.
_in_flight_locks: dict[uuid.UUID, asyncio.Lock] = {}


def _lock_for(user_id: uuid.UUID) -> asyncio.Lock:
    lock = _in_flight_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _in_flight_locks[user_id] = lock
    return lock


def _release_lock(user_id: uuid.UUID, lock: asyncio.Lock) -> None:
    # Drop the entry when no one else is waiting, so the dict tracks
    # "currently syncing" rather than every user this worker has seen.
    if not getattr(lock, "_waiters", None):
        _in_flight_locks.pop(user_id, None)


class ConnectSyncError(Exception):
    """A Connect sync cycle failed (after the state row was updated)."""


@dataclass
class ConnectSyncResult:
    glucose_fetched: int = 0
    glucose_stored: int = 0
    events_fetched: int = 0
    events_stored: int = 0


async def sync_connect_for_user(
    db: AsyncSession,
    state: MedtronicConnectState,
    *,
    now: datetime | None = None,
) -> ConnectSyncResult:
    """Run one sync cycle for ``state`` under a per-user lock.

    The lock serializes a manual "Sync now" against the scheduled tick so the
    two can't race on the rotating refresh token (see ``_in_flight_locks``).
    """
    lock = _lock_for(state.user_id)
    async with lock:
        try:
            return await _sync_connect_for_user_locked(db, state, now=now)
        finally:
            _release_lock(state.user_id, lock)


async def _sync_connect_for_user_locked(
    db: AsyncSession,
    state: MedtronicConnectState,
    *,
    now: datetime | None = None,
) -> ConnectSyncResult:
    """Run one autonomous sync cycle for ``state`` and update it in place.

    Always stamps ``last_attempt_at`` and commits (so a rotated refresh token is
    never lost), then raises ``ConnectSyncError`` on failure. On success, the
    mapped records and the updated state row are persisted in a SINGLE final
    commit (``store_carelink_records(..., commit=False)``) so a crash can't
    leave glucose stored with the status not yet flipped to connected.
    """
    now = now or datetime.now(UTC)
    state.last_attempt_at = now

    # Load the stored connection config up front: the region key plus the three
    # encrypted credentials. Any failure here is PERMANENT -- a corrupted/legacy
    # region column, or credentials the current encryption key can't decrypt
    # (key rotated out / corrupted row). Retrying a permanent failure every tick
    # would flood logs and Sentry forever, so mark the row disconnected (the only
    # recovery is re-pairing, which rewrites the region and re-encrypts the
    # credentials under the current key) and let the scheduler's discovery query
    # stop selecting it. Both get_region and decrypt_credential raise ValueError
    # on invalid stored data. Mirrors the ConnectTokenError handling below.
    try:
        region = get_region(state.region)
        refresh_token = decrypt_credential(state.encrypted_refresh_token)
        username = decrypt_credential(state.encrypted_username)
        patient_id = (
            decrypt_credential(state.encrypted_patient_id)
            if state.encrypted_patient_id
            else None
        )
    except ValueError as e:
        state.status = STATUS_DISCONNECTED
        state.last_error = f"Invalid stored connection data: {e}"
        await db.commit()
        raise ConnectSyncError(f"Connect stored data invalid: {e}") from e

    async def _persist_rotated(new_refresh_token: str) -> None:
        # Auth0 rotated the refresh token mid-cycle; capture it on the row so
        # the final commit persists it even if the data fetch then fails.
        state.encrypted_refresh_token = encrypt_credential(new_refresh_token)

    provider = ConnectTokenProvider(
        region=region,
        refresh_token=refresh_token,
        on_rotate=_persist_rotated,
    )

    try:
        async with CareLinkConnectClient(
            bearer_provider=provider,
            username=username,
            base_url=region.cloud_host,
            role=state.role,
            patient_id=patient_id,
        ) as client:
            recent = await client.get_recent_data()
        # The CarePartner feed carries no unit; a mmol/L-configured EU pump returns
        # bare mmol/L numbers. Thread the data owner's glucose-unit preference into
        # the mapper so a mmol/L user's ambiguous high (~20-27.8 mmol/L) is dropped
        # rather than stored as a false mg/dL severe low (GLY-59). mg/dL and
        # unknown-preference users are unaffected.
        glucose_unit = await resolve_glucose_unit(db, state.user_id)
        records = map_recent_data(recent, glucose_unit=glucose_unit)
        # commit=False: defer to the single final commit below so glucose +
        # events + the connected-state update land atomically.
        store = await store_carelink_records(
            db, state.user_id, records, now=now, commit=False
        )
    except ConnectTokenError as e:
        # Refresh token dead/revoked -> the user must re-login. Mark
        # disconnected so the scheduler stops retrying a hopeless credential.
        state.status = STATUS_DISCONNECTED
        state.last_error = str(e)
        await db.commit()
        raise ConnectSyncError(f"Connect auth expired: {e}") from e
    except (ConnectAuthError, ConnectError, ValueError) as e:
        # ValueError covers a malformed stored row (e.g. carepartner role with no
        # patient_id) surfacing from client construction -- treat as a sync error
        # rather than letting it escape as an unhandled 500 / kill the tick.
        state.status = STATUS_ERROR
        state.last_error = str(e)
        await db.commit()
        raise ConnectSyncError(f"Connect sync failed: {e}") from e
    except Exception as e:  # noqa: BLE001
        # Catch-all so an unexpected error (e.g. a transient DB/network error)
        # can't lose a refresh token that ROTATED during the bearer fetch -- a
        # lost rotation permanently bricks the connection on the next tick. Best
        # effort: if the commit itself is what failed, swallow that and still
        # surface the original failure as a ConnectSyncError.
        state.status = STATUS_ERROR
        state.last_error = f"Unexpected error: {e}"
        try:
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()
        raise ConnectSyncError(f"Connect sync failed unexpectedly: {e}") from e

    state.status = STATUS_CONNECTED
    state.last_sync_at = now
    state.last_error = None
    # Cumulative GLUCOSE readings stored -- matches the column name
    # (`readings_synced_total`) and the UI label ("Readings synced"). Pump
    # events (bolus/carbs) are stored too but intentionally not counted here.
    state.readings_synced_total += store.glucose_stored
    await db.commit()

    logger.info(
        "Medtronic Connect sync completed",
        user_id=str(state.user_id),
        glucose_fetched=store.glucose_fetched,
        glucose_stored=store.glucose_stored,
        events_fetched=store.events_fetched,
        events_stored=store.events_stored,
    )
    return ConnectSyncResult(
        glucose_fetched=store.glucose_fetched,
        glucose_stored=store.glucose_stored,
        events_fetched=store.events_fetched,
        events_stored=store.events_stored,
    )
