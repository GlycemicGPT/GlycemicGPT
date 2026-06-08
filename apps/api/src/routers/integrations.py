"""Story 3.1, 3.2, 3.3 & 3.4: Integration credentials and data sync router.

API endpoints for managing third-party integrations (Dexcom, Tandem) and data sync.
"""

import json
import math
import secrets
import time
import uuid
import zoneinfo
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import FileResponse, PlainTextResponse
from pydexcom import Dexcom
from pydexcom import errors as dexcom_errors
from sqlalchemy import and_, case, delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from tconnectsync.api.common import ApiException
from tconnectsync.api.tandemsource import TandemSourceApi

from src.config import settings
from src.core.auth import (
    CurrentUser,
    DiabeticOrAdminUser,
    get_current_user,
    require_diabetic_or_admin,
)
from src.core.connect_install_bundle import (
    get_install_bundle,
    store_install_bundle,
)
from src.core.encryption import decrypt_credential, encrypt_credential
from src.core.medtronic_regions import resolve_region_base_url
from src.core.tandem_regions import (
    country_to_cloud,
    is_legacy_tandem_region,
)
from src.core.token_blacklist import consume_token_once, is_token_blacklisted
from src.database import get_db
from src.logging_config import get_logger
from src.middleware.rate_limit import limiter
from src.models.glooko_sync_state import (
    STATUS_CONNECTED as GLOOKO_STATUS_CONNECTED,
)
from src.models.glooko_sync_state import (
    STATUS_DISCONNECTED as GLOOKO_STATUS_DISCONNECTED,
)
from src.models.glooko_sync_state import (
    GlookoSyncState,
)
from src.models.glucose import GlucoseReading
from src.models.integration import (
    IntegrationCredential,
    IntegrationStatus,
    IntegrationType,
)
from src.models.medtronic_connect_state import (
    STATUS_CONNECTED,
    STATUS_DISCONNECTED,
    MedtronicConnectState,
)
from src.models.pump_data import PumpEvent, PumpEventType
from src.models.tandem_sync_state import (
    SYNC_INTERVAL_DEFAULT_MINUTES,
    TandemSyncState,
)
from src.models.user import User
from src.schemas.auth import ErrorResponse
from src.schemas.cgm import (
    CgmPrimaryResponse,
    CgmPrimaryUpdate,
    CgmSourceItem,
    CgmSourcesResponse,
)
from src.schemas.forecast import (
    ForecastPayload,
    ForecastReadResponse,
    ForecastSourcePreferenceResponse,
    ForecastSourcePreferenceUpdate,
    curves_from_jsonb,
)
from src.schemas.glooko import (
    GlookoAvailabilityResponse,
    GlookoConnectRequest,
    GlookoStatusResponse,
    GlookoSyncResponse,
    GlookoSyncSettingsRequest,
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
from src.schemas.medtronic import (
    CARELINK_TOKEN_HEADER,
    MAX_TOKEN_LEN,
    MedtronicAvailabilityRequest,
    MedtronicAvailabilityResponse,
    MedtronicConnectAuthUrlResponse,
    MedtronicConnectExchangeRequest,
    MedtronicConnectInstallRequest,
    MedtronicConnectInstallResponse,
    MedtronicConnectPairResponse,
    MedtronicConnectSettingsRequest,
    MedtronicConnectStatusResponse,
    MedtronicConnectSyncResponse,
    MedtronicImportRequest,
    MedtronicImportResponse,
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
    TandemAvailabilityResponse,
    TandemImportRequest,
    TandemSyncResponse,
    TandemSyncSettingsRequest,
    TandemSyncStatusResponse,
)
from src.services.cgm_source import (
    CGM_ROLE_PRIMARY,
    default_cgm_role_for_new_source,
    get_excluded_cgm_sources,
    list_cgm_sources,
    set_primary_cgm_source,
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
from src.services.integrations.glooko.auth import glooko_login
from src.services.integrations.glooko.errors import (
    GlookoAuthError,
    GlookoNetworkError,
)
from src.services.integrations.glooko.sync import (
    GlookoSyncRunError,
    import_glooko_history_for_user,
    probe_glooko_availability,
    sync_glooko_for_user,
)
from src.services.integrations.medtronic.client import (
    CareLinkAuthError,
    CareLinkClient,
    CareLinkError,
    CareLinkReportTimeoutError,
)
from src.services.integrations.medtronic.connect_auth import (
    ConnectTokenError,
    build_authorize_url,
    exchange_code_for_tokens,
    generate_pkce,
    get_region,
)
from src.services.integrations.medtronic.connect_pairing import (
    CONNECT_PAIR_TOKEN_HEADER,
    PAIR_TOKEN_TTL_SECONDS,
    PairingTokenError,
    decode_pairing_token,
    issue_pairing_token,
    pairing_token_jti,
)
from src.services.integrations.medtronic.connect_sync import (
    ConnectSyncError,
    sync_connect_for_user,
)
from src.services.integrations.medtronic.sync import sync_carelink_for_user
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
    get_tandem_availability,
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
        # Create new credential. Cross-source CGM role (Story 43.10): primary
        # if the user has no existing primary CGM source, else secondary.
        cgm_role = await default_cgm_role_for_new_source(db, current_user.id)
        credential = IntegrationCredential(
            user_id=current_user.id,
            integration_type=IntegrationType.DEXCOM,
            encrypted_username=encrypt_credential(request.username),
            encrypted_password=encrypt_credential(request.password),
            region=request.region,
            status=IntegrationStatus.CONNECTED,
            cgm_role=cgm_role,
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
        existing.encrypted_username = encrypt_credential(request.username)
        existing.encrypted_password = encrypt_credential(request.password)
        existing.region = request.country
        existing.status = IntegrationStatus.CONNECTED
        existing.last_error = None
        existing.updated_at = datetime.now(UTC)
        credential = existing
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

    # (TandemUploadState cache-clear on reconnect was removed alongside the
    # Tandem cloud-upload feature in PR1c. The download direction uses
    # tconnectsync's own session, which authenticates fresh each sync.)

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
    include_secondary: bool = Query(
        default=False,
        description="Include secondary CGM sources (Story 43.10). Off by default.",
    ),
) -> CurrentGlucoseResponse:
    """Get the current (most recent) glucose reading.

    Returns the latest glucose value with trend and staleness indicator.
    By default reads from the primary CGM source only (Story 43.10).
    """
    excluded = await get_excluded_cgm_sources(
        db, current_user.id, include_secondary=include_secondary
    )
    latest = await get_latest_glucose_reading(
        db, current_user.id, excluded_sources=excluded
    )

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
    include_secondary: bool = Query(
        default=False,
        description="Include secondary CGM sources (Story 43.10). Off by default.",
    ),
) -> GlucoseHistoryResponse:
    """Get glucose reading history.

    Returns recent glucose readings for the specified time period.
    Default is 3 hours (180 minutes), max is 30 days (43200 minutes).
    For longer periods, consider using fewer readings with client-side
    downsampling (e.g., LTTB) for chart rendering.

    When start and end are provided, they override the minutes parameter.
    By default reads from the primary CGM source only (Story 43.10).
    """
    excluded = await get_excluded_cgm_sources(
        db, current_user.id, include_secondary=include_secondary
    )
    date_range = _validate_date_range(start, end)
    if date_range is not None:
        readings = await get_glucose_readings(
            db,
            current_user.id,
            limit=limit,
            start=date_range[0],
            end=date_range[1],
            excluded_sources=excluded,
        )
    else:
        readings = await get_glucose_readings(
            db,
            current_user.id,
            minutes=minutes,
            limit=limit,
            excluded_sources=excluded,
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
    include_secondary: bool = Query(
        default=False,
        description="Include secondary CGM sources (Story 43.10). Off by default.",
    ),
) -> TimeInRangeResponse | TimeInRangeDetailResponse:
    """Get time-in-range statistics for the specified period.

    Calculates the percentage of glucose readings that fall below, within,
    and above the user's configured target range.

    When include_details=true, returns 5-bucket clinical breakdown
    (urgent_low, low, in_range, high, urgent_high) with previous-period
    comparison data.

    When start and end are provided, they override the minutes parameter.
    By default counts the primary CGM source only (Story 43.10).
    """
    date_range = _validate_date_range(start, end)
    excluded = await get_excluded_cgm_sources(
        db, current_user.id, include_secondary=include_secondary
    )

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
                *(
                    [GlucoseReading.source.notin_(excluded)] if excluded else []
                ),
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
        excluded_sources=excluded,
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
        excluded_sources=excluded,
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
    *,
    excluded_sources: list[str] | None = None,
) -> dict:
    """Query 5-bucket TIR counts for a time window.

    Filters to physiologically plausible glucose values (20-500 mg/dL)
    to prevent sensor errors or corrupt data from skewing percentages.
    ``excluded_sources`` drops secondary/off CGM sources (Story 43.10).
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
            *([GlucoseReading.source.notin_(excluded_sources)] if excluded_sources else []),
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
        409: {
            "model": ErrorResponse,
            "description": "Country re-selection required (legacy region value)",
        },
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

    Returns integration status + freshness (from the credential) and the
    per-user sync control (enabled / interval / cumulative pulls, from
    ``TandemSyncState``). When no state row exists, a connected user
    defaults to enabled at the default interval -- backward-compatible with
    the prior global sync that synced every connected user.
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

    # Per-user sync control. Absent row => effective enabled@default.
    state_result = await db.execute(
        select(TandemSyncState).where(TandemSyncState.user_id == current_user.id)
    )
    state = state_result.scalar_one_or_none()

    # Legacy-region detection: a stored "EU"-style bucket can't be resolved
    # to a country, so sync would 409. Surface it so the UI can prompt a
    # reconnect instead of silently showing "enabled" that never runs.
    needs_country = bool(
        credential and credential.region and is_legacy_tandem_region(credential.region)
    )

    # A user with no Tandem credential has nothing to sync -- report
    # enabled=False so the response isn't misleading (the "no row =>
    # enabled@default" rule only applies to *connected* users).
    if credential is None:
        effective_enabled = False
    elif state is not None:
        effective_enabled = state.enabled
    else:
        effective_enabled = True

    return TandemSyncStatusResponse(
        integration_status=credential.status.value if credential else "not_configured",
        last_sync_at=credential.last_sync_at if credential else None,
        last_error=credential.last_error if credential else None,
        events_available=events_count,
        latest_event=latest_response,
        enabled=effective_enabled,
        sync_interval_minutes=(
            state.sync_interval_minutes if state else SYNC_INTERVAL_DEFAULT_MINUTES
        ),
        events_pulled_total=state.events_pulled_total if state else 0,
        needs_country_reselect=needs_country,
    )


@router.put(
    "/tandem/sync/settings",
    response_model=TandemSyncStatusResponse,
    responses={
        200: {"description": "Settings updated"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        404: {"model": ErrorResponse, "description": "Tandem not configured"},
        409: {
            "model": ErrorResponse,
            "description": "Country re-selection required (legacy region value)",
        },
    },
)
async def update_tandem_sync_settings(
    body: TandemSyncSettingsRequest,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> TandemSyncStatusResponse:
    """Update the per-user Tandem sync toggle + interval.

    Upserts the user's ``TandemSyncState`` row. Guards:
    - 404 if Tandem isn't connected (nothing to sync).
    - 409 only when *enabling* sync on a legacy-region credential (it would
      just 409 on every tick). Disabling is always allowed -- a legacy-region
      user must be able to turn sync off without first reconnecting.
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
            detail="Tandem integration not configured",
        )
    if (
        body.enabled
        and credential.region
        and is_legacy_tandem_region(credential.region)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Your Tandem integration uses a legacy region setting. "
                "Reconnect with your country selected before enabling sync."
            ),
        )

    # Upsert-then-lock: insert the row if missing (ON CONFLICT DO NOTHING),
    # then SELECT ... FOR UPDATE so a concurrent settings change or the
    # scheduler's events_pulled_total bump can't race the field writes.
    await db.execute(
        pg_insert(TandemSyncState)
        .values(
            user_id=current_user.id,
            enabled=body.enabled,
            sync_interval_minutes=body.sync_interval_minutes,
        )
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    state_result = await db.execute(
        select(TandemSyncState)
        .where(TandemSyncState.user_id == current_user.id)
        .with_for_update()
    )
    state = state_result.scalar_one()
    state.enabled = body.enabled
    state.sync_interval_minutes = body.sync_interval_minutes
    await db.commit()

    logger.info(
        "Tandem sync settings updated",
        user_id=str(current_user.id),
        enabled=body.enabled,
        interval_minutes=body.sync_interval_minutes,
    )

    # Re-read freshness for the response.
    count_result = await db.execute(
        select(func.count(PumpEvent.id)).where(PumpEvent.user_id == current_user.id)
    )
    events_count = count_result.scalar() or 0
    latest = await get_latest_pump_event(db, current_user.id)
    latest_response = PumpEventResponse.model_validate(latest) if latest else None

    # A legacy-region user can reach here by *disabling* (the enable path
    # 409s above), so compute the flag rather than hardcoding False.
    needs_country = bool(
        credential.region and is_legacy_tandem_region(credential.region)
    )

    return TandemSyncStatusResponse(
        integration_status=credential.status.value,
        last_sync_at=credential.last_sync_at,
        last_error=credential.last_error,
        events_available=events_count,
        latest_event=latest_response,
        enabled=state.enabled,
        sync_interval_minutes=state.sync_interval_minutes,
        events_pulled_total=state.events_pulled_total,
        needs_country_reselect=needs_country,
    )


@router.get(
    "/tandem/sync/availability",
    response_model=TandemAvailabilityResponse,
    responses={
        200: {"description": "Available data date range"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        404: {"model": ErrorResponse, "description": "Tandem not configured"},
        409: {"model": ErrorResponse, "description": "Country re-selection required"},
        503: {"model": ErrorResponse, "description": "Tandem service unavailable"},
    },
)
@limiter.limit("10/minute")
async def get_tandem_sync_availability(
    request: Request,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> TandemAvailabilityResponse:
    """Report the date range of pump data available in the user's t:connect
    cloud, to bound the manual-import date picker.

    Authenticates to Tandem (live call), so it's rate-limited and maps the
    same Tandem*Error types to HTTP statuses as the sync endpoint.
    """
    try:
        result = await get_tandem_availability(db, current_user.id)
    except TandemNotConfiguredError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tandem integration not configured",
        ) from e
    except TandemNeedsCountryError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except TandemAuthError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Tandem credentials. Please reconnect your account.",
        ) from e
    except TandemConnectionError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to reach Tandem. Please try again later.",
        ) from e
    except TandemSyncError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not read availability: {str(e)}",
        ) from e

    return TandemAvailabilityResponse(
        earliest=result["earliest"],
        latest=result["latest"],
        pump_count=result["pump_count"],
    )


