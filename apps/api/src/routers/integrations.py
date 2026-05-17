"""Story 3.1, 3.2, 3.3 & 3.4: Integration credentials and data sync router.

API endpoints for managing third-party integrations (Dexcom, Tandem) and data sync.
"""

import math
import uuid
import zoneinfo
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydexcom import Dexcom
from pydexcom import errors as dexcom_errors
from sqlalchemy import and_, case, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from tconnectsync.api.common import ApiException
from tconnectsync.api.tandemsource import TandemSourceApi

from src.core.auth import CurrentUser, DiabeticOrAdminUser
from src.core.encryption import encrypt_credential
from src.core.tandem_regions import (
    TandemLegacyRegionError,
    country_to_cloud,
    is_legacy_tandem_region,
)
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
from src.schemas.forecast import (
    ForecastPayload,
    ForecastReadResponse,
    ForecastSourcePreferenceResponse,
    ForecastSourcePreferenceUpdate,
    curves_from_jsonb,
)
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
    LoopStatusResponse,
    OverrideStatusResponse,
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
    TandemUploadResetResponse,
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
from src.services.forecast_reader import (
    get_available_sources,
    get_latest_forecast,
    read_forecast_preference,
    resolve_effective_source,
    set_forecast_source,
)
from src.services.iob_projection import get_iob_projection, get_user_dia
from src.services.loop_state_extractor import get_latest_loop_state
from src.services.tandem_sync import (
    TandemAuthError,
    TandemConnectionError,
    TandemNeedsCountryError,
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

# Maximum window for date-range queries (31 days)
_MAX_DATE_RANGE_DAYS = 31


def _validate_date_range(
    start: datetime | None, end: datetime | None
) -> tuple[datetime, datetime] | None:
    """Validate optional start/end date-range query parameters.

    Returns (start_utc, end_utc) if both are provided, or None if neither is.
    Raises HTTPException(422) on validation failure.
    """
    if start is None and end is None:
        return None
    if (start is None) != (end is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Both 'start' and 'end' must be provided together.",
        )
    # Reject naive datetimes -- callers must include Z or an explicit offset
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'start' and 'end' must include a timezone offset (e.g. 'Z' or '+05:00').",
        )
    start = start.astimezone(UTC)
    end = end.astimezone(UTC)
    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'end' must be strictly after 'start'.",
        )
    if (end - start) > timedelta(days=_MAX_DATE_RANGE_DAYS):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Date range must not exceed {_MAX_DATE_RANGE_DAYS} days.",
        )
    return start, end


