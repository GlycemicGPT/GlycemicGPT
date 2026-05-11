"""Nightscout connection management + read endpoints.

REST surface under `/api/integrations/nightscout` for users to register,
list, update, and remove their Nightscout / Nocturne (and connected
platforms) instances; plus read endpoints that the cloud-source mobile
plugin and the onboarding wizard consume.
"""

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import DiabeticOrAdminUser
from src.core.encryption import decrypt_credential, encrypt_credential
from src.database import get_db
from src.logging_config import get_logger
from src.models.glucose import GlucoseReading
from src.models.insulin_config import InsulinConfig
from src.models.nightscout_connection import (
    NightscoutConnection,
    NightscoutSyncStatus,
)
from src.models.nightscout_profile_snapshot import NightscoutProfileSnapshot
from src.models.pump_data import PumpEvent
from src.models.pump_profile import PumpProfile
from src.models.target_glucose_range import TargetGlucoseRange
from src.schemas.auth import ErrorResponse
from src.schemas.insulin_config import InsulinConfigUpdate
from src.schemas.nightscout import (
    NightscoutApplyOnboardingRequest,
    NightscoutApplyOnboardingResponse,
    NightscoutConnectionCreate,
    NightscoutConnectionCreatedResponse,
    NightscoutConnectionDeletedResponse,
    NightscoutConnectionListResponse,
    NightscoutConnectionResponse,
    NightscoutConnectionTestResult,
    NightscoutConnectionUpdate,
    NightscoutDataResponse,
    NightscoutDiscoveryReport,
    NightscoutGlucoseReadingDTO,
    NightscoutManualSyncResponse,
    NightscoutProfileSnapshotResponse,
    NightscoutPumpEventDTO,
    OnboardingDerivation,
)
from src.schemas.target_glucose_range import TargetGlucoseRangeUpdate
from src.services import insulin_config as insulin_config_service
from src.services import pump_profile as pump_profile_service
from src.services import target_glucose_range as target_range_service
from src.services.integrations.nightscout.connection_test import (
    ConnectionTestOutcome,
    test_connection,
)
from src.services.integrations.nightscout.evaluate import (
    evaluate_nightscout_for_connection,
)
from src.services.integrations.nightscout.onboarding_derive import (
    derive_onboarding_proposals,
)
from src.services.integrations.nightscout.sync import (
    sync_nightscout_for_connection,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/integrations/nightscout",
    tags=["integrations", "nightscout"],
)

# Manual sync wraps a synchronous translator round-trip; bound the
# worker so a slow / unresponsive user-controlled NS URL can't pin a
# request thread for the full upstream client timeout (often 30s+).
_SYNC_TIMEOUT_SECONDS = 20.0

# Story 43.7a (evaluate endpoint): bound the upstream probes the same
# way `_SYNC_TIMEOUT_SECONDS` does -- evaluate fires up to 5 fetches
# (entries x2, treatments, devicestatus, profile) sequentially, so a
# user-controlled URL that hangs on any of them shouldn't tie up a
# request worker indefinitely. 25s is generous-but-bounded.
_EVALUATE_TIMEOUT_SECONDS = 25.0

# Story 43.7a AC9: cache the discovery report on the connection row
# for this many seconds. Wizard re-renders shouldn't re-evaluate; an
# explicit "re-import settings" entry point (Story 43.7d) bypasses the
# cache by setting `last_evaluated_at = None` before the call.
_EVALUATE_CACHE_SECONDS = 5 * 60


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_owned(
    db: AsyncSession,
    connection_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    require_active: bool = False,
) -> NightscoutConnection:
    """Fetch a connection ensuring it belongs to the requesting user.

    Returns 404 (not 403) on cross-tenant access so we don't leak the
    existence of other users' connection IDs. Same 404 when
    `require_active=True` and the row was soft-deleted (`is_active=False`)
    -- that path is gated for endpoints that perform side effects
    (sync, test) so a deleted-but-known-id can't be reanimated.
    """
    where = [
        NightscoutConnection.id == connection_id,
        NightscoutConnection.user_id == user_id,
    ]
    if require_active:
        where.append(NightscoutConnection.is_active.is_(True))
    result = await db.execute(select(NightscoutConnection).where(*where))
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
    # Soft-deleted connections must not be reanimated via test/sync; we
    # 404 them here even though the row is still in the DB.
    conn = await _load_owned(db, connection_id, current_user.id, require_active=True)
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