@router.post(
    "/tandem/sync/import",
    response_model=TandemSyncResponse,
    responses={
        200: {"description": "Import completed"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        404: {"model": ErrorResponse, "description": "Tandem not configured"},
        409: {"model": ErrorResponse, "description": "Country re-selection required"},
        422: {"model": ErrorResponse, "description": "Invalid date range"},
        503: {"model": ErrorResponse, "description": "Tandem service unavailable"},
    },
)
@limiter.limit("5/minute")
async def import_tandem_range(
    body: TandemImportRequest,
    request: Request,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> TandemSyncResponse:
    """One-time manual import of a user-chosen date range from t:connect.

    Unlike the scheduled sync (which pulls a recent window ending now), this
    fetches exactly the requested range -- the way to backfill history or fill
    a gap after sync was off. Idempotent (ON CONFLICT DO NOTHING), so an
    overlapping re-import is safe. Rate-limited; authenticates live.
    """
    try:
        result = await sync_tandem_for_user(
            db,
            current_user.id,
            start_date=body.start_date,
            end_date=body.end_date,
        )
    except TandemNotConfiguredError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tandem integration not configured",
        ) from e
    except TandemNeedsCountryError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except TandemAuthError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Tandem credentials. Please reconnect your account.",
        ) from e
    except TandemConnectionError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to reach Tandem. Please try again later.",
        ) from e
    except TandemSyncError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Import failed: {str(e)}",
        ) from e

    # Count imported events toward the cumulative counter, matching the
    # scheduler. Atomic upsert-increment; does NOT touch last_attempt_at
    # (that's the scheduler's pacing cursor -- a manual import shouldn't
    # reset it). Best-effort: the events are already committed inside
    # sync_tandem_for_user, so a failure here must NOT turn a successful
    # import into a 500 (which would invite pointless retries against Tandem).
    if result["events_stored"]:
        try:
            await db.execute(
                pg_insert(TandemSyncState)
                .values(
                    user_id=current_user.id,
                    events_pulled_total=result["events_stored"],
                )
                .on_conflict_do_update(
                    index_elements=["user_id"],
                    set_={
                        "events_pulled_total": TandemSyncState.events_pulled_total
                        + result["events_stored"]
                    },
                )
            )
            await db.commit()
        except Exception:
            await db.rollback()
            logger.warning(
                "Tandem import succeeded but the events_pulled_total update "
                "failed (non-fatal)",
                user_id=str(current_user.id),
                exc_info=True,
            )

    last_event = None
    if result["last_event"]:
        last_event = PumpEventResponse(
            event_type=result["last_event"]["event_type"],
            event_timestamp=result["last_event"]["timestamp"],
            units=result["last_event"]["units"],
            is_automated=result["last_event"]["is_automated"],
            received_at=datetime.now(UTC),
            source="tandem",
        )

    return TandemSyncResponse(
        message="Import completed successfully",
        events_fetched=result["events_fetched"],
        events_stored=result["events_stored"],
        profiles_stored=result.get("profiles_stored", 0),
        last_event=last_event,
    )


