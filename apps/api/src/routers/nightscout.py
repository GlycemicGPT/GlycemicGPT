"""Nightscout connection management + read endpoints.

REST surface under `/api/integrations/nightscout` for users to register,
list, update, and remove their Nightscout / Nocturne (and connected
platforms) instances; plus read endpoints that the cloud-source mobile
plugin and the onboarding wizard consume.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import DiabeticOrAdminUser
from src.core.encryption import decrypt_credential, encrypt_credential
from src.database import get_db
from src.logging_config import get_logger
from src.models.glucose import GlucoseReading
from src.models.nightscout_connection import (
    NightscoutConnection,
    NightscoutSyncStatus,
)
from src.models.nightscout_profile_snapshot import NightscoutProfileSnapshot
from src.models.pump_data import PumpEvent
from src.schemas.auth import ErrorResponse
from src.schemas.nightscout import (
    NightscoutConnectionCreate,
    NightscoutConnectionCreatedResponse,
    NightscoutConnectionDeletedResponse,
    NightscoutConnectionListResponse,
    NightscoutConnectionResponse,
    NightscoutConnectionTestResult,
    NightscoutConnectionUpdate,
    NightscoutDataResponse,
    NightscoutGlucoseReadingDTO,
    NightscoutProfileSnapshotResponse,
    NightscoutPumpEventDTO,
)
from src.services.integrations.nightscout.connection_test import (
    ConnectionTestOutcome,
    test_connection,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/integrations/nightscout",
    tags=["integrations", "nightscout"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_owned(
    db: AsyncSession, connection_id: uuid.UUID, user_id: uuid.UUID
) -> NightscoutConnection:
    """Fetch a connection ensuring it belongs to the requesting user.

    Returns 404 (not 403) on cross-tenant access so we don't leak the
    existence of other users' connection IDs.
    """
    result = await db.execute(
        select(NightscoutConnection).where(
            NightscoutConnection.id == connection_id,
            NightscoutConnection.user_id == user_id,
        )
    )
    conn = result.scalar_one_or_none()
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connection not found",
        )
    return conn


def _outcome_to_response(
    outcome: ConnectionTestOutcome,
) -> NightscoutConnectionTestResult:
    return NightscoutConnectionTestResult(
        ok=outcome.ok,
        server_version=outcome.server_version,
        api_version_detected=outcome.api_version_detected,
        auth_validated=outcome.auth_validated,
        error=outcome.error,
    )


def _outcome_to_status(outcome: ConnectionTestOutcome) -> NightscoutSyncStatus:
    if outcome.ok:
        return NightscoutSyncStatus.OK
    if not outcome.auth_validated and outcome.api_version_detected is not None:
        # Reached the server but credential rejected -> auth_failed.
        return NightscoutSyncStatus.AUTH_FAILED
    return NightscoutSyncStatus.ERROR


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=NightscoutConnectionCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Connection created and tested"},
        400: {"model": ErrorResponse, "description": "Connection test failed"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
    },
)
async def create_connection(
    request: NightscoutConnectionCreate,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> NightscoutConnectionCreatedResponse:
    """Create and test a new Nightscout connection.

    The connection is tested before the row is committed. If the test
    fails, returns 400 and persists nothing -- the user fixes their
    URL/credential and re-submits.
    """
    outcome = await test_connection(
        base_url=request.base_url,
        auth_type=request.auth_type,
        credential=request.credential,
        api_version=request.api_version,
    )

    if not outcome.ok:
        logger.info(
            "nightscout_connection_test_failed",
            user_id=str(current_user.id),
            error=outcome.error,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=outcome.error or "Connection test failed",
        )

    # last_sync_status stays NEVER until an actual sync runs (Story
    # 43.4). The test outcome is independent telemetry returned in the
    # response, NOT a substitute for a successful sync.
    conn = NightscoutConnection(
        user_id=current_user.id,
        name=request.name,
        base_url=request.base_url,
        auth_type=request.auth_type,
        encrypted_credential=encrypt_credential(request.credential),
        api_version=outcome.api_version_detected or request.api_version,
        sync_interval_minutes=request.sync_interval_minutes,
        initial_sync_window_days=request.initial_sync_window_days,
        last_sync_status=NightscoutSyncStatus.NEVER,
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)

    logger.info(
        "nightscout_connection_created",
        user_id=str(current_user.id),
        connection_id=str(conn.id),
        api_version=conn.api_version.value,
    )

    return NightscoutConnectionCreatedResponse(
        connection=NightscoutConnectionResponse.model_validate(conn),
        test=_outcome_to_response(outcome),
    )


@router.get(
    "",
    response_model=NightscoutConnectionListResponse,
    responses={
        200: {"description": "List of the user's connections"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def list_connections(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> NightscoutConnectionListResponse:
    """List all Nightscout connections owned by the current user.

    Includes inactive connections so users can see their full history;
    UI is responsible for grouping active vs deactivated.
    """
    result = await db.execute(
        select(NightscoutConnection).where(
            NightscoutConnection.user_id == current_user.id
        )
    )
    return NightscoutConnectionListResponse(
        connections=[
            NightscoutConnectionResponse.model_validate(c)
            for c in result.scalars().all()
        ]
    )


@router.get(
    "/{connection_id}",
    response_model=NightscoutConnectionResponse,
    responses={
        200: {"description": "Connection found"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Connection not found"},
    },
)
async def get_connection(
    connection_id: uuid.UUID,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> NightscoutConnectionResponse:
    """Read a single connection by id (must be owned by the caller)."""
    conn = await _load_owned(db, connection_id, current_user.id)
    return NightscoutConnectionResponse.model_validate(conn)


@router.patch(
    "/{connection_id}",
    response_model=NightscoutConnectionCreatedResponse,
    responses={
        200: {"description": "Connection updated; re-test result attached"},
        400: {"model": ErrorResponse, "description": "Re-test failed"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Connection not found"},
    },
)
async def update_connection(
    connection_id: uuid.UUID,
    request: NightscoutConnectionUpdate,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> NightscoutConnectionCreatedResponse:
    """Update a connection. Re-tests if any field that affects connection
    behaviour (URL, credential, auth_type, api_version) changed.

    The PATCH stages all updates into local variables and ONLY mutates
    the ORM object after the (optional) re-test succeeds. This keeps
    the in-memory ORM state consistent with the persisted state after a
    failed test, removing the need for rollback gymnastics.
    """
    conn = await _load_owned(db, connection_id, current_user.id)

    # Resolve the post-update values (fall back to current ORM values
    # for any field the request didn't touch). Nothing is assigned to
    # the ORM yet -- if the re-test fails we never mutate.
    new_base_url = request.base_url if request.base_url is not None else conn.base_url
    new_auth_type = (
        request.auth_type if request.auth_type is not None else conn.auth_type
    )
    new_api_version = (
        request.api_version if request.api_version is not None else conn.api_version
    )
    cred_for_test = (
        request.credential
        if request.credential is not None
        else decrypt_credential(conn.encrypted_credential)
    )

    # Re-test if anything that affects what the server sees changed.
    # auth_type or api_version flips reinterpret the same credential
    # against a different protocol -- a "valid" credential at save
    # time is no longer guaranteed valid.
    needs_retest = (
        (request.base_url is not None and request.base_url != conn.base_url)
        or request.credential is not None
        or (request.auth_type is not None and request.auth_type != conn.auth_type)
        or (request.api_version is not None and request.api_version != conn.api_version)
    )

    test_outcome = None
    detected_api_version = None
    if needs_retest:
        test_outcome = await test_connection(
            base_url=new_base_url,
            auth_type=new_auth_type,
            credential=cred_for_test,
            api_version=new_api_version,
        )
        if not test_outcome.ok:
            # No ORM mutations have happened -- nothing to roll back.
            logger.info(
                "nightscout_connection_update_failed_retest",
                user_id=str(current_user.id),
                connection_id=str(conn.id),
                error=test_outcome.error,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=test_outcome.error or "Re-test failed",
            )
        detected_api_version = test_outcome.api_version_detected

    # Re-test (if any) succeeded. Apply staged updates.
    if request.name is not None:
        conn.name = request.name
    if request.auth_type is not None:
        conn.auth_type = request.auth_type
    if detected_api_version is not None:
        conn.api_version = detected_api_version
    elif request.api_version is not None:
        conn.api_version = request.api_version
    if request.is_active is not None:
        conn.is_active = request.is_active
    if request.sync_interval_minutes is not None:
        conn.sync_interval_minutes = request.sync_interval_minutes
    if request.initial_sync_window_days is not None:
        conn.initial_sync_window_days = request.initial_sync_window_days
    if request.base_url is not None:
        conn.base_url = request.base_url
    if request.credential is not None:
        conn.encrypted_credential = encrypt_credential(request.credential)

    await db.commit()
    await db.refresh(conn)

    logger.info(
        "nightscout_connection_updated",
        user_id=str(current_user.id),
        connection_id=str(conn.id),
        re_tested=bool(test_outcome),
    )

    return NightscoutConnectionCreatedResponse(
        connection=NightscoutConnectionResponse.model_validate(conn),
        test=_outcome_to_response(test_outcome)
        if test_outcome is not None
        else NightscoutConnectionTestResult(
            ok=True,
            server_version=None,
            api_version_detected=conn.api_version,
            auth_validated=True,
            error=None,
        ),
    )


@router.delete(
    "/{connection_id}",
    response_model=NightscoutConnectionDeletedResponse,
    responses={
        200: {"description": "Connection deactivated"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Connection not found"},
    },
)
async def delete_connection(
    connection_id: uuid.UUID,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> NightscoutConnectionDeletedResponse:
    """Soft-delete: marks the connection inactive.

    Hard-delete is intentionally avoided -- ingested rows carry
    `source = "nightscout:<connection_id>"` attribution that we want to
    keep readable in the dashboard even after a user removes the
    connection. A future Story can add a hard-delete endpoint that
    cascades through historical data; not in scope for 43.1.
    """
    conn = await _load_owned(db, connection_id, current_user.id)
    conn.is_active = False
    await db.commit()

    logger.info(
        "nightscout_connection_deactivated",
        user_id=str(current_user.id),
        connection_id=str(conn.id),
    )
    return NightscoutConnectionDeletedResponse(id=conn.id)


@router.post(
    "/{connection_id}/test",
    response_model=NightscoutConnectionTestResult,
    responses={
        200: {"description": "Test executed (check `ok` for outcome)"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Connection not found"},
    },
)
async def run_test(
    connection_id: uuid.UUID,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> NightscoutConnectionTestResult:
    """Re-run the connection test for an existing connection.

    Updates `last_sync_status` to reflect the outcome so the dashboard
    UI shows current health without waiting for the scheduled sync.
    """
    conn = await _load_owned(db, connection_id, current_user.id)
    outcome = await test_connection(
        base_url=conn.base_url,
        auth_type=conn.auth_type,
        credential=decrypt_credential(conn.encrypted_credential),
        api_version=conn.api_version,
    )
    # _outcome_to_status returns OK when outcome.ok; no need for a guard.
    conn.last_sync_status = _outcome_to_status(outcome)
    conn.last_sync_error = outcome.error  # None on success
    await db.commit()

    return _outcome_to_response(outcome)


# ---------------------------------------------------------------------------
# Read endpoints (mobile cloud-source plugin + onboarding wizard)
# ---------------------------------------------------------------------------

# Hard cap on `limit`. The cloud-source plugin pulls incrementally via
# `since`, so a generous-but-bounded page keeps memory predictable.
_MAX_DATA_LIMIT = 5000


@router.get(
    "/{connection_id}/data",
    response_model=NightscoutDataResponse,
    responses={
        200: {"description": "Merged data slice for this connection"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Connection not found"},
    },
)
async def read_connection_data(
    connection_id: uuid.UUID,
    current_user: DiabeticOrAdminUser,
    since: datetime | None = Query(
        default=None,
        description="Return rows whose timestamp is >= this value. "
        "Omit on first call; pass the highest timestamp from the previous "
        "page on subsequent calls. Inclusive comparison (`>=`) guards "
        "against losing rows that share a timestamp with the cursor "
        "boundary (e.g. the bolus + carbs rows of a split meal-bolus "
        "pair land at identical timestamps). Callers MUST dedupe by "
        "`ns_id` locally -- duplicates are bounded to ~1 row per page "
        "boundary per array.",
    ),
    limit: int = Query(default=500, ge=1, le=_MAX_DATA_LIMIT),
    db: AsyncSession = Depends(get_db),
) -> NightscoutDataResponse:
    """Return glucose readings + pump events sourced from this connection.

    Consumed by the mobile cloud-source plugin to populate Room DB.
    Both arrays are filtered to `source = "nightscout:<id>"` -- the
    caller never sees data from other sources, so coexistence with
    BLE plugins on the same user is clean.

    `limit` applies **per array** -- a single response can contain
    up to `limit` glucose readings AND up to `limit` pump events. The
    response field `effective_limit_per_array` echoes the value used
    so callers don't have to track the cap.
    """
    conn = await _load_owned(db, connection_id, current_user.id)
    source_tag = f"nightscout:{conn.id}"

    glucose_q = (
        select(GlucoseReading)
        .where(
            GlucoseReading.user_id == current_user.id,
            GlucoseReading.source == source_tag,
        )
        .order_by(GlucoseReading.reading_timestamp.asc())
        .limit(limit)
    )
    if since is not None:
        glucose_q = glucose_q.where(GlucoseReading.reading_timestamp >= since)
    glucose_rows = (await db.execute(glucose_q)).scalars().all()

    events_q = (
        select(PumpEvent)
        .where(
            PumpEvent.user_id == current_user.id,
            PumpEvent.source == source_tag,
        )
        .order_by(PumpEvent.event_timestamp.asc())
        .limit(limit)
    )
    if since is not None:
        events_q = events_q.where(PumpEvent.event_timestamp >= since)
    event_rows = (await db.execute(events_q)).scalars().all()

    return NightscoutDataResponse(
        connection_id=conn.id,
        fetched_at=datetime.now(UTC),
        effective_limit_per_array=limit,
        glucose_readings=[
            NightscoutGlucoseReadingDTO(
                ns_id=g.ns_id,
                reading_timestamp=g.reading_timestamp,
                value=g.value,
                trend=g.trend.value,
                trend_rate=g.trend_rate,
                source=g.source,
            )
            for g in glucose_rows
        ],
        pump_events=[
            NightscoutPumpEventDTO(
                ns_id=e.ns_id,
                event_timestamp=e.event_timestamp,
                event_type=e.event_type.value,
                units=e.units,
                duration_minutes=e.duration_minutes,
                is_automated=e.is_automated,
                metadata_json=e.metadata_json,
                meal_event_id=e.meal_event_id,
                source=e.source,
            )
            for e in event_rows
        ],
    )


@router.get(
    "/{connection_id}/profile-snapshot",
    response_model=NightscoutProfileSnapshotResponse,
    responses={
        200: {"description": "Latest profile snapshot for this connection"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Connection not found"},
    },
)
async def read_connection_profile_snapshot(
    connection_id: uuid.UUID,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> NightscoutProfileSnapshotResponse:
    """Return the latest Nightscout profile snapshot for this connection.

    Consumed by the onboarding wizard to pre-fill the user's canonical
    settings form. Returns a `has_snapshot=False` empty payload when
    no profile fetch has happened yet (the connection was added but
    hasn't synced).
    """
    conn = await _load_owned(db, connection_id, current_user.id)
    result = await db.execute(
        select(NightscoutProfileSnapshot).where(
            NightscoutProfileSnapshot.nightscout_connection_id == conn.id,
            NightscoutProfileSnapshot.user_id == current_user.id,
        )
    )
    snap = result.scalar_one_or_none()
    if snap is None:
        return NightscoutProfileSnapshotResponse(
            connection_id=conn.id,
            has_snapshot=False,
            fetched_at=None,
            source_default_profile_name=None,
            source_units=None,
            source_timezone=None,
            source_dia_hours=None,
            basal_segments=None,
            carb_ratio_segments=None,
            sensitivity_segments=None,
            target_low_segments=None,
            target_high_segments=None,
        )
    return NightscoutProfileSnapshotResponse(
        connection_id=conn.id,
        has_snapshot=True,
        fetched_at=snap.fetched_at,
        source_default_profile_name=snap.source_default_profile_name,
        source_units=snap.source_units,
        source_timezone=snap.source_timezone,
        source_dia_hours=snap.source_dia_hours,
        basal_segments=snap.basal_segments,
        carb_ratio_segments=snap.carb_ratio_segments,
        sensitivity_segments=snap.sensitivity_segments,
        target_low_segments=snap.target_low_segments,
        target_high_segments=snap.target_high_segments,
    )