router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def validate_dexcom_credentials(
    username: str, password: str, region: str = "US"
) -> tuple[bool, str | None]:
    """Validate Dexcom Share credentials by attempting to connect.

    Args:
        username: Dexcom Share email
        password: Dexcom Share password
        region: Dexcom Share region ("US", "OUS" or "JP"). pydexcom uses the
            lowercase form internally; passed here as the stored value.

    Returns:
        Tuple of (success, error_message)
    """
    try:
        # Try to connect to Dexcom - this validates credentials.
        # pydexcom accepts the region as a lowercase string or Region enum.
        dexcom = Dexcom(
            username=username,
            password=password,
            region=region.lower(),
        )
        # Try to get glucose readings to confirm connection works
        _ = dexcom.get_current_glucose_reading()
        return True, None
    except dexcom_errors.AccountError as e:
        logger.warning(
            "Dexcom credential validation failed - account error",
            region=region,
            error=str(e),
        )
        # Region mismatch and wrong password return the same AccountError, so
        # we surface a region hint alongside the credential hint.
        return (
            False,
            (
                "Could not log in to Dexcom. Double-check your email, password, "
                "and region selection (US / Outside US / Japan), and confirm "
                "Dexcom Share is enabled with at least one follower invited."
            ),
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
    username: str, password: str, country: str = "US"
) -> tuple[bool, str | None]:
    """Validate Tandem t:connect credentials by attempting to connect.

    Args:
        username: Tandem t:connect email
        password: Tandem t:connect password
        country: ISO-3166-1 alpha-2 country code (used to route to the
            correct Tandem cloud bucket via ``country_to_cloud``).

    Returns:
        Tuple of (success, error_message)
    """
    try:
        cloud = country_to_cloud(country)
    except ValueError as e:
        logger.warning(
            "Tandem credential validation failed - unsupported country",
            country=country,
            error=str(e),
        )
        return False, f"Country '{country}' is not supported by Tandem cloud."

    try:
        # tconnectsync's TandemSourceApi.__init__ calls login(), so simply
        # constructing it validates the credentials.
        _api = TandemSourceApi(email=username, password=password, region=cloud)
        return True, None
    except ValueError as e:
        # Shouldn't happen for a vetted country, but tconnectsync may add new
        # checks in future versions.
        logger.warning(
            "Tandem credential validation failed - invalid cloud bucket",
            country=country,
            cloud=cloud,
            error=str(e),
        )
        return False, f"Invalid region configuration for country '{country}'."
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
    # Validate credentials first (with region so we hit the right Share server)
    is_valid, error_message = validate_dexcom_credentials(
        request.username,
        request.password,
        request.region,
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
        existing.region = request.region
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
            region=request.region,
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
    # Validate credentials first (with country)
    is_valid, error_message = validate_tandem_credentials(
        request.username,
        request.password,
        request.country,
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
        # Update existing credentials. region column stores the country code
        # for Tandem (see model comment in src/models/integration.py).
        previous_country = existing.region or ""
        country_changed = previous_country != request.country
        existing.encrypted_username = encrypt_credential(request.username)
        existing.encrypted_password = encrypt_credential(request.password)
        existing.region = request.country
        existing.status = IntegrationStatus.CONNECTED
        existing.last_error = None
        existing.updated_at = datetime.now(UTC)
        credential = existing

        # If the country (and therefore the Tandem cloud bucket) changed, the
        # cached OAuth token is bound to the old cloud and will fail with an
        # opaque 401 against the new endpoints. Clear it so the next upload
        # re-authenticates fresh.
        if country_changed:
            state_result = await db.execute(
                select(TandemUploadState).where(
                    TandemUploadState.user_id == current_user.id
                )
            )
            state = state_result.scalar_one_or_none()
            if state is not None:
                state.tandem_access_token = None
                state.tandem_refresh_token = None
                state.tandem_token_expires_at = None
                state.tandem_pumper_id = None
                logger.info(
                    "Cleared cached Tandem auth on country change",
                    user_id=str(current_user.id),
                    old_country=previous_country,
                    new_country=request.country,
                )
    else:
        credential = IntegrationCredential(
            user_id=current_user.id,
            integration_type=IntegrationType.TANDEM,
            encrypted_username=encrypt_credential(request.username),
            encrypted_password=encrypt_credential(request.password),
            region=request.country,
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
    start: datetime | None = Query(
        default=None, description="Start of date range (ISO 8601, UTC)"
    ),
    end: datetime | None = Query(
        default=None, description="End of date range (ISO 8601, UTC)"
    ),
) -> GlucoseHistoryResponse:
    """Get glucose reading history.

    Returns recent glucose readings for the specified time period.
    Default is 3 hours (180 minutes), max is 30 days (43200 minutes).
    For longer periods, consider using fewer readings with client-side
    downsampling (e.g., LTTB) for chart rendering.

    When start and end are provided, they override the minutes parameter.
    """
    date_range = _validate_date_range(start, end)
    if date_range is not None:
        readings = await get_glucose_readings(
            db, current_user.id, limit=limit, start=date_range[0], end=date_range[1]
        )
    else:
        readings = await get_glucose_readings(
            db, current_user.id, minutes=minutes, limit=limit
        )

    return GlucoseHistoryResponse(
        readings=[GlucoseReadingResponse.model_validate(r) for r in readings],
        count=len(readings),
    )


@router.get(
    "/glucose/time-in-range",
    response_model=TimeInRangeResponse | TimeInRangeDetailResponse,
    responses={
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
    start: datetime | None = Query(
        default=None, description="Start of date range (ISO 8601, UTC)"
    ),
    end: datetime | None = Query(
        default=None, description="End of date range (ISO 8601, UTC)"
    ),
) -> TimeInRangeResponse | TimeInRangeDetailResponse:
    """Get time-in-range statistics for the specified period.

    Calculates the percentage of glucose readings that fall below, within,
    and above the user's configured target range.

    When include_details=true, returns 5-bucket clinical breakdown
    (urgent_low, low, in_range, high, urgent_high) with previous-period
    comparison data.

    When start and end are provided, they override the minutes parameter.
    """
    date_range = _validate_date_range(start, end)

    # Fetch user's target range thresholds
    target_range = await get_or_create_range(current_user.id, db)
    low_threshold = target_range.low_target
    high_threshold = target_range.high_target

    if not include_details:
        # Original 3-bucket response (backward compatible)
        if date_range is not None:
            cutoff = date_range[0]
            now = date_range[1]
        else:
            now = datetime.now(UTC)
            cutoff = now - timedelta(minutes=minutes)
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
                GlucoseReading.reading_timestamp < now,
                GlucoseReading.value >= 20,
                GlucoseReading.value <= 500,
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
        in_range_pct = max(0.0, round(100 - low_pct - high_pct, 1))

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
    if date_range is not None:
        cutoff = date_range[0]
        now = date_range[1]
        window_minutes = (now - cutoff).total_seconds() / 60
    else:
        now = datetime.now(UTC)
        cutoff = now - timedelta(minutes=minutes)
        window_minutes = minutes

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
    prev_start = cutoff - timedelta(minutes=window_minutes)
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
    user_id: uuid.UUID,
    start: datetime,
    end: datetime,
    urgent_low: float,
    low: float,
    high: float,
    urgent_high: float,
) -> dict:
    """Query 5-bucket TIR counts for a time window.

    Filters to physiologically plausible glucose values (20-500 mg/dL)
    to prevent sensor errors or corrupt data from skewing percentages.
    """
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
            GlucoseReading.value >= 20,
            GlucoseReading.value <= 500,
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

    except TandemNeedsCountryError as e:
        # Caught before the generic TandemSyncError handler below since
        # TandemNeedsCountryError is a TandemSyncError subclass.
        logger.warning(
            "Tandem sync blocked - legacy region requires re-select",
            user_id=str(current_user.id),
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
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

    # PR 6: closed-loop surfaces from the latest NS devicestatus snapshot.
    # Independent query path (DeviceStatusSnapshot, not PumpEvent) -- a
    # user with only direct integrations (Tandem cloud, etc.) gets the
    # pump fields populated and the loop fields all None, which is the
    # correct read.
    loop_state = await get_latest_loop_state(db, current_user.id)
    loop_status_resp: LoopStatusResponse | None = None
    if loop_state.loop_status is not None:
        loop_status_resp = LoopStatusResponse(
            state=loop_state.loop_status.state,
            source=loop_state.loop_status.source,
            issued_at=loop_state.loop_status.issued_at,
            failure_reason=loop_state.loop_status.failure_reason,
        )
    override_resp: OverrideStatusResponse | None = None
    if loop_state.override is not None:
        override_resp = OverrideStatusResponse(
            name=loop_state.override.name,
            started_at=loop_state.override.started_at,
            ends_at=loop_state.override.ends_at,
            multiplier=loop_state.override.multiplier,
            target_low_mgdl=loop_state.override.target_low_mgdl,
            target_high_mgdl=loop_state.override.target_high_mgdl,
        )

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
        loop_status=loop_status_resp,
        override=override_resp,
        cob_grams=loop_state.cob_grams,
    )


# ---------------------------------------------------------------------------
# Story 43.12 PR 3 -- forecast picker read/write endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/forecast",
    response_model=ForecastReadResponse,
    responses={
        200: {
            "description": (
                "User's forecast picker preference, the engines currently "
                "publishing forecasts, and (when an effective source resolves) "
                "the latest forecast payload from that source."
            )
        },
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
    },
)
async def get_forecast(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> ForecastReadResponse:
    """Compose the forecast-overlay read for the dashboard chart and AI context.

    Three independent state pieces fold into one response:

    - **`source_preference`** -- whatever the user picked (or `'auto'`
      default for new users).
    - **`available_sources`** -- engines that emitted any forecast in
      the last 24h. Drives PR 4's picker dropdown.
    - **`forecast`** -- the latest snapshot from the effective source,
      suppressed when older than the 30-min freshness threshold so
      the chart never draws a misaligned dotted line.

    The `effective_source` field is the resolved combination -- the
    chart should ignore `source_preference` and `available_sources`
    when deciding what (if anything) to render and just trust
    `effective_source` + `forecast`.

    Returns 200 with all-null forecast/effective_source for users
    with no closed-loop integration -- the picker UI hides itself
    in that state.
    """
    # Read-only path -- never INSERTs a settings row, returns
    # 'auto' as the synthesized default for users with no stored
    # preference. This keeps the GET side-effect-free per REST
    # convention. PUT is where the row gets persisted.
    preference = await read_forecast_preference(db, current_user.id)
    available = await get_available_sources(db, current_user.id)
    effective = resolve_effective_source(preference, available)

    forecast_payload: ForecastPayload | None = None
    if effective is not None:
        latest = await get_latest_forecast(db, current_user.id, effective)
        if latest is not None:
            forecast_payload = ForecastPayload(
                source_engine=latest.source_engine,  # type: ignore[arg-type]
                source_uploader=latest.source_uploader,
                issued_at=latest.issued_at,
                start_at=latest.start_at,
                step_minutes=latest.step_minutes,
                horizon_minutes=latest.horizon_minutes,
                curves_mgdl=curves_from_jsonb(latest.curves_mgdl_json),
                default_curve_name=latest.default_curve_name,
            )

    # Compute the explicit "why no forecast" reason for the frontend.
    # Mutually exclusive states; happy path returns None.
    reason: str | None = None
    if forecast_payload is None:
        if preference == "none":
            reason = "opted_out"
        elif not available:
            reason = "no_sources"
        elif preference == "auto" and len(available) > 1:
            reason = "needs_pick"
        elif effective is None:
            # preference is a specific engine but it's not in `available`.
            reason = "source_silent"
        else:
            # effective resolved but the latest snapshot is too old.
            reason = "stale"

    return ForecastReadResponse(
        source_preference=preference,
        effective_source=effective,
        available_sources=available,
        forecast=forecast_payload,
        forecast_unavailable_reason=reason,  # type: ignore[arg-type]
    )


@router.put(
    "/forecast/source",
    response_model=ForecastSourcePreferenceResponse,
    responses={
        200: {"description": "Forecast source preference updated."},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        422: {
            "model": ErrorResponse,
            "description": "Invalid `source` value (must be one of the allowed enum).",
        },
    },
)
async def update_forecast_source(
    body: ForecastSourcePreferenceUpdate,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> ForecastSourcePreferenceResponse:
    """Persist the user's forecast picker choice.

    Pydantic's `Literal` validation rejects unknown source values at
    the API boundary (422 before the DB ever sees them). The DB's
    CHECK constraint is the final guard if the schema ever drifts.
    """
    settings = await set_forecast_source(db, current_user.id, body.source)
    await db.commit()
    return ForecastSourcePreferenceResponse(
        source_preference=settings.source,  # type: ignore[arg-type]
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
                "pump_activity_mode": item.pump_activity_mode,
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
            # The (user_id, event_timestamp, event_type) unique index
            # is partial -- it applies only to direct-integration rows
            # (`ns_id IS NULL`). Including the WHERE clause here is
            # required for PostgreSQL to recognize the partial index
            # as the ON CONFLICT target.
            index_where=text("ns_id IS NULL"),
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

    # Resolve stored country and legacy flag from the Tandem credential.
    cred_result = await db.execute(
        select(IntegrationCredential).where(
            IntegrationCredential.user_id == current_user.id,
            IntegrationCredential.integration_type == IntegrationType.TANDEM,
        )
    )
    credential = cred_result.scalar_one_or_none()
    stored = credential.region if credential else None
    needs_country = bool(stored) and is_legacy_tandem_region(stored)

    if not state:
        return TandemUploadStatusResponse(
            enabled=False,
            upload_interval_minutes=15,
            pending_raw_events=pending_count,
            country=stored if not needs_country else None,
            needs_country_reselect=needs_country,
        )

    return TandemUploadStatusResponse(
        enabled=state.enabled,
        upload_interval_minutes=state.upload_interval_minutes,
        last_upload_at=state.last_upload_at,
        last_upload_status=state.last_upload_status,
        last_error=state.last_error,
        max_event_index_uploaded=state.max_event_index_uploaded,
        pending_raw_events=pending_count,
        country=stored if not needs_country else None,
        needs_country_reselect=needs_country,
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
    """Enable/disable Tandem cloud upload and set interval.

    Refuses to enable when the user's stored Tandem region is legacy
    (e.g. ``"EU"``) — they must re-select their country first via the
    ``POST /api/integrations/tandem`` connect endpoint.
    """
    cred_result = await db.execute(
        select(IntegrationCredential).where(
            IntegrationCredential.user_id == current_user.id,
            IntegrationCredential.integration_type == IntegrationType.TANDEM,
        )
    )
    credential = cred_result.scalar_one_or_none()
    stored = credential.region if credential else None
    needs_country = bool(stored) and is_legacy_tandem_region(stored)

    # Allow disable always (users should be able to turn the feature off even
    # if they're stuck on a legacy region or have no credential at all). Only
    # enable requires a healthy credential + non-legacy region.
    if request.enabled:
        if credential is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "Tandem integration not configured. Please connect your "
                    "Tandem account before enabling cloud upload."
                ),
            )
        if needs_country:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Your Tandem integration uses a legacy region value and "
                    "must be re-connected with your country selected before "
                    "uploads can be enabled."
                ),
            )

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
        country=stored if not needs_country else None,
        needs_country_reselect=needs_country,
    )