# ---------------------------------------------------------------------------
# Medtronic CareLink -- manual historical import (feature B)
#
# Stateless: the request carries the captured auth_tmp_token bearer (the user
# grabs it via the bookmarklet capture flow). We build a COOKIE-LESS
# CareLinkClient (bearer header only -- verified sufficient for /patient/*),
# import within the token's ~50-min life, and NEVER store the token. No
# credential row / scheduler / sync-state (manual, on-demand).
# ---------------------------------------------------------------------------


def _build_carelink_client(region: str, token: str) -> CareLinkClient:
    """Cookie-less CareLink client authed by the captured bearer only.

    Region is normally validated by the request schema (-> 422); this guards the
    helper directly too so a bad region can never surface as an uncaught 500.
    """
    try:
        base_url = resolve_region_base_url(region)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    async def _bearer() -> str:
        return token

    return CareLinkClient(bearer_provider=_bearer, base_url=base_url)


def _carelink_token_or_422(token: str | None) -> str:
    """Validate the captured token from the X-CareLink-Token header. The error
    message never echoes the token value (it must not land in logs/responses)."""
    if not token or not (1 <= len(token) <= MAX_TOKEN_LEN):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing or malformed CareLink token.",
        )
    return token


@router.post(
    "/medtronic/availability",
    response_model=MedtronicAvailabilityResponse,
    responses={
        200: {"description": "Available data date range"},
        401: {"model": ErrorResponse, "description": "CareLink token invalid/expired"},
        422: {"model": ErrorResponse, "description": "Invalid region or token"},
        503: {"model": ErrorResponse, "description": "CareLink unavailable"},
    },
)
@limiter.limit("10/minute")
async def get_medtronic_availability(
    body: MedtronicAvailabilityRequest,
    request: Request,
    current_user: DiabeticOrAdminUser,
    carelink_token: str = Header(alias=CARELINK_TOKEN_HEADER),
    db: AsyncSession = Depends(get_db),
) -> MedtronicAvailabilityResponse:
    """Validate the captured CareLink token and report the available data range
    (to bound the manual-import date picker). Stateless -- the token (sent in the
    X-CareLink-Token header, never the body) is used for this call only and never
    stored.
    """
    token = _carelink_token_or_422(carelink_token)
    client = _build_carelink_client(body.region, token)
    try:
        await client.get_patient_id()  # validates the bearer early
        avail = await client.get_availability()
    except CareLinkAuthError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="CareLink session is invalid or expired. Reconnect and try again.",
        ) from e
    except CareLinkError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to reach CareLink. Please try again later.",
        ) from e
    finally:
        await client.aclose()

    return MedtronicAvailabilityResponse(start=avail.start, end=avail.end)


@router.post(
    "/medtronic/import",
    response_model=MedtronicImportResponse,
    responses={
        200: {"description": "Import completed"},
        401: {"model": ErrorResponse, "description": "CareLink token invalid/expired"},
        422: {
            "model": ErrorResponse,
            "description": "Invalid region, date range, timezone, or token",
        },
        503: {"model": ErrorResponse, "description": "CareLink unavailable"},
        504: {"model": ErrorResponse, "description": "CareLink report timed out"},
    },
)
@limiter.limit("5/minute")
async def import_medtronic_range(
    body: MedtronicImportRequest,
    request: Request,
    current_user: DiabeticOrAdminUser,
    carelink_token: str = Header(alias=CARELINK_TOKEN_HEADER),
    db: AsyncSession = Depends(get_db),
) -> MedtronicImportResponse:
    """One-time manual import of a user-chosen CareLink date range. Builds a
    cookie-less client from the captured bearer, exports the CSV, maps it, and
    stores it idempotently (upsert on natural keys -- overlapping re-imports are
    safe). The token (sent in the X-CareLink-Token header, never the body) is
    used only here and never persisted.
    """
    token = _carelink_token_or_422(carelink_token)
    client = _build_carelink_client(body.region, token)
    try:
        result = await sync_carelink_for_user(
            db,
            current_user.id,
            start_date=body.start_date,
            end_date=body.end_date,
            client=client,
            tz=zoneinfo.ZoneInfo(body.tz),
        )
    except CareLinkAuthError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="CareLink session is invalid or expired. Reconnect and try again.",
        ) from e
    except CareLinkReportTimeoutError as e:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="CareLink took too long to generate the report. Try a smaller range.",
        ) from e
    except CareLinkError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to reach CareLink. Please try again later.",
        ) from e
    finally:
        await client.aclose()

    return MedtronicImportResponse(
        message="Import completed successfully",
        glucose_fetched=result.glucose_fetched,
        glucose_stored=result.glucose_stored,
        events_fetched=result.events_fetched,
        events_stored=result.events_stored,
    )


# ---------------------------------------------------------------------------
# Medtronic CareLink CarePartner (Connect) -- autonomous sync (feature A)
#
# Disabled by default until the mapping is validated on a live pump. The
# one-time CarePartner login captures an Auth0 auth code; the backend exchanges
# it for a refresh token, stores it encrypted, and the scheduler renews + pulls
# the recent (~24h) follower snapshot on a per-user cadence (Tandem parity).
# Because the only allowed interactive grant redirects to a mobile-app custom
# scheme, the login + capture is driven by a local helper CLI, which
# authenticates here with a short-lived pairing token (see connect_pairing).
# ---------------------------------------------------------------------------


