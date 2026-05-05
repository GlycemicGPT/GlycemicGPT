"""Story 43.1: Nightscout connection management endpoints.

REST surface under `/api/integrations/nightscout` for users to register,
list, update, and remove their Nightscout / Nocturne (and connected
platforms) instances.

The actual data sync (Story 43.4) and the HTTP client (Story 43.2) live
elsewhere -- this router only handles connection lifecycle. The
connection-test endpoint uses the Story 43.1 stub in
`src.services.integrations.nightscout.connection_test`; once Story 43.2
ships, that module is replaced by the full client.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import DiabeticOrAdminUser
from src.core.encryption import decrypt_credential, encrypt_credential
from src.database import get_db
from src.logging_config import get_logger
from src.models.nightscout_connection import (
    NightscoutConnection,
    NightscoutSyncStatus,
)
from src.schemas.auth import ErrorResponse
from src.schemas.nightscout import (
    NightscoutConnectionCreate,
    NightscoutConnectionCreatedResponse,
    NightscoutConnectionDeletedResponse,
    NightscoutConnectionListResponse,
    NightscoutConnectionResponse,
    NightscoutConnectionTestResult,
    NightscoutConnectionUpdate,
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
    conn.last_sync_status = (
        NightscoutSyncStatus.OK if outcome.ok else _outcome_to_status(outcome)
    )
    if outcome.error:
        conn.last_sync_error = outcome.error
    else:
        conn.last_sync_error = None
    await db.commit()

    return _outcome_to_response(outcome)
