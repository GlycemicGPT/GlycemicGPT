"""Story 3.1, 3.2, 3.3 & 3.4: Integration credentials and data sync router.

API endpoints for managing third-party integrations (Dexcom, Tandem) and data sync.
"""

import math
import zoneinfo
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydexcom import Dexcom
from pydexcom import errors as dexcom_errors
from sqlalchemy import and_, case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from tconnectsync.api.common import ApiException
from tconnectsync.api.tandemsource import TandemSourceApi

from src.core.auth import CurrentUser, DiabeticOrAdminUser
from src.core.encryption import encrypt_credential
from src.database import get_db
from src.logging_config import get_logger
from src.middleware.rate_limit import limiter
from src.models.glucose import GlucoseReading
from src.models.integration import (
    IntegrationCredential,
    IntegrationStatus,
    IntegrationType,
)
from src.models.pump_data import PumpEvent, PumpEventType
from src.models.pump_hardware_info import PumpHardwareInfo
from src.models.pump_raw_event import PumpRawEvent
from src.models.tandem_upload_state import TandemUploadState
from src.schemas.auth import ErrorResponse
from src.schemas.glucose import (
    AGPBucket,
    CurrentGlucoseResponse,
    GlucoseHistoryResponse,
    GlucosePercentilesResponse,
    GlucoseReadingResponse,
    GlucoseStatsResponse,
    SyncResponse,
    SyncStatusResponse,
    TimeInRangeDetailResponse,
    TimeInRangeResponse,
    TirBucket,
    TirThresholds,
)
from src.schemas.integration import (
    DexcomCredentialsRequest,
    IntegrationConnectResponse,
    IntegrationDisconnectResponse,
    IntegrationListResponse,
    IntegrationResponse,
    TandemCredentialsRequest,
)
from src.schemas.pump import (
    BolusReviewItem,
    BolusReviewResponse,
    ControlIQActivityResponse,
    InsulinSummaryResponse,
    IoBProjectionResponse,
    PumpEventHistoryResponse,
    PumpEventResponse,
    PumpPushRequest,
    PumpPushResponse,
    PumpStatusBasal,
    PumpStatusBattery,
    PumpStatusReservoir,
    PumpStatusResponse,
    TandemSyncResponse,
    TandemSyncStatusResponse,
    TandemUploadSettingsRequest,
    TandemUploadStatusResponse,
    TandemUploadTriggerResponse,
)
from src.services.dexcom_sync import (
    DexcomAuthError,
    DexcomConnectionError,
    DexcomSyncError,
    get_glucose_readings,
    get_latest_glucose_reading,
    sync_dexcom_for_user,
)
from src.services.iob_projection import get_iob_projection, get_user_dia
from src.services.tandem_sync import (
    TandemAuthError,
    TandemConnectionError,
    TandemNotConfiguredError,
    TandemSyncError,
    get_control_iq_activity,
    get_latest_pump_event,
    get_latest_pump_status,
    get_pump_events,
    sync_tandem_for_user,
)
from src.services.target_glucose_range import get_or_create_range

logger = get_logger(__name__)

# Minimum readings for a statistically meaningful previous-period TIR comparison
_MIN_PREV_PERIOD_READINGS = 10

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def validate_dexcom_credentials(
    username: str, password: str
) -> tuple[bool, str | None]:
    """Validate Dexcom Share credentials by attempting to connect.

    Args:
        username: Dexcom Share email
        password: Dexcom Share password

    Returns:
        Tuple of (success, error_message)
    """
    try:
        # Try to connect to Dexcom - this validates credentials
        dexcom = Dexcom(username=username, password=password)
        # Try to get glucose readings to confirm connection works
        _ = dexcom.get_current_glucose_reading()
        return True, None
    except dexcom_errors.AccountError as e:
        logger.warning(
            "Dexcom credential validation failed - account error",
            error=str(e),
        )
        return (
            False,
            "Invalid Dexcom credentials. Please check your email and password.",
        )
    except dexcom_errors.SessionError as e:
        logger.warning(
            "Dexcom credential validation failed - session error",
            error=str(e),
        )
        return False, "Unable to connect to Dexcom. Please try again later."
    except Exception as e:
        logger.error(
            "Dexcom credential validation failed - unexpected error",
            error=str(e),
        )
        return (
            False,
            "An error occurred while validating credentials. Please try again.",
        )


def validate_tandem_credentials(
    username: str, password: str, region: str = "US"
) -> tuple[bool, str | None]:
    """Validate Tandem t:connect credentials by attempting to connect.

    Args:
        username: Tandem t:connect email
        password: Tandem t:connect password
        region: Account region ('US' or 'EU')

    Returns:
        Tuple of (success, error_message)
    """
    try:
        # Try to connect to Tandem - this validates credentials via login()
        # TandemSourceApi calls login() in __init__, so instantiation validates
        _api = TandemSourceApi(email=username, password=password, region=region)
        return True, None
    except ValueError as e:
        # Invalid region
        logger.warning(
            "Tandem credential validation failed - invalid region",
            error=str(e),
        )
        return False, f"Invalid region: {region}. Must be 'US' or 'EU'."
    except ApiException as e:
        logger.warning(
            "Tandem credential validation failed - API error",
            error=str(e),
        )
        # Check for specific error messages
        error_str = str(e).lower()
        if "login" in error_str or "credential" in error_str or "401" in error_str:
            return (
                False,
                "Invalid Tandem credentials. Please check your email and password.",
            )
        return False, "Unable to connect to Tandem t:connect. Please try again later."
    except Exception as e:
        logger.error(
            "Tandem credential validation failed - unexpected error",
            error=str(e),
        )
        return (
            False,
            "An error occurred while validating credentials. Please try again.",
        )