async def get_connect_actor(
    request: Request,
    pair_token: str | None = Header(default=None, alias=CONNECT_PAIR_TOKEN_HEADER),
    session_token: str | None = Cookie(default=None, alias=settings.jwt_cookie_name),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the acting user for the Connect handshake from EITHER a pairing
    token (the local login-helper CLI) OR the normal session/Bearer/API-key
    auth (the web UI). Scoped to the handshake endpoints only -- the pairing
    token cannot authenticate anything else."""
    if pair_token:
        try:
            user_id = decode_pairing_token(pair_token)
        except PairingTokenError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired pairing token. Reissue it from GlycemicGPT.",
            ) from e
        user = (
            await db.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
            )
        await require_diabetic_or_admin(request, user)
        return user
    # No pairing token -> normal auth (cookie/Bearer/API-key) + role check.
    user = await get_current_user(request, session_token, db)
    await require_diabetic_or_admin(request, user)
    return user


@router.post(
    "/medtronic/connect/pair",
    response_model=MedtronicConnectPairResponse,
    responses={
        200: {"description": "Pairing token issued"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
@limiter.limit("10/minute")
async def pair_medtronic_connect(
    request: Request,
    current_user: DiabeticOrAdminUser,
) -> MedtronicConnectPairResponse:
    """Mint a short-lived pairing token for the local login-helper CLI. Only a
    logged-in web user can mint one (for their own account)."""
    token, expires_at = issue_pairing_token(current_user.id)
    logger.info("Medtronic Connect pairing token issued", user_id=str(current_user.id))
    return MedtronicConnectPairResponse(pairing_token=token, expires_at=expires_at)


# ---------------------------------------------------------------------------
# Helper-binary distribution (gated by the pair token)
#
# These endpoints serve the small native Go helper (chromedp-driven CarePartner
# login + 302 capture) that runs on the user's PC during a one-time setup.
# They are intentionally gated by the SAME short-lived pair token used for the
# rest of the handshake -- i.e., they only respond when a user has actively
# clicked "Connect with the desktop helper" in the web UI, and they go dark
# again the moment `/exchange` consumes the token (or it expires). This is the
# explicit "not constantly exposed" property we want: no helper download
# surface exists outside an active pairing window.
#
# All failures return 404 (not 401/403) so the endpoints look indistinguishable
# from "not there" when no active pairing is in progress.
# ---------------------------------------------------------------------------

#: Where the API container has the per-OS/arch helper binaries baked in by the
#: multi-stage Dockerfile. In dev (no Go builder ran) the files are absent and
#: the binary endpoint just returns 404 -- power users fall back to the Python
#: CLI.
_CONNECT_HELPER_DIST_ROOT = Path("/app/connect-helper-dist")

#: Allowlist of (os, arch) the binary endpoint will serve. Anything else 404s.
_CONNECT_HELPER_PLATFORMS: set[tuple[str, str]] = {
    ("linux", "amd64"),
    ("linux", "arm64"),
    ("darwin", "amd64"),
    ("darwin", "arm64"),
    ("windows", "amd64"),
}


async def _pair_token_or_404(pair: str | None) -> str:
    """Validate a pair token for helper-download endpoints. Returns the jti.

    Returns 404 (not 401) on ANY failure -- a probe should not be able to
    distinguish "no active pairing" from "wrong token" from "endpoint exists."
    """
    not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if not pair:
        raise not_found
    try:
        jti = pairing_token_jti(pair)
    except PairingTokenError as e:
        raise not_found from e
    # Once /exchange consumed the token, the helper download must go dark too.
    if await is_token_blacklisted(f"medtronic_pair:{jti}"):
        raise not_found
    return jti


def _bash_q(value: str) -> str:
    """POSIX single-quote a value for safe embedding in a bash script."""
    return "'" + value.replace("'", "'\\''") + "'"


def _ps_q(value: str) -> str:
    """PowerShell single-quote a value for safe embedding in a .ps1 script."""
    return "'" + value.replace("'", "''") + "'"


def _validate_helper_inputs(
    api: str, region: str, username: str
) -> tuple[str, str, str]:
    """Common boundary checks for helper.sh / helper.ps1. 404s on any failure."""
    not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    api_stripped = (api or "").strip()
    if not api_stripped or not api_stripped.startswith(("https://", "http://")):
        raise not_found
    if len(api_stripped) > 1024 or any(c in api_stripped for c in "\r\n\0"):
        raise not_found
    try:
        get_region(region)  # validates against the live regions allowlist
    except ValueError as e:
        raise not_found from e
    user_stripped = (username or "").strip()
    if not (1 <= len(user_stripped) <= 256) or any(
        c in user_stripped for c in "\r\n\0"
    ):
        raise not_found
    return api_stripped, region.upper(), user_stripped


_HELPER_SH_TEMPLATE = """#!/bin/bash
# GlycemicGPT Medtronic CareLink CarePartner Connect helper installer.
# This script is auto-generated by your GlycemicGPT instance and is only
# valid for a single pairing window (~15 minutes, single-use).
set -eu

API={api}
PAIR={pair}
USERNAME={username}
REGION={region}

OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)
case "$ARCH" in
  x86_64|amd64) ARCH=amd64 ;;
  arm64|aarch64) ARCH=arm64 ;;
esac
case "$OS:$ARCH" in
  linux:amd64|linux:arm64|darwin:amd64|darwin:arm64) ;;
  *) echo "Unsupported OS/arch: $OS/$ARCH" >&2; exit 1 ;;
esac

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
BIN="$TMP/glycemicgpt-connect"

echo "Downloading helper for $OS/$ARCH from $API..."
curl -fsSL -H "X-Connect-Pair-Token: $PAIR" "$API/api/integrations/medtronic/connect/helper-binary?os=$OS&arch=$ARCH" -o "$BIN"
chmod +x "$BIN"

echo "Launching browser; sign in to CareLink to complete setup."
"$BIN" --api "$API" --pair "$PAIR" --username "$USERNAME" --region "$REGION"
"""


_HELPER_PS1_TEMPLATE = """# GlycemicGPT Medtronic CareLink CarePartner Connect helper installer.
# Auto-generated by your GlycemicGPT instance; valid for one pairing window.
$ErrorActionPreference = 'Stop'

$API = {api}
$PAIR = {pair}
$USERNAME = {username}
$REGION = {region}

if (-not [Environment]::Is64BitProcess) {{
    Write-Error '32-bit Windows is not supported.'
    exit 1
}}
$OS = 'windows'
$ARCH = 'amd64'

$BIN = Join-Path ([System.IO.Path]::GetTempPath()) 'glycemicgpt-connect.exe'
Write-Host "Downloading helper for $OS/$ARCH from $API..."
Invoke-WebRequest -Headers @{{ 'X-Connect-Pair-Token' = $PAIR }} -Uri "$API/api/integrations/medtronic/connect/helper-binary?os=$OS&arch=$ARCH" -OutFile $BIN -UseBasicParsing