@router.post(
    "/tandem/cloud-upload/trigger",
    response_model=TandemUploadTriggerResponse,
    responses={
        200: {"description": "Upload triggered"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Tandem not configured"},
        409: {"model": ErrorResponse, "description": "Integration disconnected"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        500: {"model": ErrorResponse, "description": "Upload failed"},
    },
)
@limiter.limit("5/minute")
async def trigger_tandem_upload(
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> TandemUploadTriggerResponse:
    """Manually trigger a Tandem cloud upload.

    Uploads pending raw events to the Tandem cloud immediately. Rate-limited
    to 5/minute per IP -- the scheduler handles steady-state uploads on its
    own interval; this endpoint is a manual override.
    """
    # Verify Tandem credentials exist and are not disconnected.
    cred_result = await db.execute(
        select(IntegrationCredential).where(
            IntegrationCredential.user_id == current_user.id,
            IntegrationCredential.integration_type == IntegrationType.TANDEM,
        )
    )
    credential = cred_result.scalar_one_or_none()
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tandem integration not configured. Please connect your Tandem account first.",
        )
    if credential.status == IntegrationStatus.DISCONNECTED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tandem integration is disconnected. Reconnect Tandem first.",
        )

    # Import here to avoid circular imports
    from src.services.tandem_upload import upload_to_tandem

    try:
        result = await upload_to_tandem(db, current_user.id)
    except TandemLegacyRegionError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
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

    return TandemUploadTriggerResponse(
        message=result.get("message", "Upload complete"),
        events_uploaded=result.get("events_uploaded", 0),
        status=result.get("status", "success"),
    )


@router.post(
    "/tandem/cloud-upload/reset",
    response_model=TandemUploadResetResponse,
    responses={
        200: {"description": "Upload state reset"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Tandem not configured"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    },
)
@limiter.limit("5/minute")
async def reset_tandem_upload(
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> TandemUploadResetResponse:
    """Reset the Tandem upload high-water mark and re-queue all stored events.

    Recovery action for cases where the local state has drifted out of sync
    with reality -- e.g. after a pump re-pair, sequence-counter reset, or
    when migrating off the legacy incremental-sync logic that silently
    filtered queued events.

    Rate-limited to 5/minute per IP: the reset is a heavy ``UPDATE`` over
    every ``pump_raw_events`` row for the user and takes a row-lock on the
    upload state -- a tight loop could saturate the connection pool for
    legitimate uploads. Idempotent: safe to call repeatedly within the
    limit.
    """
    cred_result = await db.execute(
        select(IntegrationCredential).where(
            IntegrationCredential.user_id == current_user.id,
            IntegrationCredential.integration_type == IntegrationType.TANDEM,
        )
    )
    credential = cred_result.scalar_one_or_none()
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tandem integration not configured.",
        )
    # Respect the user's "off" decision: a disconnected integration should
    # not be re-armed by the reset path. The user must reconnect first.
    if credential.status == IntegrationStatus.DISCONNECTED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Tandem integration is disconnected. Reconnect Tandem "
                "before resetting the upload state."
            ),
        )

    from src.services.tandem_upload import reset_tandem_upload_state

    result = await reset_tandem_upload_state(db, current_user.id)
    return TandemUploadResetResponse(
        message=result.get("message", "Reset complete"),
        events_requeued=result.get("events_requeued", 0),
    )


# --- Story 30.1: Aggregate statistics endpoints ---

# Maximum rows to load into memory for percentile calculation
_AGP_MAX_ROWS = 50_000
# Hard safety cap for insulin units (Tandem X2/Mobi max single bolus = 25U)
_MAX_BOLUS_UNITS = 25
# Maximum basal rate (Tandem X2/Mobi max = 15 U/hr)
_MAX_BASAL_RATE = 15.0
# Maximum gap between basal records before capping (handles disconnections).
# 2 hours covers typical gaps: site changes (~30 min), sensor restarts (~2 hr
# for Dexcom G6/G7), showers (~15 min). Longer gaps indicate true disconnection
# and should not accumulate phantom insulin.
_BASAL_MAX_GAP_HOURS = 2.0


def _boundary_aligned_cutoff(
    days: int,
    boundary_hour: int,
    tz_name: str = "UTC",
    now: datetime | None = None,
) -> datetime:
    """Compute the start of an analytics period aligned to the day boundary.

    For days=1 (24H): returns today's boundary hour (or yesterday's if
    we haven't passed it yet).  For days=3: returns the boundary 3-1=2
    days before the effective boundary.  This matches the pump's Delivery
    Summary which resets at midnight (boundary=0).

    The ``days`` parameter follows the same semantics as the web API
    ``days`` query parameter: days=1 means "current day period" (like 24H),
    days=7 means "7-day period", etc.

    ``tz_name`` is an IANA timezone string (e.g. "America/Chicago") so
    the boundary is computed in the user's local time.  Defaults to UTC
    for backward compatibility.
    """
    if not 0 <= boundary_hour <= 23:
        boundary_hour = 0
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except (KeyError, ValueError) as e:
        raise ValueError(f"Invalid timezone: {tz_name}") from e
    local_now = (now or datetime.now(UTC)).astimezone(tz)
    today_boundary = local_now.replace(
        hour=boundary_hour, minute=0, second=0, microsecond=0
    )
    if local_now < today_boundary:
        effective_boundary = today_boundary - timedelta(days=1)
    else:
        effective_boundary = today_boundary
    # days=1 means "since the current boundary" (daysBack=0 on mobile).
    # days=7 means "since 6 days before the effective boundary".
    # Convert back to UTC for DB queries.
    return (effective_boundary - timedelta(days=max(days - 1, 0))).astimezone(UTC)


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
    start: datetime | None = Query(
        default=None, description="Start of date range (ISO 8601, UTC)"
    ),
    end: datetime | None = Query(
        default=None, description="End of date range (ISO 8601, UTC)"
    ),
) -> GlucoseStatsResponse:
    """Get aggregate glucose statistics: mean, SD, CV%, GMI, CGM active%.

    GMI (Glucose Management Indicator) estimates A1C from mean glucose
    using the formula: GMI = 3.31 + (0.02392 * mean_glucose_mg_dl).

    CGM active % assumes 5-minute reading intervals (standard for Dexcom G6/G7).

    When start and end are provided, they override the minutes parameter.
    """
    date_range = _validate_date_range(start, end)
    if date_range is not None:
        cutoff = date_range[0]
        upper = date_range[1]
        period_minutes = (upper - cutoff).total_seconds() / 60
    else:
        cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
        upper = None
        period_minutes = minutes

    conditions = [
        GlucoseReading.user_id == current_user.id,
        GlucoseReading.reading_timestamp >= cutoff,
        GlucoseReading.value >= 20,
        GlucoseReading.value <= 500,
    ]
    if upper is not None:
        conditions.append(GlucoseReading.reading_timestamp < upper)

    result = await db.execute(
        select(
            func.count().label("total"),
            func.avg(GlucoseReading.value).label("mean"),
            func.stddev_pop(GlucoseReading.value).label("stddev"),
        ).where(*conditions)
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
            period_minutes=int(period_minutes),
        )

    cv = round((sd / mean) * 100, 1) if mean > 0 else 0.0
    # GMI formula: Bergenstal et al. 2018
    gmi = round(3.31 + (0.02392 * mean), 1)
    # CGM active %: readings / expected readings (1 per 5 min, Dexcom standard)
    expected_readings = period_minutes / 5
    cgm_active = round(min((count / expected_readings) * 100, 100.0), 1)

    return GlucoseStatsResponse(
        mean_glucose=round(mean, 1),
        std_dev=round(sd, 1),
        cv_pct=cv,
        gmi=gmi,
        cgm_active_pct=cgm_active,
        readings_count=count,
        period_minutes=int(period_minutes),
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
    tz: str = Query(
        default="UTC",
        max_length=50,
        description="IANA timezone for day boundary (e.g. America/Chicago)",
    ),
    start: datetime | None = Query(
        default=None, description="Start of date range (ISO 8601, UTC)"
    ),
    end: datetime | None = Query(
        default=None, description="End of date range (ISO 8601, UTC)"
    ),
) -> InsulinSummaryResponse:
    """Get insulin delivery summary: TDD, basal/bolus split, bolus count.

    All unit values (tdd, basal_units, bolus_units, correction_units) are
    daily averages over the requested period. Counts (bolus_count,
    correction_count) are totals for the full period.

    When start and end are provided, they override the days/tz parameters
    and skip boundary alignment.
    """
    date_range = _validate_date_range(start, end)
    if date_range is not None:
        cutoff = date_range[0]
        now = date_range[1]
        # Compute fractional days for averaging
        period_days = max(1, (now - cutoff).total_seconds() / 86400)
    else:
        from src.services.analytics_config import get_boundary_hour

        now = datetime.now(UTC)
        boundary_hour = await get_boundary_hour(current_user.id, db)
        try:
            cutoff = _boundary_aligned_cutoff(days, boundary_hour, tz, now)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        period_days = days

    # Bolus/correction: dedup CTE collapses dual-creation records
    # (same delivery stored as both 'bolus' and 'correction' at the same
    # timestamp+units). `GROUP BY (event_timestamp, units)` is the dedupe
    # key; `bool_or(... = correction)` picks the more specific label
    # when both exist for the same delivery. The grouping naturally
    # handles cross-source duplicates too (e.g. one row from mobile BLE
    # + one from Tandem cloud + one from Nightscout — same ts and units
    # → merged into one delivery). No source filter, by design: this
    # widget renders any bolus the canonical table holds, regardless of
    # which integration wrote it. See issue #574 / source-agnostic-
    # widgets discussion.
    _bolus_table = PumpEvent.__tablename__
    _bolus_val = PumpEventType.BOLUS.value
    _correction_val = PumpEventType.CORRECTION.value
    bolus_query = text(  # nosemgrep: avoid-sqlalchemy-text
        f"""
        WITH deliveries AS (
            SELECT event_timestamp, units,
                   bool_or(event_type = :correction_type) AS is_correction
            FROM {_bolus_table}
            WHERE user_id = :user_id
              AND event_timestamp >= :cutoff AND event_timestamp <= :now
              AND event_type IN (:bolus_type, :correction_type)
              AND units IS NOT NULL AND units >= 0 AND units <= :max_bolus
            GROUP BY event_timestamp, units
        )
        SELECT is_correction,
               COALESCE(SUM(units), 0) AS total_units,
               COUNT(*) AS delivery_count
        FROM deliveries
        GROUP BY is_correction
    """
    )
    bolus_result = await db.execute(
        bolus_query,
        {
            "user_id": str(current_user.id),
            "cutoff": cutoff,
            "now": now,
            "bolus_type": _bolus_val,
            "correction_type": _correction_val,
            "max_bolus": float(_MAX_BOLUS_UNITS),
        },
    )
    bolus_rows = bolus_result.all()

    # Basal: time-weighted rate integration using SQL LEAD() window
    # function. Each basal record stores units = rate in U/hr (not
    # delivered amount). Actual delivery = rate * time_until_next_record,
    # capped at _BASAL_MAX_GAP_HOURS to handle pump disconnections/gaps.
    # Uses PostgreSQL EXTRACT(EPOCH) and LEAST() -- not portable to
    # SQLite.
    #
    # No source filter: any integration that writes basal-rate-change
    # events to the canonical table contributes. Cross-source overlap
    # (rare in practice -- a user with both Tandem cloud and Loop-via-
    # NS reporting the same pump) produces same-timestamp rows that the
    # LEAD ordering folds into zero-duration intervals, so the
    # integrated total is approximately correct without explicit
    # row-level dedupe. A precise dedupe scheme would land at write
    # time, not in this read query.
    _table = PumpEvent.__tablename__
    _basal_val = PumpEventType.BASAL.value
    basal_query = text(  # nosemgrep: avoid-sqlalchemy-text
        f"""
        WITH prior AS (
            SELECT event_timestamp, units
            FROM {_table}
            WHERE user_id = :user_id
              AND event_type = :event_type
              AND units IS NOT NULL
              AND units >= 0
              AND units <= :max_rate
              AND event_timestamp < :cutoff
            ORDER BY event_timestamp DESC
            LIMIT 1
        ),
        in_window AS (
            SELECT event_timestamp, units
            FROM {_table}
            WHERE user_id = :user_id
              AND event_type = :event_type
              AND units IS NOT NULL
              AND units >= 0
              AND units <= :max_rate
              AND event_timestamp >= :cutoff
              AND event_timestamp <= :now
        ),
        basal_rows AS (
            SELECT * FROM prior
            UNION ALL
            SELECT * FROM in_window
        ),
        basal_ordered AS (
            SELECT
                event_timestamp,
                units,
                LEAD(event_timestamp) OVER (ORDER BY event_timestamp) AS next_ts
            FROM basal_rows
        )
        SELECT COALESCE(SUM(
            units * LEAST(
                EXTRACT(EPOCH FROM (
                    LEAST(COALESCE(next_ts, :now), :now)
                    - GREATEST(event_timestamp, :cutoff)
                )) / 3600.0,
                :max_gap
            )
        ), 0) AS total_basal
        FROM basal_ordered
        WHERE LEAST(COALESCE(next_ts, :now), :now)
            > GREATEST(event_timestamp, :cutoff)
    """
    )
    basal_result = await db.execute(
        basal_query,
        {
            "user_id": str(current_user.id),
            "cutoff": cutoff,
            "now": now,
            "event_type": _basal_val,
            "max_rate": float(_MAX_BASAL_RATE),
            "max_gap": float(_BASAL_MAX_GAP_HOURS),
        },
    )
    basal_units = float(basal_result.scalar() or 0.0)

    bolus_units = 0.0
    correction_units = 0.0
    bolus_count = 0
    correction_count = 0

    for row in bolus_rows:
        units = float(row.total_units)
        if row.is_correction is True:
            correction_units += units
            correction_count += int(row.delivery_count)
        else:
            bolus_units += units
            bolus_count += int(row.delivery_count)

    tdd_total = basal_units + bolus_units + correction_units
    # Compute percentages from raw totals before rounding to avoid
    # compounding rounding error.
    if tdd_total > 0:
        basal_pct = round((basal_units / tdd_total) * 100, 1)
        bolus_pct = round(100 - basal_pct, 1)
    else:
        basal_pct = 0.0
        bolus_pct = 0.0

    # The per-day averages divide totals by `period_days` (default 14).
    # If the user has less than `period_days` of pump data (just-
    # connected NS user, fresh signup with no historical sync, anyone
    # whose retention window starts mid-period), dividing by the full
    # 14 dilutes the average across days that have no data and the
    # widget reads near zero. Find the actual data span and use the
    # smaller of (requested period, data span) as the effective
    # divisor. Clamp to 1 hour minimum so a near-empty dataset doesn't
    # produce absurd averages.
    # The denominator must apply the same safety filters as the
    # numerator -- a bogus out-of-range row (units > _MAX_BOLUS_UNITS,
    # negative, NULL) is excluded from totals but would inflate the
    # divisor here, understating per-day averages. Match the
    # bolus/correction and basal range filters used above.
    earliest_event_query = text(  # nosemgrep: avoid-sqlalchemy-text
        f"""
        SELECT MIN(event_timestamp) AS earliest
        FROM {_table}
        WHERE user_id = :user_id
          AND event_timestamp >= :cutoff
          AND event_timestamp <= :now
          AND units IS NOT NULL
          AND units >= 0
          AND (
            (event_type IN (:bolus_type, :correction_type)
             AND units <= :max_bolus)
            OR
            (event_type = :basal_type
             AND units <= :max_rate)
          )
        """
    )
    earliest_result = await db.execute(
        earliest_event_query,
        {
            "user_id": str(current_user.id),
            "cutoff": cutoff,
            "now": now,
            "bolus_type": _bolus_val,
            "correction_type": _correction_val,
            "basal_type": _basal_val,
            "max_bolus": float(_MAX_BOLUS_UNITS),
            "max_rate": float(_MAX_BASAL_RATE),
        },
    )
    earliest_row = earliest_result.first()
    if earliest_row and earliest_row.earliest:
        actual_span_days = (now - earliest_row.earliest).total_seconds() / 86400
        effective_period_days = max(1.0 / 24, min(period_days, actual_span_days))
    else:
        effective_period_days = period_days

    # Average per day (round only at the final output step)
    d = max(effective_period_days, 1.0 / 24)
    tdd = round(tdd_total / d, 1)
    basal_avg = round(basal_units / d, 1)
    bolus_avg = round((bolus_units + correction_units) / d, 1)
    correction_avg = round(correction_units / d, 1)

    return InsulinSummaryResponse(
        tdd=tdd,
        basal_units=basal_avg,
        bolus_units=bolus_avg,
        correction_units=correction_avg,
        basal_pct=basal_pct,
        bolus_pct=bolus_pct,
        bolus_count=bolus_count,
        correction_count=correction_count,
        period_days=max(1, round(effective_period_days)),
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
    tz: str = Query(
        default="UTC",
        max_length=50,
        description="IANA timezone for day boundary (e.g. America/Chicago)",
    ),
    start: datetime | None = Query(
        default=None, description="Start of date range (ISO 8601, UTC)"
    ),
    end: datetime | None = Query(
        default=None, description="End of date range (ISO 8601, UTC)"
    ),
) -> BolusReviewResponse:
    """Get paginated list of bolus events for review.

    When start and end are provided, they override the days/tz parameters
    and skip boundary alignment.
    """
    date_range = _validate_date_range(start, end)
    if date_range is not None:
        cutoff = date_range[0]
        now = date_range[1]
        period_days = max(1, (now - cutoff).total_seconds() / 86400)
    else:
        from src.services.analytics_config import get_boundary_hour

        now = datetime.now(UTC)
        boundary_hour = await get_boundary_hour(current_user.id, db)
        try:
            cutoff = _boundary_aligned_cutoff(days, boundary_hour, tz, now)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        period_days = days

    # No source filter: render any bolus / correction in the time
    # window regardless of which integration wrote it (Tandem direct,
    # mobile BLE, Nightscout-relayed Loop / AAPS / OmniPod, future
    # Tidepool, etc.). Cross-source duplicate suppression at the row
    # level is its own piece of work (write-time content-hash dedupe);
    # for the table view, displaying both rows with their distinct
    # source labels is an acceptable interim. See issue #574.
    bolus_filter = [
        PumpEvent.user_id == current_user.id,
        PumpEvent.event_timestamp >= cutoff,
        PumpEvent.event_timestamp <= now,
        PumpEvent.units.is_not(None),
        PumpEvent.units >= 0,
        PumpEvent.units <= _MAX_BOLUS_UNITS,
        PumpEvent.event_type.in_(
            [
                PumpEventType.BOLUS,
                PumpEventType.CORRECTION,
            ]
        ),
    ]

    # Count total
    count_result = await db.execute(select(func.count()).where(*bolus_filter))
    total = count_result.scalar() or 0

    # Fetch page
    result = await db.execute(
        select(PumpEvent)
        .where(*bolus_filter)
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
                pump_activity_mode=e.pump_activity_mode,
                iob_at_event=e.iob_at_event,
                bg_at_event=e.bg_at_event,
            )
            for e in events
        ],
        total_count=total,
        period_days=max(1, round(period_days)),
    )