@router.get(
    "",
    response_model=IntegrationListResponse,
    responses={
        200: {"description": "List of integrations"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
    },
)
async def list_integrations(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> IntegrationListResponse:
    """List all integrations for the current user.

    Returns the status of all configured integrations.
    """
    result = await db.execute(
        select(IntegrationCredential).where(
            IntegrationCredential.user_id == current_user.id
        )
    )
    credentials = result.scalars().all()

    return IntegrationListResponse(
        integrations=[IntegrationResponse.model_validate(cred) for cred in credentials]
    )


@router.post(
    "/dexcom",
    response_model=IntegrationConnectResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Dexcom connected successfully"},
        400: {"model": ErrorResponse, "description": "Invalid credentials"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
    },
)
async def connect_dexcom(
    request: DexcomCredentialsRequest,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> IntegrationConnectResponse:
    """Connect Dexcom Share account.

    Validates the provided credentials and stores them encrypted
    in the database. If credentials already exist, they are updated.
    """
    # Validate credentials first
    is_valid, error_message = validate_dexcom_credentials(
        request.username,
        request.password,
    )

    if not is_valid:
        logger.warning(
            "Dexcom connection failed",
            user_id=str(current_user.id),
            error=error_message,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_message,
        )

    # Check if integration already exists
    result = await db.execute(
        select(IntegrationCredential).where(
            IntegrationCredential.user_id == current_user.id,
            IntegrationCredential.integration_type == IntegrationType.DEXCOM,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Update existing credentials
        existing.encrypted_username = encrypt_credential(request.username)
        existing.encrypted_password = encrypt_credential(request.password)
        existing.status = IntegrationStatus.CONNECTED
        existing.last_error = None
        existing.updated_at = datetime.now(UTC)
        credential = existing
    else:
        # Create new credential
        credential = IntegrationCredential(
            user_id=current_user.id,
            integration_type=IntegrationType.DEXCOM,
            encrypted_username=encrypt_credential(request.username),
            encrypted_password=encrypt_credential(request.password),
            status=IntegrationStatus.CONNECTED,
        )
        db.add(credential)

    await db.commit()
    await db.refresh(credential)

    logger.info(
        "Dexcom connected successfully",
        user_id=str(current_user.id),
        integration_type="dexcom",
    )

    return IntegrationConnectResponse(
        message="Dexcom connected successfully",
        integration=IntegrationResponse.model_validate(credential),
    )


@router.delete(
    "/dexcom",
    response_model=IntegrationDisconnectResponse,
    responses={
        200: {"description": "Dexcom disconnected"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        404: {"model": ErrorResponse, "description": "Integration not found"},
    },
)
async def disconnect_dexcom(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> IntegrationDisconnectResponse:
    """Disconnect Dexcom Share account.

    Removes the stored credentials and marks the integration as disconnected.
    """
    result = await db.execute(
        select(IntegrationCredential).where(
            IntegrationCredential.user_id == current_user.id,
            IntegrationCredential.integration_type == IntegrationType.DEXCOM,
        )
    )
    credential = result.scalar_one_or_none()

    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dexcom integration not found",
        )

    await db.delete(credential)
    await db.commit()

    logger.info(
        "Dexcom disconnected",
        user_id=str(current_user.id),
        integration_type="dexcom",
    )

    return IntegrationDisconnectResponse(message="Dexcom disconnected successfully")


@router.get(
    "/dexcom/status",
    response_model=IntegrationResponse,
    responses={
        200: {"description": "Dexcom integration status"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        404: {"model": ErrorResponse, "description": "Integration not found"},
    },
)
async def get_dexcom_status(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> IntegrationResponse:
    """Get the current Dexcom integration status."""
    result = await db.execute(
        select(IntegrationCredential).where(
            IntegrationCredential.user_id == current_user.id,
            IntegrationCredential.integration_type == IntegrationType.DEXCOM,
        )
    )
    credential = result.scalar_one_or_none()

    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dexcom integration not found",
        )

    return IntegrationResponse.model_validate(credential)


# ============================================================================
# Story 3.3: Tandem t:connect Integration Endpoints
# ============================================================================


@router.post(
    "/tandem",
    response_model=IntegrationConnectResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Tandem t:connect connected successfully"},
        400: {"model": ErrorResponse, "description": "Invalid credentials"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
    },
)
async def connect_tandem(
    request: TandemCredentialsRequest,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> IntegrationConnectResponse:
    """Connect Tandem t:connect account.

    Validates the provided credentials and stores them encrypted
    in the database. If credentials already exist, they are updated.
    """
    # Validate credentials first (with region)
    is_valid, error_message = validate_tandem_credentials(
        request.username,
        request.password,
        request.region,
    )

    if not is_valid:
        logger.warning(
            "Tandem connection failed",
            user_id=str(current_user.id),
            error=error_message,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_message,
        )

    # Check if integration already exists
    result = await db.execute(
        select(IntegrationCredential).where(
            IntegrationCredential.user_id == current_user.id,
            IntegrationCredential.integration_type == IntegrationType.TANDEM,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Update existing credentials
        existing.encrypted_username = encrypt_credential(request.username)
        existing.encrypted_password = encrypt_credential(request.password)
        existing.region = request.region
        existing.status = IntegrationStatus.CONNECTED
        existing.last_error = None
        existing.updated_at = datetime.now(UTC)
        credential = existing
    else:
        # Create new credential
        credential = IntegrationCredential(
            user_id=current_user.id,
            integration_type=IntegrationType.TANDEM,
            encrypted_username=encrypt_credential(request.username),
            encrypted_password=encrypt_credential(request.password),
            region=request.region,
            status=IntegrationStatus.CONNECTED,
        )
        db.add(credential)

    await db.commit()
    await db.refresh(credential)

    logger.info(
        "Tandem t:connect connected successfully",
        user_id=str(current_user.id),
        integration_type="tandem",
    )

    return IntegrationConnectResponse(
        message="Tandem t:connect connected successfully",
        integration=IntegrationResponse.model_validate(credential),
    )


@router.delete(
    "/tandem",
    response_model=IntegrationDisconnectResponse,
    responses={
        200: {"description": "Tandem disconnected"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        404: {"model": ErrorResponse, "description": "Integration not found"},
    },
)
async def disconnect_tandem(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> IntegrationDisconnectResponse:
    """Disconnect Tandem t:connect account.

    Removes the stored credentials and marks the integration as disconnected.
    """
    result = await db.execute(
        select(IntegrationCredential).where(
            IntegrationCredential.user_id == current_user.id,
            IntegrationCredential.integration_type == IntegrationType.TANDEM,
        )
    )
    credential = result.scalar_one_or_none()

    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tandem integration not found",
        )

    await db.delete(credential)
    await db.commit()

    logger.info(
        "Tandem disconnected",
        user_id=str(current_user.id),
        integration_type="tandem",
    )

    return IntegrationDisconnectResponse(
        message="Tandem t:connect disconnected successfully"
    )


@router.get(
    "/tandem/status",
    response_model=IntegrationResponse,
    responses={
        200: {"description": "Tandem integration status"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        404: {"model": ErrorResponse, "description": "Integration not found"},
    },
)
async def get_tandem_status(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> IntegrationResponse:
    """Get the current Tandem t:connect integration status."""
    result = await db.execute(
        select(IntegrationCredential).where(
            IntegrationCredential.user_id == current_user.id,
            IntegrationCredential.integration_type == IntegrationType.TANDEM,
        )
    )
    credential = result.scalar_one_or_none()

    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tandem integration not found",
        )

    return IntegrationResponse.model_validate(credential)


# ============================================================================
# Story 3.2: Dexcom CGM Data Sync Endpoints
# ============================================================================


@router.post(
    "/dexcom/sync",
    response_model=SyncResponse,
    responses={
        200: {"description": "Sync completed"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        404: {"model": ErrorResponse, "description": "Dexcom not configured"},
        503: {"model": ErrorResponse, "description": "Dexcom service unavailable"},
    },
)
async def sync_dexcom_data(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> SyncResponse:
    """Manually trigger a Dexcom data sync.

    Fetches the latest glucose readings from Dexcom Share API
    and stores them in the database.
    """
    try:
        result = await sync_dexcom_for_user(db, current_user.id)

        last_reading = None
        if result["last_reading"]:
            last_reading = GlucoseReadingResponse(
                value=result["last_reading"]["value"],
                reading_timestamp=result["last_reading"]["timestamp"],
                trend=result["last_reading"]["trend"],
                trend_rate=None,
                received_at=datetime.now(UTC),
                source="dexcom",
            )

        return SyncResponse(
            message="Sync completed successfully",
            readings_fetched=result["readings_fetched"],
            readings_stored=result["readings_stored"],
            last_reading=last_reading,
        )

    except DexcomAuthError as e:
        logger.warning(
            "Dexcom sync failed - auth error",
            user_id=str(current_user.id),
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Dexcom credentials. Please reconnect your account.",
        ) from e

    except DexcomConnectionError as e:
        logger.warning(
            "Dexcom sync failed - connection error",
            user_id=str(current_user.id),
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to connect to Dexcom. Please try again later.",
        ) from e

    except DexcomSyncError as e:
        logger.error(
            "Dexcom sync failed",
            user_id=str(current_user.id),
            error=str(e),
        )
        if "not configured" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dexcom integration not configured",
            ) from e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync failed: {str(e)}",
        ) from e


@router.get(
    "/dexcom/sync/status",
    response_model=SyncStatusResponse,
    responses={
        200: {"description": "Sync status"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
    },
)
async def get_sync_status(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> SyncStatusResponse:
    """Get the current Dexcom sync status.

    Returns the integration status, last sync time, and latest reading.
    """
    # Get integration status
    result = await db.execute(
        select(IntegrationCredential).where(
            IntegrationCredential.user_id == current_user.id,
            IntegrationCredential.integration_type == IntegrationType.DEXCOM,
        )
    )
    credential = result.scalar_one_or_none()

    # Count readings
    count_result = await db.execute(
        select(func.count(GlucoseReading.id)).where(
            GlucoseReading.user_id == current_user.id
        )
    )
    readings_count = count_result.scalar() or 0

    # Get latest reading
    latest = await get_latest_glucose_reading(db, current_user.id)
    latest_response = None
    if latest:
        latest_response = GlucoseReadingResponse.model_validate(latest)

    return SyncStatusResponse(
        integration_status=credential.status.value if credential else "not_configured",
        last_sync_at=credential.last_sync_at if credential else None,
        last_error=credential.last_error if credential else None,
        readings_available=readings_count,
        latest_reading=latest_response,
    )


@router.get(
    "/glucose/current",
    response_model=CurrentGlucoseResponse,
    responses={
        200: {"description": "Current glucose reading"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        404: {"model": ErrorResponse, "description": "No readings available"},
    },
)
async def get_current_glucose(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> CurrentGlucoseResponse:
    """Get the current (most recent) glucose reading.

    Returns the latest glucose value with trend and staleness indicator.
    """
    latest = await get_latest_glucose_reading(db, current_user.id)

    if not latest:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No glucose readings available. Please sync with Dexcom first.",
        )

    now = datetime.now(UTC)
    reading_time = latest.reading_timestamp
    if reading_time.tzinfo is None:
        reading_time = reading_time.replace(tzinfo=UTC)

    minutes_ago = int((now - reading_time).total_seconds() / 60)
    is_stale = minutes_ago > 10

    return CurrentGlucoseResponse(
        value=latest.value,
        trend=latest.trend,
        trend_rate=latest.trend_rate,
        reading_timestamp=latest.reading_timestamp,
        minutes_ago=minutes_ago,
        is_stale=is_stale,
    )


@router.get(
    "/glucose/history",
    response_model=GlucoseHistoryResponse,
    responses={
        200: {"description": "Glucose reading history"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
    },
)
@limiter.limit("30/minute")
async def get_glucose_history(
    request: Request,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
    minutes: int = Query(
        default=180, ge=5, le=43200, description="Minutes of history (max 30d)"
    ),
    limit: int = Query(default=36, ge=1, le=8640, description="Max readings to return"),
) -> GlucoseHistoryResponse:
    """Get glucose reading history.

    Returns recent glucose readings for the specified time period.
    Default is 3 hours (180 minutes), max is 30 days (43200 minutes).
    For longer periods, consider using fewer readings with client-side
    downsampling (e.g., LTTB) for chart rendering.
    """
    readings = await get_glucose_readings(
        db, current_user.id, minutes=minutes, limit=limit
    )

    return GlucoseHistoryResponse(
        readings=[GlucoseReadingResponse.model_validate(r) for r in readings],
        count=len(readings),
    )


@router.get(
    "/glucose/time-in-range",
    response_model=None,
    responses={
        200: {
            "description": "Time in range statistics",
            "content": {
                "application/json": {
                    "schema": {
                        "oneOf": [
                            {"$ref": "#/components/schemas/TimeInRangeResponse"},
                            {"$ref": "#/components/schemas/TimeInRangeDetailResponse"},
                        ]
                    }
                }
            },
        },
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
    },
)
@limiter.limit("30/minute")
async def get_time_in_range(
    request: Request,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
    minutes: int = Query(
        default=1440,
        ge=60,
        le=43200,
        description="Analysis window in minutes (max 30d)",
    ),
    include_details: bool = Query(
        default=False,
        description="Return 5-bucket detail with previous period comparison",
    ),
) -> TimeInRangeResponse | TimeInRangeDetailResponse:
    """Get time-in-range statistics for the specified period.

    Calculates the percentage of glucose readings that fall below, within,
    and above the user's configured target range.

    When include_details=true, returns 5-bucket clinical breakdown
    (urgent_low, low, in_range, high, urgent_high) with previous-period
    comparison data.
    """
    # Fetch user's target range thresholds
    target_range = await get_or_create_range(current_user.id, db)
    low_threshold = target_range.low_target
    high_threshold = target_range.high_target

    if not include_details:
        # Original 3-bucket response (backward compatible)
        cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
        result = await db.execute(
            select(
                func.count().label("total"),
                func.sum(
                    case((GlucoseReading.value < low_threshold, 1), else_=0)
                ).label("low_count"),
                func.sum(
                    case((GlucoseReading.value > high_threshold, 1), else_=0)
                ).label("high_count"),
            ).where(
                GlucoseReading.user_id == current_user.id,
                GlucoseReading.reading_timestamp >= cutoff,
            )
        )
        row = result.one()
        count = row.total
        low_count = row.low_count or 0
        high_count = row.high_count or 0

        if count == 0:
            return TimeInRangeResponse(
                low_pct=0.0,
                in_range_pct=0.0,
                high_pct=0.0,
                readings_count=0,
                low_threshold=low_threshold,
                high_threshold=high_threshold,
            )

        low_pct = round((low_count / count) * 100, 1)
        high_pct = round((high_count / count) * 100, 1)
        in_range_pct = round(100 - low_pct - high_pct, 1)

        return TimeInRangeResponse(
            low_pct=low_pct,
            in_range_pct=in_range_pct,
            high_pct=high_pct,
            readings_count=count,
            low_threshold=low_threshold,
            high_threshold=high_threshold,
        )

    # 5-bucket detail response
    urgent_low = target_range.urgent_low
    urgent_high = target_range.urgent_high
    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=minutes)

    buckets_result = await _query_5_buckets(
        db,
        current_user.id,
        cutoff,
        now,
        urgent_low,
        low_threshold,
        high_threshold,
        urgent_high,
    )

    # Previous period: same duration ending at cutoff
    prev_start = cutoff - timedelta(minutes=minutes)
    prev_result = await _query_5_buckets(
        db,
        current_user.id,
        prev_start,
        cutoff,
        urgent_low,
        low_threshold,
        high_threshold,
        urgent_high,
    )

    previous_buckets = None
    previous_count = None
    if prev_result["total"] >= _MIN_PREV_PERIOD_READINGS:
        previous_buckets = _build_tir_buckets(
            prev_result,
            urgent_low,
            low_threshold,
            high_threshold,
            urgent_high,
        )
        previous_count = prev_result["total"]

    thresholds = TirThresholds(
        urgent_low=urgent_low,
        low=low_threshold,
        high=high_threshold,
        urgent_high=urgent_high,
    )

    return TimeInRangeDetailResponse(
        buckets=_build_tir_buckets(
            buckets_result,
            urgent_low,
            low_threshold,
            high_threshold,
            urgent_high,
        ),
        readings_count=buckets_result["total"],
        previous_buckets=previous_buckets,
        previous_readings_count=previous_count,
        thresholds=thresholds,
    )


async def _query_5_buckets(
    db: AsyncSession,
    user_id,
    start: datetime,
    end: datetime,
    urgent_low: float,
    low: float,
    high: float,
    urgent_high: float,
) -> dict:
    """Query 5-bucket TIR counts for a time window."""
    result = await db.execute(
        select(
            func.count().label("total"),
            func.sum(case((GlucoseReading.value < urgent_low, 1), else_=0)).label(
                "urgent_low_count"
            ),
            func.sum(
                case(
                    (
                        and_(
                            GlucoseReading.value >= urgent_low,
                            GlucoseReading.value < low,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("low_count"),
            func.sum(
                case(
                    (
                        and_(
                            GlucoseReading.value >= low,
                            GlucoseReading.value <= high,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("in_range_count"),
            func.sum(
                case(
                    (
                        and_(
                            GlucoseReading.value > high,
                            GlucoseReading.value <= urgent_high,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("high_count"),
            func.sum(case((GlucoseReading.value > urgent_high, 1), else_=0)).label(
                "urgent_high_count"
            ),
        ).where(
            GlucoseReading.user_id == user_id,
            GlucoseReading.reading_timestamp >= start,
            GlucoseReading.reading_timestamp < end,
        )
    )
    row = result.one()
    return {
        "total": row.total or 0,
        "urgent_low_count": row.urgent_low_count or 0,
        "low_count": row.low_count or 0,
        "in_range_count": row.in_range_count or 0,
        "high_count": row.high_count or 0,
        "urgent_high_count": row.urgent_high_count or 0,
    }


def _build_tir_buckets(
    counts: dict,
    urgent_low: float,
    low: float,
    high: float,
    urgent_high: float,
) -> list[TirBucket]:
    """Build ordered list of 5 TirBucket objects from query counts."""
    total = counts["total"]
    if total == 0:
        return [
            TirBucket(
                label="urgent_low",
                pct=0.0,
                readings=0,
                threshold_low=None,
                threshold_high=urgent_low,
            ),
            TirBucket(
                label="low",
                pct=0.0,
                readings=0,
                threshold_low=urgent_low,
                threshold_high=low,
            ),
            TirBucket(
                label="in_range",
                pct=0.0,
                readings=0,
                threshold_low=low,
                threshold_high=high,
            ),
            TirBucket(
                label="high",
                pct=0.0,
                readings=0,
                threshold_low=high,
                threshold_high=urgent_high,
            ),
            TirBucket(
                label="urgent_high",
                pct=0.0,
                readings=0,
                threshold_low=urgent_high,
                threshold_high=None,
            ),
        ]

    labels = ["urgent_low", "low", "in_range", "high", "urgent_high"]
    count_keys = [
        "urgent_low_count",
        "low_count",
        "in_range_count",
        "high_count",
        "urgent_high_count",
    ]
    thresholds_low = [None, urgent_low, low, high, urgent_high]
    thresholds_high = [urgent_low, low, high, urgent_high, None]

    # Calculate percentages: round 4 independently, derive in_range to ensure sum = 100
    raw_pcts = [(counts[k] / total) * 100 for k in count_keys]
    rounded = [round(p, 1) for p in raw_pcts]
    # Adjust in_range (index 2) to absorb rounding drift
    others_sum = sum(rounded[i] for i in [0, 1, 3, 4])
    rounded[2] = max(0.0, round(100.0 - others_sum, 1))

    buckets = []
    for i, label in enumerate(labels):
        buckets.append(
            TirBucket(
                label=label,
                pct=rounded[i],
                readings=counts[count_keys[i]],
                threshold_low=thresholds_low[i],
                threshold_high=thresholds_high[i],
            )
        )
    return buckets


# ============================================================================
# Story 3.4: Tandem Pump Data Sync Endpoints
# ============================================================================


@router.post(
    "/tandem/sync",
    response_model=TandemSyncResponse,
    responses={
        200: {"description": "Sync completed"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        404: {"model": ErrorResponse, "description": "Tandem not configured"},
        503: {"model": ErrorResponse, "description": "Tandem service unavailable"},
    },
)
async def sync_tandem_data(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> TandemSyncResponse:
    """Manually trigger a Tandem pump data sync.

    Fetches the latest pump events from Tandem t:connect API
    and stores them in the database.
    """
    try:
        result = await sync_tandem_for_user(db, current_user.id)

        last_event = None
        if result["last_event"]:
            # Create a minimal response for the last event
            last_event = PumpEventResponse(
                event_type=result["last_event"]["event_type"],
                event_timestamp=result["last_event"]["timestamp"],
                units=result["last_event"]["units"],
                is_automated=result["last_event"]["is_automated"],
                received_at=datetime.now(UTC),
                source="tandem",
            )

        return TandemSyncResponse(
            message="Sync completed successfully",
            events_fetched=result["events_fetched"],
            events_stored=result["events_stored"],
            profiles_stored=result.get("profiles_stored", 0),
            last_event=last_event,
        )

    except TandemAuthError as e:
        logger.warning(
            "Tandem sync failed - auth error",
            user_id=str(current_user.id),
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Tandem credentials. Please reconnect your account.",
        ) from e

    except TandemConnectionError as e:
        logger.warning(
            "Tandem sync failed - connection error",
            user_id=str(current_user.id),
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to connect to Tandem. Please try again later.",
        ) from e

    except TandemNotConfiguredError as e:
        logger.warning(
            "Tandem sync failed - not configured",
            user_id=str(current_user.id),
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tandem integration not configured",
        ) from e

    except TandemSyncError as e:
        logger.error(
            "Tandem sync failed",
            user_id=str(current_user.id),
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync failed: {str(e)}",
        ) from e


@router.get(
    "/tandem/sync/status",
    response_model=TandemSyncStatusResponse,
    responses={
        200: {"description": "Sync status"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
    },
)
async def get_tandem_sync_status(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> TandemSyncStatusResponse:
    """Get the current Tandem sync status.

    Returns the integration status, last sync time, and latest event.
    """
    # Get integration status
    result = await db.execute(
        select(IntegrationCredential).where(
            IntegrationCredential.user_id == current_user.id,
            IntegrationCredential.integration_type == IntegrationType.TANDEM,
        )
    )
    credential = result.scalar_one_or_none()

    # Count events
    count_result = await db.execute(
        select(func.count(PumpEvent.id)).where(PumpEvent.user_id == current_user.id)
    )
    events_count = count_result.scalar() or 0

    # Get latest event
    latest = await get_latest_pump_event(db, current_user.id)
    latest_response = None
    if latest:
        latest_response = PumpEventResponse.model_validate(latest)

    return TandemSyncStatusResponse(
        integration_status=credential.status.value if credential else "not_configured",
        last_sync_at=credential.last_sync_at if credential else None,
        last_error=credential.last_error if credential else None,
        events_available=events_count,
        latest_event=latest_response,
    )


@router.get(
    "/pump/history",
    response_model=PumpEventHistoryResponse,
    responses={
        200: {"description": "Pump event history"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
    },
)
@limiter.limit("30/minute")
async def get_pump_event_history(
    request: Request,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
    minutes: int = Query(
        default=180, ge=5, le=43200, description="Minutes of history (max 30d)"
    ),
    limit: int = Query(default=500, ge=1, le=5000, description="Max events to return"),
    event_type: PumpEventType | None = Query(default=None),
) -> PumpEventHistoryResponse:
    """Get pump event history for the current user.

    Returns bolus, basal, and other pump events within the specified time window.
    Max 30 days (43200 minutes). Used by the dashboard chart to overlay
    insulin delivery on the glucose graph.
    """
    events = await get_pump_events(
        db, current_user.id, hours=minutes / 60, limit=limit, event_type=event_type
    )
    return PumpEventHistoryResponse(
        events=[PumpEventResponse.model_validate(e) for e in events],
        count=len(events),
    )


@router.get(
    "/pump/status",
    response_model=PumpStatusResponse,
    responses={
        200: {"description": "Latest pump status (basal, battery, reservoir)"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
    },
)
async def get_pump_status(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> PumpStatusResponse:
    """Get latest pump status for the dashboard hero card.

    Returns the most recent basal rate, battery percentage, and reservoir
    level from synced pump events.

    Field mapping notes:
    - PumpEvent.units stores the numeric value (rate, percentage, or units remaining)
    - PumpEvent.is_automated is reused for battery events to store is_charging
      (Tandem pumps use non-rechargeable batteries so this is always False)
    """
    status = await get_latest_pump_status(db, current_user.id)

    basal_event = status.get("basal")
    battery_event = status.get("battery")
    reservoir_event = status.get("reservoir")

    return PumpStatusResponse(
        basal=PumpStatusBasal(
            rate=basal_event.units or 0.0,
            is_automated=basal_event.is_automated,
            timestamp=basal_event.event_timestamp,
        )
        if basal_event
        else None,
        battery=PumpStatusBattery(
            percentage=int(battery_event.units or 0),
            is_charging=battery_event.is_automated,
            timestamp=battery_event.event_timestamp,
        )
        if battery_event
        else None,
        reservoir=PumpStatusReservoir(
            units_remaining=reservoir_event.units or 0.0,
            timestamp=reservoir_event.event_timestamp,
        )
        if reservoir_event
        else None,
    )


@router.get(
    "/tandem/control-iq/activity",
    response_model=ControlIQActivityResponse,
    responses={
        200: {"description": "Control-IQ activity summary"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
    },
)
async def get_control_iq_activity_summary(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
    hours: int = Query(
        default=24, ge=1, le=168, description="Hours of history to analyze"
    ),
) -> ControlIQActivityResponse:
    """Get a summary of Control-IQ activity (Story 3.5).

    This endpoint provides aggregated metrics about Control-IQ automated actions,
    including:
    - Automatic correction boluses
    - Basal rate adjustments (increases and decreases)
    - Automated insulin suspends
    - Activity mode usage (Sleep, Exercise, Standard)

    This data helps AI analysis focus on what Control-IQ cannot adjust
    (carb ratios, correction factors) rather than what it's already handling.

    Args:
        hours: Number of hours of history to analyze (1-168, default 24)

    Returns:
        ControlIQActivityResponse with aggregated metrics
    """
    activity = await get_control_iq_activity(db, current_user.id, hours=hours)

    return ControlIQActivityResponse(
        total_events=activity.total_events,
        automated_events=activity.automated_events,
        manual_events=activity.manual_events,
        correction_count=activity.correction_count,
        total_correction_units=activity.total_correction_units,
        basal_increase_count=activity.basal_increase_count,
        basal_decrease_count=activity.basal_decrease_count,
        avg_basal_adjustment_pct=activity.avg_basal_adjustment_pct,
        suspend_count=activity.suspend_count,
        automated_suspend_count=activity.automated_suspend_count,
        sleep_mode_events=activity.sleep_mode_events,
        exercise_mode_events=activity.exercise_mode_events,
        standard_mode_events=activity.standard_mode_events,
        start_time=activity.start_time,
        end_time=activity.end_time,
        hours_analyzed=hours,
    )


@router.get(
    "/tandem/iob/projection",
    response_model=IoBProjectionResponse,
    responses={
        200: {"description": "IoB projection data"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        404: {"model": ErrorResponse, "description": "No IoB data available"},
    },
)
async def get_iob_projection_endpoint(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> IoBProjectionResponse:
    """Get projected insulin-on-board (IoB) values (Story 3.7).

    This endpoint provides:
    - Last confirmed IoB from the pump
    - Current projected IoB based on insulin decay curve
    - Projected IoB values for 30 and 60 minutes ahead
    - Staleness warning if data is over 2 hours old

    Uses the user's configured DIA (defaults to 4 hours for Humalog/Novolog).

    Returns:
        IoBProjectionResponse with confirmed and projected IoB values
    """
    dia = await get_user_dia(db, current_user.id)
    projection = await get_iob_projection(db, current_user.id, dia_hours=dia)

    if projection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No IoB data available. Please sync your pump data first.",
        )

    return IoBProjectionResponse(
        confirmed_iob=projection.confirmed_iob,
        confirmed_at=projection.confirmed_at,
        projected_iob=projection.projected_iob,
        projected_at=projection.projected_at,
        projected_30min=projection.projected_30min,
        projected_60min=projection.projected_60min,
        minutes_since_confirmed=projection.minutes_since_confirmed,
        is_stale=projection.is_stale,
        stale_warning=projection.stale_warning,
        is_estimated=projection.is_estimated,
    )


# ============================================================================
# Story 16.5: Mobile Pump Push Endpoint
# ============================================================================


@router.post(
    "/pump/push",
    response_model=PumpPushResponse,
    responses={
        200: {"description": "Pump events processed"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
@limiter.limit("60/minute")
async def push_pump_events(
    body: PumpPushRequest,
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> PumpPushResponse:
    """Accept a batch of pump events from a mobile client.

    Uses PostgreSQL ON CONFLICT DO NOTHING on the existing unique index
    (user_id, event_timestamp, event_type) for idempotent inserts.
    """
    now = datetime.now(UTC)
    rows = []
    for item in body.events:
        ts = item.event_timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        rows.append(
            {
                "user_id": current_user.id,
                "event_type": item.event_type,
                "event_timestamp": ts,
                "units": item.units,
                "duration_minutes": item.duration_minutes,
                "is_automated": item.is_automated,
                "control_iq_mode": item.control_iq_mode,
                "basal_adjustment_pct": item.basal_adjustment_pct,
                "iob_at_event": item.iob_at_event,
                "bg_at_event": item.bg_at_event,
                "received_at": now,
                "source": body.source,
            }
        )

    stmt = (
        pg_insert(PumpEvent)
        .values(rows)
        .on_conflict_do_nothing(
            index_elements=["user_id", "event_timestamp", "event_type"],
        )
    )
    result = await db.execute(stmt)

    accepted = max(result.rowcount, 0)
    duplicates = len(rows) - accepted

    # Store raw events for Tandem cloud upload (Story 16.6)
    raw_accepted = 0
    raw_duplicates = 0
    if body.raw_events:
        raw_rows = [
            {
                "user_id": current_user.id,
                "sequence_number": item.sequence_number,
                "raw_bytes_b64": item.raw_bytes_b64,
                "event_type_id": item.event_type_id,
                "pump_time_seconds": item.pump_time_seconds,
            }
            for item in body.raw_events
        ]
        raw_stmt = (
            pg_insert(PumpRawEvent)
            .values(raw_rows)
            .on_conflict_do_nothing(
                constraint="uq_pump_raw_event_user_seq",
            )
        )
        raw_result = await db.execute(raw_stmt)
        raw_accepted = max(raw_result.rowcount, 0)
        raw_duplicates = len(raw_rows) - raw_accepted

    # Upsert pump hardware info (Story 16.6)
    if body.pump_info:
        hw_stmt = (
            pg_insert(PumpHardwareInfo)
            .values(
                user_id=current_user.id,
                serial_number=body.pump_info.serial_number,
                model_number=body.pump_info.model_number,
                part_number=body.pump_info.part_number,
                pump_rev=body.pump_info.pump_rev,
                arm_sw_ver=body.pump_info.arm_sw_ver,
                msp_sw_ver=body.pump_info.msp_sw_ver,
                config_a_bits=body.pump_info.config_a_bits,
                config_b_bits=body.pump_info.config_b_bits,
                pcba_sn=body.pump_info.pcba_sn,
                pcba_rev=body.pump_info.pcba_rev,
                pump_features=body.pump_info.pump_features,
            )
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    "serial_number": body.pump_info.serial_number,
                    "model_number": body.pump_info.model_number,
                    "part_number": body.pump_info.part_number,
                    "pump_rev": body.pump_info.pump_rev,
                    "arm_sw_ver": body.pump_info.arm_sw_ver,
                    "msp_sw_ver": body.pump_info.msp_sw_ver,
                    "config_a_bits": body.pump_info.config_a_bits,
                    "config_b_bits": body.pump_info.config_b_bits,
                    "pcba_sn": body.pump_info.pcba_sn,
                    "pcba_rev": body.pump_info.pcba_rev,
                    "pump_features": body.pump_info.pump_features,
                    "updated_at": now,
                },
            )
        )
        await db.execute(hw_stmt)

    await db.commit()

    logger.info(
        "Mobile pump push",
        user_id=str(current_user.id),
        total=len(rows),
        accepted=accepted,
        duplicates=duplicates,
        raw_accepted=raw_accepted,
        raw_duplicates=raw_duplicates,
    )

    return PumpPushResponse(
        accepted=accepted,
        duplicates=duplicates,
        raw_accepted=raw_accepted,
        raw_duplicates=raw_duplicates,
    )


# ============================================================================
# Story 16.6: Tandem Cloud Upload Endpoints
# ============================================================================


@router.get(
    "/tandem/cloud-upload/status",
    response_model=TandemUploadStatusResponse,
    responses={
        200: {"description": "Tandem upload status"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def get_tandem_upload_status(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> TandemUploadStatusResponse:
    """Get the Tandem cloud upload status for the current user."""
    result = await db.execute(
        select(TandemUploadState).where(TandemUploadState.user_id == current_user.id)
    )
    state = result.scalar_one_or_none()

    # Count pending raw events
    pending_result = await db.execute(
        select(func.count(PumpRawEvent.id)).where(
            PumpRawEvent.user_id == current_user.id,
            PumpRawEvent.uploaded_to_tandem.is_(False),
        )
    )
    pending_count = pending_result.scalar() or 0

    if not state:
        return TandemUploadStatusResponse(
            enabled=False,
            upload_interval_minutes=15,
            pending_raw_events=pending_count,
        )

    return TandemUploadStatusResponse(
        enabled=state.enabled,
        upload_interval_minutes=state.upload_interval_minutes,
        last_upload_at=state.last_upload_at,
        last_upload_status=state.last_upload_status,
        last_error=state.last_error,
        max_event_index_uploaded=state.max_event_index_uploaded,
        pending_raw_events=pending_count,
    )


@router.put(
    "/tandem/cloud-upload/settings",
    response_model=TandemUploadStatusResponse,
    responses={
        200: {"description": "Settings updated"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def update_tandem_upload_settings(
    request: TandemUploadSettingsRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> TandemUploadStatusResponse:
    """Enable/disable Tandem cloud upload and set interval."""
    result = await db.execute(
        select(TandemUploadState).where(TandemUploadState.user_id == current_user.id)
    )
    state = result.scalar_one_or_none()

    if state:
        state.enabled = request.enabled
        state.upload_interval_minutes = request.interval_minutes
    else:
        state = TandemUploadState(
            user_id=current_user.id,
            enabled=request.enabled,
            upload_interval_minutes=request.interval_minutes,
        )
        db.add(state)

    await db.commit()
    await db.refresh(state)

    # Count pending raw events
    pending_result = await db.execute(
        select(func.count(PumpRawEvent.id)).where(
            PumpRawEvent.user_id == current_user.id,
            PumpRawEvent.uploaded_to_tandem.is_(False),
        )
    )
    pending_count = pending_result.scalar() or 0

    logger.info(
        "Tandem upload settings updated",
        user_id=str(current_user.id),
        enabled=request.enabled,
        interval=request.interval_minutes,
    )

    return TandemUploadStatusResponse(
        enabled=state.enabled,
        upload_interval_minutes=state.upload_interval_minutes,
        last_upload_at=state.last_upload_at,
        last_upload_status=state.last_upload_status,
        last_error=state.last_error,
        max_event_index_uploaded=state.max_event_index_uploaded,
        pending_raw_events=pending_count,
    )


@router.post(
    "/tandem/cloud-upload/trigger",
    response_model=TandemUploadTriggerResponse,
    responses={
        200: {"description": "Upload triggered"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Tandem not configured"},
        500: {"model": ErrorResponse, "description": "Upload failed"},
    },
)
async def trigger_tandem_upload(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> TandemUploadTriggerResponse:
    """Manually trigger a Tandem cloud upload.

    Uploads pending raw events to the Tandem cloud immediately.
    """
    # Verify Tandem credentials exist
    cred_result = await db.execute(
        select(IntegrationCredential).where(
            IntegrationCredential.user_id == current_user.id,
            IntegrationCredential.integration_type == IntegrationType.TANDEM,
        )
    )
    if not cred_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tandem integration not configured. Please connect your Tandem account first.",
        )

    # Import here to avoid circular imports
    from src.services.tandem_upload import upload_to_tandem

    try:
        result = await upload_to_tandem(db, current_user.id)
        return TandemUploadTriggerResponse(
            message=result.get("message", "Upload complete"),
            events_uploaded=result.get("events_uploaded", 0),
            status=result.get("status", "success"),
        )
    except Exception as e:
        logger.error(
            "Tandem upload trigger failed",
            user_id=str(current_user.id),
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Upload failed. Please try again later.",
        ) from e


# --- Story 30.1: Aggregate statistics endpoints ---

# Maximum rows to load into memory for percentile calculation
_AGP_MAX_ROWS = 50_000
# Hard safety cap for insulin units (Tandem X2/Mobi max single bolus = 25U)
_MAX_BOLUS_UNITS = 25


def _compute_percentile(data: list[float], pct: float) -> float:
    """Compute percentile using linear interpolation (matching numpy default)."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (pct / 100)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return round(sorted_data[int(k)], 1)
    return round(sorted_data[f] * (c - k) + sorted_data[c] * (k - f), 1)


@router.get(
    "/glucose/stats",
    response_model=GlucoseStatsResponse,
    responses={
        200: {"description": "Aggregate glucose statistics"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
    },
)
@limiter.limit("30/minute")
async def get_glucose_stats(
    request: Request,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
    minutes: int = Query(
        default=1440,
        ge=60,
        le=43200,
        description="Analysis window in minutes (max 30d)",
    ),
) -> GlucoseStatsResponse:
    """Get aggregate glucose statistics: mean, SD, CV%, GMI, CGM active%.

    GMI (Glucose Management Indicator) estimates A1C from mean glucose
    using the formula: GMI = 3.31 + (0.02392 * mean_glucose_mg_dl).

    CGM active % assumes 5-minute reading intervals (standard for Dexcom G6/G7).
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=minutes)

    result = await db.execute(
        select(
            func.count().label("total"),
            func.avg(GlucoseReading.value).label("mean"),
            func.stddev_pop(GlucoseReading.value).label("stddev"),
        ).where(
            GlucoseReading.user_id == current_user.id,
            GlucoseReading.reading_timestamp >= cutoff,
            GlucoseReading.value >= 20,
            GlucoseReading.value <= 500,
        )
    )
    row = result.one()
    count = row.total or 0
    mean = float(row.mean) if row.mean is not None else 0.0
    sd = float(row.stddev) if row.stddev is not None else 0.0

    if count == 0:
        return GlucoseStatsResponse(
            mean_glucose=0.0,
            std_dev=0.0,
            cv_pct=0.0,
            gmi=0.0,
            cgm_active_pct=0.0,
            readings_count=0,
            period_minutes=minutes,
        )

    cv = round((sd / mean) * 100, 1) if mean > 0 else 0.0
    # GMI formula: Bergenstal et al. 2018
    gmi = round(3.31 + (0.02392 * mean), 1)
    # CGM active %: readings / expected readings (1 per 5 min, Dexcom standard)
    expected_readings = minutes / 5
    cgm_active = round(min((count / expected_readings) * 100, 100.0), 1)

    return GlucoseStatsResponse(
        mean_glucose=round(mean, 1),
        std_dev=round(sd, 1),
        cv_pct=cv,
        gmi=gmi,
        cgm_active_pct=cgm_active,
        readings_count=count,
        period_minutes=minutes,
    )


@router.get(
    "/glucose/percentiles",
    response_model=GlucosePercentilesResponse,
    responses={
        200: {"description": "AGP percentile bands by hour of day"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
    },
)
@limiter.limit("15/minute")
async def get_glucose_percentiles(
    request: Request,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
    days: int = Query(
        default=14,
        ge=7,
        le=90,
        description="Number of days to analyze (min 7 for AGP)",
    ),
    tz: str = Query(
        default="UTC",
        max_length=50,
        description="IANA timezone for hour grouping (e.g. America/Chicago)",
    ),
) -> GlucosePercentilesResponse:
    """Get AGP (Ambulatory Glucose Profile) percentile bands.

    Returns 10th, 25th, 50th, 75th, and 90th percentile glucose values
    grouped by hour of day in the specified timezone.
    Requires at least 7 days of data.
    """
    # Validate timezone
    try:
        user_tz = zoneinfo.ZoneInfo(tz)
    except (KeyError, zoneinfo.ZoneInfoNotFoundError) as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid timezone: {tz}",
        ) from e

    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Fetch readings with a hard row cap to prevent memory issues
    result = await db.execute(
        select(
            GlucoseReading.reading_timestamp,
            GlucoseReading.value,
        )
        .where(
            GlucoseReading.user_id == current_user.id,
            GlucoseReading.reading_timestamp >= cutoff,
            GlucoseReading.value >= 20,
            GlucoseReading.value <= 500,
        )
        .order_by(GlucoseReading.reading_timestamp)
        .limit(_AGP_MAX_ROWS)
    )
    rows = result.all()

    # Group values by hour in the user's timezone
    hourly: dict[int, list[float]] = {h: [] for h in range(24)}
    for row in rows:
        ts = row.reading_timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        local_ts = ts.astimezone(user_tz)
        hourly[local_ts.hour].append(float(row.value))

    buckets = []
    for h in range(24):
        vals = hourly[h]
        buckets.append(
            AGPBucket(
                hour=h,
                p10=_compute_percentile(vals, 10),
                p25=_compute_percentile(vals, 25),
                p50=_compute_percentile(vals, 50),
                p75=_compute_percentile(vals, 75),
                p90=_compute_percentile(vals, 90),
                count=len(vals),
            )
        )

    return GlucosePercentilesResponse(
        buckets=buckets,
        period_days=days,
        readings_count=len(rows),
        is_truncated=len(rows) >= _AGP_MAX_ROWS,
    )


@router.get(
    "/insulin/summary",
    response_model=InsulinSummaryResponse,
    responses={
        200: {"description": "Insulin delivery summary"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
    },
)
@limiter.limit("30/minute")
async def get_insulin_summary(
    request: Request,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
    days: int = Query(
        default=14,
        ge=1,
        le=90,
        description="Number of days to analyze",
    ),
) -> InsulinSummaryResponse:
    """Get insulin delivery summary: TDD, basal/bolus split, bolus count.

    All unit values (tdd, basal_units, bolus_units, correction_units) are
    daily averages over the requested period. Counts (bolus_count,
    correction_count) are totals for the full period.
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Aggregate insulin by event type in SQL
    result = await db.execute(
        select(
            PumpEvent.event_type,
            PumpEvent.is_automated,
            func.coalesce(func.sum(PumpEvent.units), 0).label("total_units"),
            func.count().label("event_count"),
        )
        .where(
            PumpEvent.user_id == current_user.id,
            PumpEvent.event_timestamp >= cutoff,
            PumpEvent.units.is_not(None),
            PumpEvent.units >= 0,
            PumpEvent.units <= _MAX_BOLUS_UNITS,
            PumpEvent.event_type.in_(
                [
                    PumpEventType.BASAL,
                    PumpEventType.BOLUS,
                    PumpEventType.CORRECTION,
                ]
            ),
        )
        .group_by(PumpEvent.event_type, PumpEvent.is_automated)
    )
    rows = result.all()

    basal_units = 0.0
    bolus_units = 0.0
    correction_units = 0.0
    bolus_count = 0
    correction_count = 0

    for row in rows:
        units = float(row.total_units)
        if row.event_type == PumpEventType.BASAL:
            basal_units += units
        elif row.event_type == PumpEventType.BOLUS:
            bolus_units += units
            bolus_count += int(row.event_count)
        elif row.event_type == PumpEventType.CORRECTION:
            correction_units += units
            correction_count += int(row.event_count)

    tdd_total = basal_units + bolus_units + correction_units
    # Average per day
    tdd = round(tdd_total / max(days, 1), 1)
    basal_avg = round(basal_units / max(days, 1), 1)
    bolus_avg = round((bolus_units + correction_units) / max(days, 1), 1)
    correction_avg = round(correction_units / max(days, 1), 1)

    if tdd > 0:
        basal_pct = round((basal_avg / tdd) * 100, 1)
        bolus_pct = round(100 - basal_pct, 1)
    else:
        basal_pct = 0.0
        bolus_pct = 0.0

    return InsulinSummaryResponse(
        tdd=tdd,
        basal_units=basal_avg,
        bolus_units=bolus_avg,
        correction_units=correction_avg,
        basal_pct=basal_pct,
        bolus_pct=bolus_pct,
        bolus_count=bolus_count,
        correction_count=correction_count,
        period_days=days,
    )


@router.get(
    "/bolus/review",
    response_model=BolusReviewResponse,
    responses={
        200: {"description": "Bolus delivery review list"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
    },
)
@limiter.limit("15/minute")
async def get_bolus_review(
    request: Request,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
    days: int = Query(default=7, ge=1, le=30, description="Number of days"),
    limit: int = Query(default=100, ge=1, le=500, description="Max results"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
) -> BolusReviewResponse:
    """Get paginated list of bolus events for review."""
    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Count total
    count_result = await db.execute(
        select(func.count()).where(
            PumpEvent.user_id == current_user.id,
            PumpEvent.event_timestamp >= cutoff,
            PumpEvent.units.is_not(None),
            PumpEvent.units >= 0,
            PumpEvent.units <= _MAX_BOLUS_UNITS,
            PumpEvent.event_type.in_(
                [
                    PumpEventType.BOLUS,
                    PumpEventType.CORRECTION,
                ]
            ),
        )
    )
    total = count_result.scalar() or 0

    # Fetch page
    result = await db.execute(
        select(PumpEvent)
        .where(
            PumpEvent.user_id == current_user.id,
            PumpEvent.event_timestamp >= cutoff,
            PumpEvent.units.is_not(None),
            PumpEvent.units >= 0,
            PumpEvent.units <= _MAX_BOLUS_UNITS,
            PumpEvent.event_type.in_(
                [
                    PumpEventType.BOLUS,
                    PumpEventType.CORRECTION,
                ]
            ),
        )
        .order_by(PumpEvent.event_timestamp.desc(), PumpEvent.id.desc())
        .offset(offset)
        .limit(limit)
    )
    events = result.scalars().all()

    return BolusReviewResponse(
        boluses=[
            BolusReviewItem(
                event_timestamp=e.event_timestamp,
                units=e.units or 0.0,
                is_automated=e.is_automated,
                control_iq_reason=e.control_iq_reason,
                control_iq_mode=e.control_iq_mode,
                iob_at_event=e.iob_at_event,
                bg_at_event=e.bg_at_event,
            )
            for e in events
        ],
        total_count=total,
        period_days=days,
    )