Write-Host 'Launching browser; sign in to CareLink to complete setup.'
& $BIN --api $API --pair $PAIR --username $USERNAME --region $REGION
"""


@router.get(
    "/medtronic/connect/helper.sh",
    response_class=PlainTextResponse,
    include_in_schema=False,
)
async def medtronic_connect_helper_sh(
    request: Request,
    pair: str = Query(default=""),
    api: str = Query(default=""),
    username: str = Query(default=""),
    region: str = Query(default="US"),
) -> PlainTextResponse:
    """Render the bash helper-installer script, pre-filled and gated by the pair token."""
    await _pair_token_or_404(pair)
    api_v, region_v, username_v = _validate_helper_inputs(api, region, username)
    body = _HELPER_SH_TEMPLATE.format(
        api=_bash_q(api_v),
        pair=_bash_q(pair),
        username=_bash_q(username_v),
        region=_bash_q(region_v),
    )
    # Prevent any intermediate cache from serving a stale + tokenised script.
    return PlainTextResponse(
        body,
        media_type="text/x-shellscript; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@router.get(
    "/medtronic/connect/helper.ps1",
    response_class=PlainTextResponse,
    include_in_schema=False,
)
async def medtronic_connect_helper_ps1(
    request: Request,
    pair: str = Query(default=""),
    api: str = Query(default=""),
    username: str = Query(default=""),
    region: str = Query(default="US"),
) -> PlainTextResponse:
    """Render the PowerShell helper-installer script, pre-filled and gated by the pair token."""
    await _pair_token_or_404(pair)
    api_v, region_v, username_v = _validate_helper_inputs(api, region, username)
    body = _HELPER_PS1_TEMPLATE.format(
        api=_ps_q(api_v),
        pair=_ps_q(pair),
        username=_ps_q(username_v),
        region=_ps_q(region_v),
    )
    return PlainTextResponse(
        body,
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@router.get(
    "/medtronic/connect/helper-binary",
    include_in_schema=False,
)
async def medtronic_connect_helper_binary(
    request: Request,
    os: str = Query(default=""),
    arch: str = Query(default=""),
    pair: str = Header(default="", alias="X-Connect-Pair-Token"),
) -> FileResponse:
    """Stream the right Go helper binary for the requested OS/arch.

    The pair token is taken from the ``X-Connect-Pair-Token`` header (not the
    query string) so it can't leak through reverse-proxy access logs, browser
    history, or endpoint telemetry. The generated installer scripts send it via
    ``curl -H`` / ``Invoke-WebRequest -Headers``.

    Binaries are baked into the API image by the multi-stage Dockerfile; in dev
    (no Go builder ran) the files are absent and we 404, which falls through to
    the Python CLI as the advanced/dev path.
    """
    await _pair_token_or_404(pair)
    key = (os.lower(), arch.lower())
    if key not in _CONNECT_HELPER_PLATFORMS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    bin_name = "glycemicgpt-connect" + (".exe" if key[0] == "windows" else "")
    path = _CONNECT_HELPER_DIST_ROOT / key[0] / key[1] / bin_name
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=bin_name,
        headers={"Cache-Control": "no-store"},
    )


# ---------------------------------------------------------------------------
# Short-handle install URLs
#
# The long-form helper.sh URL carries the Fernet pair token (~272 chars) in
# the query string -- a 540-char copy-paste line in the web UI. These
# endpoints introduce an 8-byte (16-hex-char) opaque handle that indexes a
# server-side bundle containing the same {pair, api, username, region}; the
# user only ever sees the handle. Same single-use gate as the long form:
# the bundle's pair-token jti is checked against the blacklist on every
# render, so the install URL goes dark the instant /exchange consumes it.
#
# 16 hex chars = 64 bits of entropy. Inside the 15-min TTL, even at 10^5
# guesses/sec brute-force, the success probability is ~5e-11. The /install
# minter is rate-limited at 10/min behind cookie+CSRF auth, so an
# unauthenticated attacker can't even bulk-enumerate handles to test.
# ---------------------------------------------------------------------------

#: How many random bytes a handle encodes. 8 bytes -> 16 hex chars.
_INSTALL_HANDLE_BYTES = 8


def _new_install_handle() -> str:
    """Cryptographically random 16-hex-char handle for install bundles."""
    return secrets.token_hex(_INSTALL_HANDLE_BYTES)


async def _install_bundle_or_404(handle: str) -> tuple[str, str, str, str]:
    """Resolve a handle to (pair_token, api, username, region) or 404.

    Same posture as `_pair_token_or_404`: any failure (unknown handle,
    expired bundle, malformed payload, or a pair-token jti already on the
    blacklist) returns 404, so the endpoint is indistinguishable from
    "not there" without a live pairing window.
    """
    not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    bundle = await get_install_bundle(handle)
    if not bundle:
        raise not_found
    pair = bundle.get("pair")
    api = bundle.get("api")
    username = bundle.get("username")
    region = bundle.get("region")
    if not all(isinstance(v, str) and v for v in (pair, api, username, region)):
        raise not_found
    # If the underlying pair token has been consumed by /exchange (or
    # expired), the install URL must go dark too.
    try:
        jti = pairing_token_jti(pair)
    except PairingTokenError as e:
        raise not_found from e
    if await is_token_blacklisted(f"medtronic_pair:{jti}"):
        raise not_found
    return pair, api, username, region


@router.post(
    "/medtronic/connect/install",
    response_model=MedtronicConnectInstallResponse,
    responses={
        200: {"description": "Install bundle minted; handle returned"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        422: {"model": ErrorResponse, "description": "Invalid api_url/username/region"},
    },
)
@limiter.limit("10/minute")
async def install_medtronic_connect(
    request: Request,
    payload: MedtronicConnectInstallRequest,
    current_user: DiabeticOrAdminUser,
) -> MedtronicConnectInstallResponse:
    """Mint a single-use install bundle for the desktop helper.

    The bundle holds the pair token + the three "what to tell the helper"
    fields the long URL used to carry as query string. Returns only the
    opaque handle + expiry; the web card builds the actual install URL
    from its own origin (so a reverse-proxy hostname is honored).
    """
    token, expires_at = issue_pairing_token(current_user.id)
    handle = _new_install_handle()
    await store_install_bundle(
        handle,
        {
            "pair": token,
            "api": payload.api_url,
            "username": payload.username,
            "region": payload.region,
        },
        ttl_seconds=PAIR_TOKEN_TTL_SECONDS,
    )
    logger.info(
        "Medtronic Connect install bundle issued",
        user_id=str(current_user.id),
        region=payload.region,
    )
    return MedtronicConnectInstallResponse(
        handle=handle, pairing_token=token, expires_at=expires_at
    )


@router.get(
    "/medtronic/connect/install/{handle}.sh",
    response_class=PlainTextResponse,
    include_in_schema=False,
)
async def medtronic_connect_install_sh(
    request: Request,
    handle: str,
) -> PlainTextResponse:
    """Render the bash helper-installer for a short-handle bundle.

    Same output as ``/helper.sh?pair=…&api=…&username=…&region=…`` but the
    bundle's values come from Redis under the handle rather than the
    query string.
    """
    pair, api, username, region = await _install_bundle_or_404(handle)
    body = _HELPER_SH_TEMPLATE.format(
        api=_bash_q(api),
        pair=_bash_q(pair),
        username=_bash_q(username),
        region=_bash_q(region),
    )
    return PlainTextResponse(
        body,
        media_type="text/x-shellscript; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@router.get(
    "/medtronic/connect/install/{handle}.ps1",
    response_class=PlainTextResponse,
    include_in_schema=False,
)
async def medtronic_connect_install_ps1(
    request: Request,
    handle: str,
) -> PlainTextResponse:
    """Render the PowerShell helper-installer for a short-handle bundle."""
    pair, api, username, region = await _install_bundle_or_404(handle)
    body = _HELPER_PS1_TEMPLATE.format(
        api=_ps_q(api),
        pair=_ps_q(pair),
        username=_ps_q(username),
        region=_ps_q(region),
    )
    return PlainTextResponse(
        body,
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


async def _store_connect_state(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    region_key: str,
    username: str,
    refresh_token: str,
    role: str,
    patient_id: str | None,
) -> MedtronicConnectState:
    """Upsert-then-lock the Connect state row with a fresh (encrypted) credential.

    Used by both connect paths (direct header handshake + PKCE exchange). The
    refresh token is encrypted at rest and never returned to the client.
    """
    enc_username = encrypt_credential(username)
    enc_refresh = encrypt_credential(refresh_token)
    enc_patient = encrypt_credential(patient_id) if patient_id else None

    await db.execute(
        pg_insert(MedtronicConnectState)
        .values(
            user_id=user_id,
            region=region_key,
            encrypted_username=enc_username,
            encrypted_refresh_token=enc_refresh,
            role=role,
            encrypted_patient_id=enc_patient,
            enabled=True,
            status=STATUS_CONNECTED,
        )
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    state = (
        await db.execute(
            select(MedtronicConnectState)
            .where(MedtronicConnectState.user_id == user_id)
            .with_for_update()
        )
    ).scalar_one()
    # Overwrite (covers the existing-row / reconnect case).
    state.region = region_key
    state.encrypted_username = enc_username
    state.encrypted_refresh_token = enc_refresh
    state.role = role
    state.encrypted_patient_id = enc_patient
    state.enabled = True
    state.status = STATUS_CONNECTED
    state.last_error = None
    await db.commit()
    return state


def _connect_status_response(
    state: MedtronicConnectState | None,
) -> MedtronicConnectStatusResponse:
    """Build the status response from a state row (never exposes the token)."""
    if state is None:
        return MedtronicConnectStatusResponse(
            connected=False,
            status="not_configured",
            enabled=False,
        )
    return MedtronicConnectStatusResponse(
        connected=state.status == STATUS_CONNECTED,
        status=state.status,
        enabled=state.enabled,
        region=state.region,
        role=state.role,
        sync_interval_minutes=state.sync_interval_minutes,
        last_sync_at=state.last_sync_at,
        last_error=state.last_error,
        readings_synced_total=state.readings_synced_total,
    )


# How long a started PKCE login stays valid before the user must restart it.
_PKCE_SESSION_TTL_SECONDS = 900


@router.get(
    "/medtronic/connect/authorize-url",
    response_model=MedtronicConnectAuthUrlResponse,
    responses={
        200: {"description": "Authorize URL + opaque PKCE session"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        422: {"model": ErrorResponse, "description": "Invalid region"},
    },
)
@limiter.limit("10/minute")
async def get_medtronic_connect_authorize_url(
    request: Request,
    region: str = Query(description="CarePartner region: US or EU"),
    current_user: User = Depends(get_connect_actor),
) -> MedtronicConnectAuthUrlResponse:
    """Start the one-time CarePartner PKCE login.

    Returns the Auth0 ``/authorize`` URL (the user opens it, logs in, solves the
    captcha) plus an opaque, encrypted ``pkce_session`` that carries the
    code_verifier server-side -- the verifier never reaches the browser in the
    clear. The frontend round-trips ``pkce_session`` to ``/connect/exchange``.
    """
    try:
        reg = get_region(region)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from e

    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(16)
    authorize_url = build_authorize_url(reg, code_challenge=challenge, state=state)
    # Encrypt the verifier + binding into an opaque blob (Fernet). It carries no
    # usable secret in the clear and is bound to this user + a freshness stamp.
    pkce_session = encrypt_credential(
        json.dumps(
            {
                "v": verifier,
                "r": reg.key,
                "s": state,
                "u": str(current_user.id),
                "ts": int(time.time()),
            }
        )
    )
    return MedtronicConnectAuthUrlResponse(
        authorize_url=authorize_url, pkce_session=pkce_session, state=state
    )


@router.post(
    "/medtronic/connect/exchange",
    response_model=MedtronicConnectStatusResponse,
    responses={
        200: {"description": "Connected"},
        401: {"model": ErrorResponse, "description": "Authorization code rejected"},
        422: {
            "model": ErrorResponse,
            "description": "Invalid/expired session or unparseable redirect",
        },
        503: {"model": ErrorResponse, "description": "CareLink auth unavailable"},
    },
)
@limiter.limit("5/minute")
async def exchange_medtronic_connect_code(
    body: MedtronicConnectExchangeRequest,
    request: Request,
    current_user: User = Depends(get_connect_actor),
    pair_token: str | None = Header(default=None, alias=CONNECT_PAIR_TOKEN_HEADER),
    db: AsyncSession = Depends(get_db),
) -> MedtronicConnectStatusResponse:
    """Finish the login: parse the captured redirect for the ``code`` + ``state``,
    exchange them for a refresh token, and store it (encrypted). The authorization
    code is single-use and useless without the server-held verifier.

    When authenticated by a pairing token (the local helper CLI), the token's
    ``jti`` is consumed once -- AFTER the Auth0 code exchange succeeds but BEFORE
    storing -- so (a) a transient failure (bad/expired code, network) does NOT
    burn a still-valid token (the CLI can retry in the same window), and (b) a
    replayed token still can't overwrite the stored credential with a different
    CareLink account."""
    try:
        session = json.loads(decrypt_credential(body.pkce_session))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid connect session. Please restart the CarePartner login.",
        ) from e

    # Bind the session to this user + enforce freshness (replay/staleness guard).
    if session.get("u") != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Connect session does not belong to this account.",
        )
    if int(time.time()) - int(session.get("ts", 0)) > _PKCE_SESSION_TTL_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Connect login expired. Please restart the CarePartner login.",
        )

    try:
        reg = get_region(session["r"])
    except (ValueError, KeyError) as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid connect session region.",
        ) from e

    # Parse the pasted redirect (custom scheme -> still urlparse-able).
    parsed = urlparse(body.redirect_url.strip())
    qs = parse_qs(parsed.query)
    code = (qs.get("code") or [None])[0]
    returned_state = (qs.get("state") or [None])[0]
    if not code:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Could not find an authorization code in the pasted URL. Copy the "
                "full address you were redirected to after signing in."
            ),
        )
    # CSRF/mix-up guard: the returned state must match the one we issued.
    if returned_state != session.get("s"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Connect login could not be verified. Please try again.",
        )

    try:
        token_result = await exchange_code_for_tokens(reg, code, session["v"])
    except ConnectTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Could not complete the CareLink login. Please sign in again "
                "and paste the redirect promptly (the code is short-lived)."
            ),
        ) from e
    except ValueError as e:  # untrusted host (defensive)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from e

    # Auth0 exchange succeeded -> now consume the pairing token (single-use)
    # BEFORE storing, so a replayed token can't overwrite the credential. A
    # transient failure above left the token unconsumed, so the CLI can retry.
    if pair_token is not None:
        try:
            jti = pairing_token_jti(pair_token)
        except PairingTokenError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired pairing token.",
            ) from e
        if not await consume_token_once(
            f"medtronic_pair:{jti}", PAIR_TOKEN_TTL_SECONDS
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    "This pairing token was already used. Start a new connection "
                    "from GlycemicGPT to get a fresh one."
                ),
            )

    state = await _store_connect_state(
        db,
        current_user.id,
        region_key=reg.key,
        username=body.username,
        refresh_token=token_result.refresh_token,
        role=body.role,
        patient_id=body.patient_id,
    )
    logger.info(
        "Medtronic Connect connected (PKCE)",
        user_id=str(current_user.id),
        region=reg.key,
        role=body.role,
    )
    return _connect_status_response(state)


@router.get(
    "/medtronic/connect/status",
    response_model=MedtronicConnectStatusResponse,
    responses={
        200: {"description": "Connect status"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def get_medtronic_connect_status(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> MedtronicConnectStatusResponse:
    """Report the user's Medtronic Connect sync status (no token exposed)."""
    state = (
        await db.execute(
            select(MedtronicConnectState).where(
                MedtronicConnectState.user_id == current_user.id
            )
        )
    ).scalar_one_or_none()
    return _connect_status_response(state)