@router.post(
    "/{connection_id}/sync",
    response_model=NightscoutManualSyncResponse,
    responses={
        200: {"description": "Sync executed (check `status` for outcome)"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Connection not found"},
    },
)
async def run_sync(
    connection_id: uuid.UUID,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> NightscoutManualSyncResponse:
    """Manually trigger a sync for one connection (Story 43.4 AC10).

    Synchronous from the user's POV: the request blocks until the
    fetch + translate completes (subject to `_SYNC_TIMEOUT_SECONDS`).
    Updates `last_synced_at` (only on full success) and
    `last_sync_status` regardless. Same code path the background
    scheduler uses, so the manual button validates the scheduler's
    behavior.

    Soft-deleted connections are 404'd here so a stale connection ID
    can't be used to reanimate sync activity for a deactivated
    instance.
    """
    conn = await _load_owned(db, connection_id, current_user.id, require_active=True)
    try:
        result = await asyncio.wait_for(
            sync_nightscout_for_connection(db, conn),
            timeout=_SYNC_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        # Caller-controlled URL: bound the worker. Surface as NETWORK
        # status (matches what we'd record for a hung-socket case) and
        # write back to the connection so the UI badge updates.
        # Roll back first: the cancelled sync may have flushed partial
        # rows; we don't want to commit those alongside the status
        # update. The translator's ON CONFLICT DO NOTHING means the
        # next successful sync will re-write what we drop here.
        await db.rollback()
        conn.last_sync_status = NightscoutSyncStatus.NETWORK
        conn.last_sync_error = f"Sync exceeded {_SYNC_TIMEOUT_SECONDS}s timeout"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=conn.last_sync_error,
        ) from None
    return NightscoutManualSyncResponse(
        connection_id=conn.id,
        status=result.status,
        entries_inserted=result.entries_inserted,
        entries_skipped=result.entries_skipped,
        entries_failed=result.entries_failed,
        treatments_inserted_pump=result.treatments_inserted_pump,
        treatments_inserted_glucose=result.treatments_inserted_glucose,
        treatments_failed=result.treatments_failed,
        devicestatuses_inserted=result.devicestatuses_inserted,
        devicestatuses_failed=result.devicestatuses_failed,
        profile_synced=result.profile_synced,
        duration_ms=result.duration_ms,
        error=result.error,
    )


@router.post(
    "/{connection_id}/evaluate",
    response_model=NightscoutDiscoveryReport,
    responses={
        200: {"description": "Discovery report (check `status_ok`)"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Connection not found"},
        504: {"model": ErrorResponse, "description": "Evaluate timed out"},
    },
)
async def run_evaluate(
    connection_id: uuid.UUID,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> NightscoutDiscoveryReport:
    """Story 43.7a: evaluate the target Nightscout for the wizard.

    Counts entries (full + 7d), detects uploaders, samples treatments
    + devicestatus + profile, and returns a structured discovery
    report (AC1). The wizard's step 2 renders this as the
    "Found ~142K entries..." preview.

    Cached for 5 min on the connection row (AC9). Wizard re-renders
    return the cached body; "Re-import settings" (Story 43.7d)
    bypasses the cache by clearing `last_evaluated_at` before the
    call.

    Soft-deleted connections are 404'd (parity with `/test` and
    `/sync`) -- evaluate is a side-effecting probe, not a passive
    read.
    """
    conn = await _load_owned(db, connection_id, current_user.id, require_active=True)

    # AC9: 5-min cache. Return the previously persisted report when
    # the cache window is still warm AND the cached report itself
    # was a success. A cached `status_ok=False` (e.g. typo'd token
    # on the prior call) MUST NOT be served from cache -- doing so
    # would trap the user for 5 min while they fix the secret. The
    # cache is for "we already evaluated this healthy instance"
    # only.
    # `isinstance(..., dict)` guards against legacy rows that may
    # have stored a list / string in this JSONB column under an
    # earlier schema -- without it, `.get()` would raise
    # AttributeError and 500 the request instead of falling
    # through to a fresh evaluate.
    if (
        conn.last_evaluated_at is not None
        and isinstance(conn.detected_uploaders_json, dict)
        and conn.detected_uploaders_json.get("status_ok") is True
    ):
        age = (datetime.now(UTC) - conn.last_evaluated_at).total_seconds()
        if age < _EVALUATE_CACHE_SECONDS:
            try:
                return NightscoutDiscoveryReport.model_validate(
                    conn.detected_uploaders_json
                )
            except Exception:  # noqa: BLE001 - shape changed mid-cache
                # Schema drift between cached payload and current
                # model: fall through to a fresh evaluate. The
                # cached row will be overwritten below.
                logger.info(
                    "nightscout_evaluate_cache_invalid",
                    connection_id=str(conn.id),
                )

    # Bound the user-controlled upstream the same way `/sync` does.
    try:
        report = await asyncio.wait_for(
            evaluate_nightscout_for_connection(conn),
            timeout=_EVALUATE_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        # Don't persist anything on timeout: `last_evaluated_at` stays
        # whatever it was, so an immediate retry isn't blocked by a
        # phantom cache entry. Last sync status is also untouched
        # (we didn't write user data).
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Evaluate exceeded {_EVALUATE_TIMEOUT_SECONDS}s timeout",
        ) from None

    # Persistence policy: only successful reports go into the cache.
    # A `status_ok=False` (auth fail, unreachable URL, etc.) returns
    # to the caller fresh every time so the user can immediately
    # retry after fixing their secret -- without waiting out a
    # 5-min cache window. Diagnostic value of caching a failure is
    # near zero; the wizard's "we couldn't reach your NS" UX wants
    # a real attempt each time.
    if report.status_ok:
        # `mode="json"` so datetime fields serialize to strings -- the
        # JSONB column rejects raw datetime objects.
        conn.detected_uploaders_json = report.model_dump(mode="json")
        conn.last_evaluated_at = datetime.now(UTC)
        await db.commit()

    return report


# ---------------------------------------------------------------------------
# Onboarding wizard: derivation read + apply
# ---------------------------------------------------------------------------


async def _load_user_settings(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> tuple[
    TargetGlucoseRange | None,
    InsulinConfig | None,
    PumpProfile | None,
]:
    """Read-only fetch of the user's canonical settings.

    Returns (target_range, insulin_config, pump_profile) where any
    of the three may be None when the user hasn't been seeded with
    that row yet. Importantly does NOT create defaults -- the
    wizard's "Currently" column should display the absence of a
    customization, not a freshly-materialized default. Active pump
    profile only (mirrors `get_active_profile`).
    """
    range_q = await db.execute(
        select(TargetGlucoseRange).where(TargetGlucoseRange.user_id == user_id)
    )
    config_q = await db.execute(
        select(InsulinConfig).where(InsulinConfig.user_id == user_id)
    )
    pump_profile = await pump_profile_service.get_active_profile(user_id, db)
    return (
        range_q.scalar_one_or_none(),
        config_q.scalar_one_or_none(),
        pump_profile,
    )


async def _load_snapshot(
    db: AsyncSession,
    *,
    connection_id: uuid.UUID,
    user_id: uuid.UUID,
) -> NightscoutProfileSnapshot | None:
    """Latest profile snapshot for `(connection, user)`, or None."""
    result = await db.execute(
        select(NightscoutProfileSnapshot).where(
            NightscoutProfileSnapshot.nightscout_connection_id == connection_id,
            NightscoutProfileSnapshot.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


@router.get(
    "/{connection_id}/onboarding-derivation",
    response_model=OnboardingDerivation,
    responses={
        200: {"description": "Derivation of pre-fill proposals + current values"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Connection not found"},
    },
)
async def read_onboarding_derivation(
    connection_id: uuid.UUID,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> OnboardingDerivation:
    """Build the wizard step 3 diff-table source for this connection.

    Reads the latest stored profile snapshot + the user's current
    canonical settings, then runs `derive_onboarding_proposals` to
    produce the field-by-field "Currently | From Nightscout" rows.

    Pure read: no DB writes. Soft-deleted connections return 404
    (parity with `/evaluate` and `/sync`).

    The snapshot is populated by `/evaluate` and routine `/sync`
    runs; if neither has happened yet the derivation surfaces
    `has_profile=False` and the wizard shows a "no profile data --
    we'll just sync data" banner. The wizard renders the same
    UI shape on every call so step 3 is deterministic regardless
    of NS state.
    """
    conn = await _load_owned(db, connection_id, current_user.id, require_active=True)
    snapshot = await _load_snapshot(db, connection_id=conn.id, user_id=current_user.id)
    target_range, insulin, pump = await _load_user_settings(db, current_user.id)
    return derive_onboarding_proposals(
        snapshot,
        current_target_range=target_range,
        current_insulin_config=insulin,
        current_pump_profile=pump,
    )


def _glucose_domain_requested(req: NightscoutApplyOnboardingRequest) -> bool:
    """Whether any glucose-domain import was requested.

    Drives the `units_unknown` confirmation gate: if the source
    profile's units couldn't be classified, applying mg/dL targets
    or ISFs that came in unitless from NS would silently miscompute
    -- so the apply endpoint refuses without an explicit
    `confirm_units_unknown=True` ack from the caller.
    """
    return req.import_target_low or req.import_target_high or req.import_isf_schedule


@router.post(
    "/{connection_id}/apply-onboarding",
    response_model=NightscoutApplyOnboardingResponse,
    responses={
        200: {"description": "Settings applied (check `first_sync_status`)"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Connection not found"},
        409: {
            "model": ErrorResponse,
            "description": "Profile units unknown -- caller must confirm",
        },
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def apply_onboarding(  # noqa: PLR0912, PLR0915  -- linear, readable orchestration
    connection_id: uuid.UUID,
    request: NightscoutApplyOnboardingRequest,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> NightscoutApplyOnboardingResponse:
    """Persist confirmed onboarding proposals + kick the first sync.

    Sequence:
        1. Load the connection + latest snapshot + current settings.
        2. Run the derivation (same code as `/onboarding-derivation`).
        3. Apply per-field imports honoring overrides.
        4. Persist `initial_sync_window_days` on the connection if set.
        5. Trigger `sync_nightscout_for_connection` bounded by
           `_SYNC_TIMEOUT_SECONDS`.

    The first sync runs INSIDE the request, so the wizard step 4
    progress UI gets a real status back instead of polling. On
    timeout the response is still 200 (settings landed
    successfully) with `first_sync_status="timeout"` and
    `first_sync_error` set; the wizard renders "we'll keep trying
    in the background" copy and routes the user to the dashboard.

    Idempotent: re-running with the same body re-asserts the same
    settings rows. The pump profile is upserted on
    `(user_id, "Nightscout")` so it doesn't accumulate duplicates;
    target range / insulin config are one-row-per-user by design.
    """
    conn = await _load_owned(db, connection_id, current_user.id, require_active=True)

    # Serialize the read-and-merge step for concurrent applies.
    # The xact-scoped advisory lock is released by the first
    # internal commit inside `update_range` / `update_config`, so
    # this DOES NOT serialize the full apply path -- it only
    # protects the snapshot+settings read and pre-flight ordering
    # check from racing with another in-flight apply for the same
    # user. The remaining window (two simultaneous syncs from a
    # double-clicked wizard) is mitigated by the
    # `uq_pump_profile_user_name` UPSERT (no row duplication) and
    # by the wizard's UI gating the button after the first click.
    # Acceptable for a same-user-only scope; full atomicity would
    # require non-committing variants of the settings writers.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": str(current_user.id)},
    )

    snapshot = await _load_snapshot(db, connection_id=conn.id, user_id=current_user.id)
    target_range, insulin, pump = await _load_user_settings(db, current_user.id)
    derivation = derive_onboarding_proposals(
        snapshot,
        current_target_range=target_range,
        current_insulin_config=insulin,
        current_pump_profile=pump,
    )

    # Hard gate: glucose-domain imports require an explicit ack
    # when the source unit is unrecognized. Returning 409 (not 422)
    # because the request body is well-formed -- the conflict is
    # with the upstream profile's state, which the caller can
    # resolve by re-confirming.
    if (
        derivation.units_unknown
        and _glucose_domain_requested(request)
        and not request.confirm_units_unknown
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Nightscout profile units could not be classified as "
                "mg/dL or mmol/L; resend with confirm_units_unknown=true "
                "to apply glucose-domain settings anyway."
            ),
        )

    # Pre-validate target range ordering BEFORE any writer commits.
    # The settings writers (`update_range`, `update_config`) commit
    # internally, so a mid-sequence ValueError would leave us with
    # a partially-applied state. By computing the merged thresholds
    # against the user's current row and rejecting up front, the
    # only failure modes left are infrastructure-level (DB drop) --
    # in which case partial application is unavoidable but the
    # subsequent writers would also have failed anyway.
    if request.import_target_low or request.import_target_high:
        new_low = (
            (
                request.override_target_low
                if request.override_target_low is not None
                else derivation.target_low.proposed_value
            )
            if request.import_target_low
            else (target_range.low_target if target_range else None)
        )
        new_high = (
            (
                request.override_target_high
                if request.override_target_high is not None
                else derivation.target_high.proposed_value
            )
            if request.import_target_high
            else (target_range.high_target if target_range else None)
        )
        # urgent_low/urgent_high are not modified by this endpoint,
        # so they retain whatever the user has (or defaults if no
        # row yet -- get_or_create_range will seed defaults that
        # already satisfy the ordering invariant).
        if new_low is not None and new_high is not None and new_low >= new_high:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"low_target ({new_low}) must be less than high_target ({new_high})"
                ),
            )

    applied: dict[str, bool] = {
        "target_low": False,
        "target_high": False,
        "dia_hours": False,
        "basal_schedule": False,
        "carb_ratio_schedule": False,
        "isf_schedule": False,
        "initial_sync_window_days": False,
    }

    # ---- target range ----------------------------------------------------
    target_range_payload: dict[str, float] = {}
    if request.import_target_low:
        value = request.override_target_low
        if value is None:
            value = derivation.target_low.proposed_value
        if value is not None:
            target_range_payload["low_target"] = float(value)
            applied["target_low"] = True
    if request.import_target_high:
        value = request.override_target_high
        if value is None:
            value = derivation.target_high.proposed_value
        if value is not None:
            target_range_payload["high_target"] = float(value)
            applied["target_high"] = True

    target_range_response: dict | None = None
    if target_range_payload:
        try:
            updated_range = await target_range_service.update_range(
                current_user.id,
                TargetGlucoseRangeUpdate(**target_range_payload),
                db,
            )
        except ValueError as e:
            # Ordering invariant violated (e.g. low_target came in
            # above existing high_target). Surface as 422 with the
            # writer's message; nothing has been committed yet
            # because update_range commits at the end.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            ) from e
        target_range_response = {
            "id": str(updated_range.id),
            "urgent_low": updated_range.urgent_low,
            "low_target": updated_range.low_target,
            "high_target": updated_range.high_target,
            "urgent_high": updated_range.urgent_high,
        }

    # ---- insulin config (DIA only) --------------------------------------
    insulin_response: dict | None = None
    if request.import_dia_hours:
        dia_value = request.override_dia_hours
        if dia_value is None:
            dia_value = derivation.dia_hours.proposed_value
        if dia_value is not None:
            try:
                updated_config = await insulin_config_service.update_config(
                    current_user.id,
                    InsulinConfigUpdate(dia_hours=float(dia_value)),
                    db,
                )
            except ValueError as e:
                # The schema enforces 2.0 <= dia_hours <= 8.0 at
                # validation time; this branch fires on writer-level
                # invariants. Same 422 surface as target range.
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(e),
                ) from e
            applied["dia_hours"] = True
            insulin_response = {
                "id": str(updated_config.id),
                "insulin_type": updated_config.insulin_type,
                "dia_hours": updated_config.dia_hours,
                "onset_minutes": updated_config.onset_minutes,
            }

    # ---- pump profile (basal / ICR / ISF) -------------------------------
    # Use truthy checks (not `is not None`) so an empty proposed
    # list -- which `_segments_by_start` collapses to {} -- doesn't
    # claim a schedule was applied when no segments existed to write.
    has_basal = bool(derivation.basal_schedule.proposed_segments)
    has_carb_ratio = bool(derivation.carb_ratio_schedule.proposed_segments)
    has_isf = bool(derivation.isf_schedule.proposed_segments)

    pump_profile_id: uuid.UUID | None = None
    persisted_profile = await pump_profile_service.upsert_from_onboarding(
        current_user.id,
        derivation,
        apply_basal=request.import_basal_schedule and has_basal,
        apply_carb_ratio=request.import_carb_ratio_schedule and has_carb_ratio,
        apply_isf=request.import_isf_schedule and has_isf,
        # DIA is mirrored onto the pump_profile row only when the
        # user opted in to importing it, so the active profile read
        # by mobile is internally consistent with insulin_configs.
        apply_dia=request.import_dia_hours
        and derivation.dia_hours.proposed_value is not None,
        db=db,
    )
    if persisted_profile is not None:
        pump_profile_id = persisted_profile.id
        applied["basal_schedule"] = request.import_basal_schedule and has_basal
        applied["carb_ratio_schedule"] = (
            request.import_carb_ratio_schedule and has_carb_ratio
        )
        applied["isf_schedule"] = request.import_isf_schedule and has_isf

    # ---- connection-level: initial sync window --------------------------
    if request.initial_sync_window_days is not None:
        conn.initial_sync_window_days = request.initial_sync_window_days
        applied["initial_sync_window_days"] = True

    # Commit all settings changes BEFORE the first sync runs so
    # that a sync timeout doesn't unwind the user's confirmed
    # imports. The sync writes its own rows + connection status
    # in a separate transaction managed by the orchestrator.
    await db.commit()

    # ---- first sync -----------------------------------------------------
    first_sync_status: str = "skipped"
    first_sync_error: str | None = None
    sync_response: NightscoutManualSyncResponse | None = None

    try:
        result = await asyncio.wait_for(
            sync_nightscout_for_connection(db, conn),
            timeout=_SYNC_TIMEOUT_SECONDS,
        )
        sync_response = NightscoutManualSyncResponse(
            connection_id=conn.id,
            status=result.status,
            entries_inserted=result.entries_inserted,
            entries_skipped=result.entries_skipped,
            entries_failed=result.entries_failed,
            treatments_inserted_pump=result.treatments_inserted_pump,
            treatments_inserted_glucose=result.treatments_inserted_glucose,
            treatments_failed=result.treatments_failed,
            devicestatuses_inserted=result.devicestatuses_inserted,
            devicestatuses_failed=result.devicestatuses_failed,
            profile_synced=result.profile_synced,
            duration_ms=result.duration_ms,
            error=result.error,
        )
        if result.status == NightscoutSyncStatus.OK:
            first_sync_status = "ok"
        else:
            # Sync ran but the orchestrator recorded a non-OK
            # status (auth fail, validation, partial). We surface
            # this as `error` so the wizard distinguishes "we
            # never got a response" (timeout) from "we got a
            # response but the upstream rejected the call".
            first_sync_status = "error"
            first_sync_error = result.error or result.status.value
    except TimeoutError:
        # Mirror the `/sync` endpoint's recovery: roll back any
        # partial sync rows, mark the connection NETWORK, commit
        # the status update. Distinct from `/sync` in that we do
        # NOT raise 504 -- settings already landed and the user
        # deserves a 200 with a clear "timed out, retry pending"
        # signal so the wizard's progress step can render the
        # "we'll keep trying in the background" copy.
        first_sync_status = "timeout"
        first_sync_error = f"First sync exceeded {_SYNC_TIMEOUT_SECONDS}s timeout"
        try:
            await db.rollback()
            # The rollback expires the loaded `conn` object; re-fetch
            # before mutating to avoid touching a detached row.
            refreshed = (
                await db.execute(
                    select(NightscoutConnection).where(
                        NightscoutConnection.id == conn.id
                    )
                )
            ).scalar_one()
            refreshed.last_sync_status = NightscoutSyncStatus.NETWORK
            refreshed.last_sync_error = first_sync_error
            await db.commit()
        except Exception:  # noqa: BLE001
            # Status-update commit failure is non-fatal: settings
            # already landed in the prior commit, and the wizard
            # only needs `first_sync_status` to render correctly.
            # The next scheduler tick will re-establish a real
            # `last_sync_status` regardless.
            logger.warning(
                "nightscout_apply_onboarding_status_update_failed",
                connection_id=str(conn.id),
            )
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass

    logger.info(
        "nightscout_apply_onboarding_completed",
        user_id=str(current_user.id),
        connection_id=str(conn.id),
        first_sync_status=first_sync_status,
        applied_fields=[k for k, v in applied.items() if v],
    )

    return NightscoutApplyOnboardingResponse(
        connection_id=conn.id,
        applied=applied,
        target_glucose_range=target_range_response,
        insulin_config=insulin_response,
        pump_profile_id=pump_profile_id,
        first_sync_status=first_sync_status,  # type: ignore[arg-type]
        first_sync_error=first_sync_error,
        sync_result=sync_response,
    )


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

    # Defend against naive datetimes from clients: PostgreSQL's TIMESTAMP
    # WITH TIME ZONE compares against naive values using the session's
    # `timezone` setting, which silently shifts the cursor on a non-UTC
    # session. Force UTC at the boundary.
    if since is not None and since.tzinfo is None:
        since = since.replace(tzinfo=UTC)

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