@router.put(
    "/medtronic/connect/settings",
    response_model=MedtronicConnectStatusResponse,
    responses={
        200: {"description": "Settings updated"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Connect not configured"},
    },
)
async def update_medtronic_connect_settings(
    body: MedtronicConnectSettingsRequest,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> MedtronicConnectStatusResponse:
    """Update the per-user Connect sync toggle + interval. 404 if not connected
    (there is no row to control until the user completes the handshake)."""
    state = (
        await db.execute(
            select(MedtronicConnectState)
            .where(MedtronicConnectState.user_id == current_user.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Medtronic Connect is not configured. Connect it first.",
        )
    state.enabled = body.enabled
    state.sync_interval_minutes = body.sync_interval_minutes
    await db.commit()
    logger.info(
        "Medtronic Connect settings updated",
        user_id=str(current_user.id),
        enabled=body.enabled,
        interval_minutes=body.sync_interval_minutes,
    )
    return _connect_status_response(state)


@router.post(
    "/medtronic/connect/disconnect",
    responses={
        200: {"description": "Disconnected"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def disconnect_medtronic_connect(
    request: Request,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Disconnect Medtronic Connect: delete the state row (and its encrypted
    refresh token). Idempotent."""
    await db.execute(
        delete(MedtronicConnectState).where(
            MedtronicConnectState.user_id == current_user.id
        )
    )
    await db.commit()
    logger.info("Medtronic Connect disconnected", user_id=str(current_user.id))
    return {"message": "Medtronic Connect disconnected"}


@router.post(
    "/medtronic/connect/sync",
    response_model=MedtronicConnectSyncResponse,
    responses={
        200: {"description": "Sync completed"},
        401: {"model": ErrorResponse, "description": "Refresh token expired"},
        404: {"model": ErrorResponse, "description": "Connect not configured"},
        503: {"model": ErrorResponse, "description": "CareLink unavailable"},
    },
)
@limiter.limit("5/minute")
async def sync_medtronic_connect_now(
    request: Request,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> MedtronicConnectSyncResponse:
    """Manually trigger a Connect sync now (in addition to the scheduler)."""
    state = (
        await db.execute(
            select(MedtronicConnectState).where(
                MedtronicConnectState.user_id == current_user.id
            )
        )
    ).scalar_one_or_none()
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Medtronic Connect is not configured. Connect it first.",
        )
    try:
        result = await sync_connect_for_user(db, state)
    except ConnectSyncError as e:
        # The orchestrator already recorded the failure on the row. A dead
        # refresh token surfaces as 401 (user must re-login); anything else 503.
        if state.status == STATUS_DISCONNECTED:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    "Your CareLink login expired. Please complete the "
                    "CarePartner sign-in again to reconnect."
                ),
            ) from e
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to reach CareLink. Please try again later.",
        ) from e

    return MedtronicConnectSyncResponse(
        message="Sync completed successfully",
        glucose_fetched=result.glucose_fetched,
        glucose_stored=result.glucose_stored,
        events_fetched=result.events_fetched,
        events_stored=result.events_stored,
    )


# ============================================================================
# Glooko (Omnipod Cloud Sync) -- autonomous sync (connect/sync API endpoints)
#
# Credential-based like Tandem (the user's own Glooko email + password), but --
# like Medtronic Connect -- everything lives on a dedicated GlookoSyncState row
# (encrypted credentials + control + freshness), so these endpoints mirror the
# Medtronic Connect URL shape. Connect records an explicit acknowledgment that
# this is an unofficial Glooko connection; credentials are Fernet-encrypted and
# NEVER logged or returned.
# ============================================================================


async def _store_glooko_state(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    region: str,
    email: str,
    password: str,
    patient_slug: str | None,
    patient_oid: str | None,
) -> GlookoSyncState:
    """Upsert-then-lock the Glooko state row with fresh (encrypted) credentials.

    Stamps the consent acknowledgment with the connect time (server-side, never a
    client value) and (re)enables sync -- reconnecting is an explicit intent to
    use the integration. Reconnecting with the SAME Glooko patient preserves the
    sync interval, cursors, and counters so continuity isn't lost; reconnecting
    with a DIFFERENT patient resets the per-stream cursors and freshness so the
    next sync can't resume from the prior account's position and mis-associate
    medical data. The credentials are encrypted at rest and never returned.
    """
    enc_email = encrypt_credential(email)
    enc_password = encrypt_credential(password)
    now = datetime.now(UTC)

    await db.execute(
        pg_insert(GlookoSyncState)
        .values(
            user_id=user_id,
            region=region,
            encrypted_email=enc_email,
            encrypted_password=enc_password,
            status=GLOOKO_STATUS_CONNECTED,
            enabled=True,
            consent_acknowledged_at=now,
            patient_slug=patient_slug,
            patient_oid=patient_oid,
        )
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    state = (
        await db.execute(
            select(GlookoSyncState)
            .where(GlookoSyncState.user_id == user_id)
            .with_for_update()
        )
    ).scalar_one()
    # Detect an account switch BEFORE overwriting: if the discovered patient
    # differs from the stored one, the existing cursors point into a different
    # account's data and must not be reused.
    patient_changed = (state.patient_slug or None) != (patient_slug or None) or (
        state.patient_oid or None
    ) != (patient_oid or None)
    # Overwrite (covers the existing-row / reconnect case).
    state.region = region
    state.encrypted_email = enc_email
    state.encrypted_password = enc_password
    state.status = GLOOKO_STATUS_CONNECTED
    state.enabled = True
    state.consent_acknowledged_at = now
    state.last_error = None
    state.patient_slug = patient_slug
    state.patient_oid = patient_oid
    if patient_changed:
        # Fresh account -> drop sync progress so the next sync starts clean.
        state.stream_cursors = None
        state.last_sync_at = None
        state.last_cgm_window_end = None
        state.readings_synced_total = 0
    await db.commit()
    return state


def _glooko_status_response(
    state: GlookoSyncState | None,
) -> GlookoStatusResponse:
    """Build the status response from a state row (never exposes credentials)."""
    if state is None:
        return GlookoStatusResponse(
            connected=False,
            status="not_configured",
            enabled=False,
        )
    return GlookoStatusResponse(
        connected=state.status == GLOOKO_STATUS_CONNECTED,
        status=state.status,
        enabled=state.enabled,
        region=state.region,
        sync_interval_minutes=state.sync_interval_minutes,
        last_sync_at=state.last_sync_at,
        last_error=state.last_error,
        readings_synced_total=state.readings_synced_total,
        consent_acknowledged_at=state.consent_acknowledged_at,
    )


@router.post(
    "/glooko",
    response_model=GlookoStatusResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Glooko connected successfully"},
        400: {"model": ErrorResponse, "description": "Invalid Glooko credentials"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        422: {
            "model": ErrorResponse,
            "description": "Validation error (consent not acknowledged, "
            "unsupported region, or malformed body)",
        },
        503: {"model": ErrorResponse, "description": "Glooko service unavailable"},
    },
)
@limiter.limit("5/minute")
async def connect_glooko(
    body: GlookoConnectRequest,
    request: Request,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> GlookoStatusResponse:
    """Connect a Glooko account: validate credentials live, then store them
    encrypted and record the consent acknowledgment.

    A live login proves the credentials work (fail fast rather than storing a
    bad credential that only fails on the first scheduled sync) and discovers the
    patient identifiers. The acknowledgment (``accept_risk``) is enforced by the
    request schema -- the user must acknowledge this is an unofficial Glooko
    connection before we store anything.
    """
    try:
        session = await glooko_login(body.email, body.password, body.region)
    except GlookoAuthError as e:
        logger.warning(
            "Glooko connection rejected (bad credentials)",
            user_id=str(current_user.id),
            region=body.region,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Glooko email or password.",
        ) from e
    except GlookoNetworkError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to reach Glooko. Please try again later.",
        ) from e
    except ValueError as e:  # unsupported region (defensive; schema validates)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from e

    state = await _store_glooko_state(
        db,
        current_user.id,
        region=body.region,
        email=body.email,
        password=body.password,
        patient_slug=session.patient_slug,
        patient_oid=session.patient_oid,
    )
    logger.info(
        "Glooko connected successfully",
        user_id=str(current_user.id),
        region=body.region,
    )
    return _glooko_status_response(state)


@router.get(
    "/glooko/status",
    response_model=GlookoStatusResponse,
    responses={
        200: {"description": "Glooko sync status"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def get_glooko_status(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> GlookoStatusResponse:
    """Report the user's Glooko sync status (no credentials exposed). Returns a
    ``not_configured`` status (rather than 404) when there is no row, so the
    Cloud Sync card can render an honest disconnected state."""
    state = (
        await db.execute(
            select(GlookoSyncState).where(GlookoSyncState.user_id == current_user.id)
        )
    ).scalar_one_or_none()
    return _glooko_status_response(state)


@router.delete(
    "/glooko",
    responses={
        200: {"description": "Glooko disconnected"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def disconnect_glooko(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Disconnect Glooko: delete the state row (and its encrypted credentials +
    consent record). Idempotent -- a no-op if the user was never connected."""
    await db.execute(
        delete(GlookoSyncState).where(GlookoSyncState.user_id == current_user.id)
    )
    await db.commit()
    logger.info("Glooko disconnected", user_id=str(current_user.id))
    return {"message": "Glooko disconnected"}


@router.post(
    "/glooko/sync",
    response_model=GlookoSyncResponse,
    responses={
        200: {"description": "Sync completed"},
        400: {"model": ErrorResponse, "description": "Glooko login no longer valid"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Glooko not configured"},
        503: {"model": ErrorResponse, "description": "Glooko service unavailable"},
    },
)
@limiter.limit("5/minute")
async def sync_glooko_now(
    request: Request,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> GlookoSyncResponse:
    """Manually trigger an incremental Glooko sync now (in addition to the
    scheduler). Resumes each stream from its stored cursor."""
    state = (
        await db.execute(
            select(GlookoSyncState).where(GlookoSyncState.user_id == current_user.id)
        )
    ).scalar_one_or_none()
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Glooko is not configured. Connect it first.",
        )
    try:
        result = await sync_glooko_for_user(db, state)
    except GlookoSyncRunError as e:
        # The orchestrator already recorded the failure on the row. Bad
        # credentials surface as disconnected (the user must reconnect);
        # anything else is transient.
        if state.status == GLOOKO_STATUS_DISCONNECTED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Your Glooko login is no longer valid. Please reconnect.",
            ) from e
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to sync from Glooko. Please try again later.",
        ) from e

    return GlookoSyncResponse(
        message="Sync completed successfully",
        glucose_fetched=result.glucose_fetched,
        glucose_stored=result.glucose_stored,
        events_fetched=result.events_fetched,
        events_stored=result.events_stored,
    )


@router.put(
    "/glooko/sync/settings",
    response_model=GlookoStatusResponse,
    responses={
        200: {"description": "Settings updated"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Glooko not configured"},
    },
)
async def update_glooko_sync_settings(
    body: GlookoSyncSettingsRequest,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> GlookoStatusResponse:
    """Update the per-user Glooko sync toggle + interval. 404 if not connected
    (there is no row to control until the user completes the connect)."""
    state = (
        await db.execute(
            select(GlookoSyncState)
            .where(GlookoSyncState.user_id == current_user.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Glooko is not configured. Connect it first.",
        )
    state.enabled = body.enabled
    state.sync_interval_minutes = body.sync_interval_minutes
    await db.commit()
    logger.info(
        "Glooko sync settings updated",
        user_id=str(current_user.id),
        enabled=body.enabled,
        interval_minutes=body.sync_interval_minutes,
    )
    return _glooko_status_response(state)


@router.get(
    "/glooko/sync/availability",
    response_model=GlookoAvailabilityResponse,
    responses={
        200: {"description": "Reachable Glooko CGM data"},
        400: {"model": ErrorResponse, "description": "Glooko login no longer valid"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Glooko not configured"},
        503: {"model": ErrorResponse, "description": "Glooko service unavailable"},
    },
)
@limiter.limit("10/minute")
async def get_glooko_sync_availability(
    request: Request,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> GlookoAvailabilityResponse:
    """Report whether CGM data is reachable in the user's Glooko cloud, to let the
    Cloud Sync card be honest about what will sync.

    A live, READ-ONLY probe: it authenticates and walks the CGM window but does
    NOT mutate the sync-state row (the Tandem #669 ``persist_status=False``
    contract), so a probe failure never flips the stored status/last_error.
    """
    state = (
        await db.execute(
            select(GlookoSyncState).where(GlookoSyncState.user_id == current_user.id)
        )
    ).scalar_one_or_none()
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Glooko is not configured. Connect it first.",
        )
    try:
        result = await probe_glooko_availability(state)
    except GlookoAuthError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your Glooko login is no longer valid. Please reconnect.",
        ) from e
    except GlookoNetworkError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to reach Glooko. Please try again later.",
        ) from e
    except ValueError as e:
        # A bad stored region or an undecryptable credential (e.g. a rotated
        # Fernet key) -- both are recovered by reconnecting, so give the same
        # remediation the rest of the integration does rather than an opaque 500.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your Glooko connection needs to be re-established. "
            "Please reconnect.",
        ) from e

    return GlookoAvailabilityResponse(
        connected=state.status == GLOOKO_STATUS_CONNECTED,
        cgm_available=result.cgm_available,
        earliest=result.earliest,
        latest=result.latest,
    )


@router.post(
    "/glooko/sync/import",
    response_model=GlookoSyncResponse,
    responses={
        200: {"description": "Import completed"},
        400: {"model": ErrorResponse, "description": "Glooko login no longer valid"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Glooko not configured"},
        503: {"model": ErrorResponse, "description": "Glooko service unavailable"},
    },
)
@limiter.limit("5/minute")
async def import_glooko_history(
    request: Request,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> GlookoSyncResponse:
    """One-time historical backfill from Glooko.

    Unlike the incremental sync (which pulls a recent window ending now), this
    paginates each pump stream from the start and walks the CGM window back over a
    bounded span -- the way to backfill history after connecting. It does NOT
    advance the incremental cursors or ``last_sync_at`` (it fills the past). Safe
    to re-run: storage is idempotent.
    """
    state = (
        await db.execute(
            select(GlookoSyncState).where(GlookoSyncState.user_id == current_user.id)
        )
    ).scalar_one_or_none()
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Glooko is not configured. Connect it first.",
        )
    try:
        result = await import_glooko_history_for_user(db, state)
    except GlookoSyncRunError as e:
        if state.status == GLOOKO_STATUS_DISCONNECTED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Your Glooko login is no longer valid. Please reconnect.",
            ) from e
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to import from Glooko. Please try again later.",
        ) from e

    return GlookoSyncResponse(
        message="Import completed successfully",
        glucose_fetched=result.glucose_fetched,
        glucose_stored=result.glucose_stored,
        events_fetched=result.events_fetched,
        events_stored=result.events_stored,
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


# ---------------------------------------------------------------------------
# Story 43.10 -- cross-source CGM primary-source picker
# ---------------------------------------------------------------------------


@router.get(
    "/cgm",
    response_model=CgmSourcesResponse,
    responses={
        200: {
            "description": (
                "The user's CGM-providing integrations (Dexcom + Nightscout), "
                "which one is primary, and whether the picker should render."
            )
        },
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
    },
)
async def get_cgm_sources(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> CgmSourcesResponse:
    """List the user's CGM sources for the primary-source picker.

    Read-only -- never mutates roles. The picker hides itself when fewer
    than two sources exist (`multiple_sources=False`): a single source is
    always primary and there is nothing to dedupe.
    """
    sources = await list_cgm_sources(db, current_user.id)
    primary = next((s.source for s in sources if s.role == CGM_ROLE_PRIMARY), None)
    return CgmSourcesResponse(
        sources=[
            CgmSourceItem(source=s.source, label=s.label, role=s.role, kind=s.kind)
            for s in sources
        ],
        primary_source=primary,
        multiple_sources=len(sources) > 1,
    )


@router.put(
    "/cgm/source",
    response_model=CgmPrimaryResponse,
    responses={
        200: {"description": "Primary CGM source updated."},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        404: {
            "model": ErrorResponse,
            "description": "`source` is not one of the user's CGM sources.",
        },
    },
)
async def update_primary_cgm_source(
    body: CgmPrimaryUpdate,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> CgmPrimaryResponse:
    """Promote the chosen CGM source to primary; demote the rest to secondary.

    Atomic across the user's CGM sources -- the chosen source becomes the
    one that drives charts/stats; the others are kept for audit but stop
    driving widgets by default.
    """
    ok = await set_primary_cgm_source(db, current_user.id, body.source)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="That source is not one of your CGM sources.",
        )
    await db.commit()
    return CgmPrimaryResponse(primary_source=body.source)


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

# RFC 9745 Deprecation header value for the legacy ``raw_events`` /
# ``pump_info`` fields on ``/pump/push``. Format is ``@<unix-timestamp>``
# (Structured Field Date item). 1779148800 == 2026-05-19 00:00:00 UTC,
# the date PR1c removed the consuming cloud-upload feature.
_PUMP_PUSH_RAW_FIELDS_DEPRECATED_AT = "@1779148800"


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
    response: Response,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> PumpPushResponse:
    """Accept a batch of pump events from a mobile client.

    Uses PostgreSQL ON CONFLICT DO NOTHING on the existing unique index
    (user_id, event_timestamp, event_type) for idempotent inserts.

    The ``raw_events`` / ``pump_info`` fields are kept for back-compat with
    older mobile builds but are discarded server-side. When either field
    is present on the request, an IETF ``Deprecation`` response header is
    set so clients have a protocol-level signal to detect and remove the
    capture logic.
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

    # ``body.raw_events`` and ``body.pump_info`` are accepted for backward
    # compatibility with mobile clients that still send them, but no longer
    # persisted -- the cloud upload feature that consumed them was removed
    # (see PR1c). The response reports zero raw_accepted/raw_duplicates so
    # the mobile client's success path still works without changes.
    #
    # RFC 9745 specifies the ``Deprecation`` header as a Structured Field
    # Date item: ``@<unix-timestamp>``. The timestamp marks the moment
    # the resource (in this case, *these specific request fields*) was
    # deprecated. We use 2026-05-19 00:00:00 UTC, the date PR1c landed.
    # Paired with ``Sunset`` (RFC 8594) -- a far-future date because we
    # still need to accept the fields from older mobile builds in the
    # field for a long tail -- and a ``Link`` to the deprecation docs.
    if body.raw_events is not None or body.pump_info is not None:
        response.headers["Deprecation"] = _PUMP_PUSH_RAW_FIELDS_DEPRECATED_AT
        response.headers["Sunset"] = "Mon, 31 Dec 2029 23:59:59 GMT"
        response.headers["Link"] = (
            "<https://glycemicgpt.org/docs/daily-use/connecting-tandem-cloud>; "
            'rel="deprecation"; type="text/html"'
        )

    await db.commit()

    logger.info(
        "Mobile pump push",
        user_id=str(current_user.id),
        total=len(rows),
        accepted=accepted,
        duplicates=duplicates,
    )

    return PumpPushResponse(
        accepted=accepted,
        duplicates=duplicates,
        raw_accepted=0,
        raw_duplicates=0,
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
    include_secondary: bool = Query(
        default=False,
        description="Include secondary CGM sources (Story 43.10). Off by default.",
    ),
) -> GlucoseStatsResponse:
    """Get aggregate glucose statistics: mean, SD, CV%, GMI, CGM active%.

    GMI (Glucose Management Indicator) estimates A1C from mean glucose
    using the formula: GMI = 3.31 + (0.02392 * mean_glucose_mg_dl).

    CGM active % assumes 5-minute reading intervals (standard for Dexcom G6/G7).

    When start and end are provided, they override the minutes parameter.
    By default aggregates the primary CGM source only (Story 43.10).
    """
    date_range = _validate_date_range(start, end)
    excluded = await get_excluded_cgm_sources(
        db, current_user.id, include_secondary=include_secondary
    )
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
    if excluded:
        conditions.append(GlucoseReading.source.notin_(excluded))

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
    include_secondary: bool = Query(
        default=False,
        description="Include secondary CGM sources (Story 43.10). Off by default.",
    ),
) -> GlucosePercentilesResponse:
    """Get AGP (Ambulatory Glucose Profile) percentile bands.

    Returns 10th, 25th, 50th, 75th, and 90th percentile glucose values
    grouped by hour of day in the specified timezone.
    Requires at least 7 days of data.
    By default profiles the primary CGM source only (Story 43.10).
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
    excluded = await get_excluded_cgm_sources(
        db, current_user.id, include_secondary=include_secondary
    )

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
            *([GlucoseReading.source.notin_(excluded)] if excluded else []),
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
