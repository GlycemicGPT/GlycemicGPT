"""Stories 6.1, 6.6, 9.1, 9.2, 9.3, 9.4, 9.5: Settings router.

Provides endpoints for managing user alert thresholds, escalation timing,
target glucose range, brief delivery configuration, data retention settings,
data purge capability, and settings export.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import get_current_user, require_diabetic_or_admin
from src.database import get_db
from src.models.user import User
from src.schemas.alert_threshold import (
    AlertThresholdDefaults,
    AlertThresholdResponse,
    AlertThresholdUpdate,
)
from src.schemas.brief_delivery_config import (
    BriefDeliveryConfigDefaults,
    BriefDeliveryConfigResponse,
    BriefDeliveryConfigUpdate,
)
from src.schemas.data_purge import DataPurgeRequest, DataPurgeResponse
from src.schemas.data_retention_config import (
    DataRetentionConfigDefaults,
    DataRetentionConfigResponse,
    DataRetentionConfigUpdate,
    StorageUsageResponse,
)
from src.schemas.escalation_config import (
    EscalationConfigDefaults,
    EscalationConfigResponse,
    EscalationConfigUpdate,
)
from src.schemas.insulin_config import (
    InsulinConfigDefaults,
    InsulinConfigResponse,
    InsulinConfigUpdate,
)
from src.schemas.safety_limits import (
    SafetyLimitsDefaults,
    SafetyLimitsResponse,
    SafetyLimitsUpdate,
)
from src.schemas.settings_export import (
    ExportType,
    SettingsExportRequest,
    SettingsExportResponse,
)
from src.schemas.target_glucose_range import (
    TargetGlucoseRangeDefaults,
    TargetGlucoseRangeResponse,
    TargetGlucoseRangeUpdate,
)
from src.services.alert_threshold import get_or_create_thresholds, update_thresholds
from src.services.brief_delivery_config import (
    get_or_create_config as get_or_create_brief_config,
)
from src.services.brief_delivery_config import update_config as update_brief_config
from src.services.data_purge import purge_all_user_data
from src.services.data_retention_config import (
    get_or_create_config as get_or_create_retention_config,
)
from src.services.data_retention_config import (
    get_storage_usage,
)
from src.services.data_retention_config import (
    update_config as update_retention_config,
)
from src.services.escalation_config import get_or_create_config, update_config
from src.services.insulin_config import (
    get_or_create_config as get_or_create_insulin_config,
)
from src.services.insulin_config import update_config as update_insulin_config
from src.services.safety_limits import (
    get_or_create_safety_limits,
    update_safety_limits,
)
from src.services.settings_export import export_user_data
from src.services.target_glucose_range import get_or_create_range, update_range

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get(
    "/alert-thresholds",
    response_model=AlertThresholdResponse,
    dependencies=[Depends(require_diabetic_or_admin)],
)
async def get_alert_thresholds(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlertThresholdResponse:
    """Get the current user's alert thresholds.

    Returns defaults if no thresholds have been configured yet.
    """
    thresholds = await get_or_create_thresholds(user.id, db)
    return AlertThresholdResponse.model_validate(thresholds)


@router.patch(
    "/alert-thresholds",
    response_model=AlertThresholdResponse,
    dependencies=[Depends(require_diabetic_or_admin)],
)
async def patch_alert_thresholds(
    body: AlertThresholdUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlertThresholdResponse:
    """Update the current user's alert thresholds.

    Only provided fields are updated. Validates that threshold
    ordering remains consistent (urgent_low < low_warning <
    high_warning < urgent_high).
    """
    try:
        thresholds = await update_thresholds(user.id, body, db)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    return AlertThresholdResponse.model_validate(thresholds)


@router.get("/alert-thresholds/defaults", response_model=AlertThresholdDefaults)
async def get_alert_threshold_defaults() -> AlertThresholdDefaults:
    """Get the default alert threshold values for reference.

    This endpoint does not require authentication.
    """
    return AlertThresholdDefaults()


# ── Escalation timing endpoints ──


@router.get(
    "/escalation-config",
    response_model=EscalationConfigResponse,
    dependencies=[Depends(require_diabetic_or_admin)],
)
async def get_escalation_config(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EscalationConfigResponse:
    """Get the current user's escalation timing configuration.

    Returns defaults if no configuration has been set yet.
    """
    config = await get_or_create_config(user.id, db)
    return EscalationConfigResponse.model_validate(config)


@router.patch(
    "/escalation-config",
    response_model=EscalationConfigResponse,
    dependencies=[Depends(require_diabetic_or_admin)],
)
async def patch_escalation_config(
    body: EscalationConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EscalationConfigResponse:
    """Update the current user's escalation timing configuration.

    Only provided fields are updated. Validates that tier ordering
    remains consistent (reminder < primary_contact < all_contacts).
    """
    try:
        config = await update_config(user.id, body, db)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    return EscalationConfigResponse.model_validate(config)


@router.get("/escalation-config/defaults", response_model=EscalationConfigDefaults)
async def get_escalation_config_defaults() -> EscalationConfigDefaults:
    """Get the default escalation timing values for reference.

    This endpoint does not require authentication.
    """
    return EscalationConfigDefaults()


# ── Target glucose range endpoints (Story 9.1) ──


@router.get(
    "/target-glucose-range",
    response_model=TargetGlucoseRangeResponse,
    dependencies=[Depends(require_diabetic_or_admin)],
)
async def get_target_glucose_range(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TargetGlucoseRangeResponse:
    """Get the current user's target glucose range.

    Returns all four thresholds (urgent_low, low_target, high_target,
    urgent_high). Creates defaults if no range has been configured yet.
    """
    target_range = await get_or_create_range(user.id, db)
    return TargetGlucoseRangeResponse.model_validate(target_range)


@router.patch(
    "/target-glucose-range",
    response_model=TargetGlucoseRangeResponse,
    dependencies=[Depends(require_diabetic_or_admin)],
)
async def patch_target_glucose_range(
    body: TargetGlucoseRangeUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TargetGlucoseRangeResponse:
    """Update the current user's target glucose range.

    Only provided fields are updated. Validates ordering:
    urgent_low < low_target < high_target < urgent_high
    after merge with existing values.
    """
    try:
        target_range = await update_range(user.id, body, db)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    return TargetGlucoseRangeResponse.model_validate(target_range)


@router.get(
    "/target-glucose-range/defaults",
    response_model=TargetGlucoseRangeDefaults,
)
async def get_target_glucose_range_defaults() -> TargetGlucoseRangeDefaults:
    """Get the default target glucose range values for reference.

    This endpoint does not require authentication.
    """
    return TargetGlucoseRangeDefaults()


# ── Insulin configuration endpoints ──


@router.get(
    "/insulin-config",
    response_model=InsulinConfigResponse,
    dependencies=[Depends(require_diabetic_or_admin)],
)
async def get_insulin_config(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InsulinConfigResponse:
    """Get the current user's insulin configuration.

    Returns defaults (Humalog, 4h DIA) if not configured yet.
    """
    config = await get_or_create_insulin_config(user.id, db)
    return InsulinConfigResponse.model_validate(config)


@router.patch(
    "/insulin-config",
    response_model=InsulinConfigResponse,
    dependencies=[Depends(require_diabetic_or_admin)],
)
async def patch_insulin_config(
    body: InsulinConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InsulinConfigResponse:
    """Update the current user's insulin configuration.

    Only provided fields are updated. DIA must be between 2-8 hours.
    """
    config = await update_insulin_config(user.id, body, db)
    return InsulinConfigResponse.model_validate(config)


@router.get(
    "/insulin-config/defaults",
    response_model=InsulinConfigDefaults,
)
async def get_insulin_config_defaults() -> InsulinConfigDefaults:
    """Get the default insulin configuration values and presets.

    This endpoint does not require authentication.
    """
    return InsulinConfigDefaults()


# ── Brief delivery configuration endpoints (Story 9.2) ──


@router.get(
    "/brief-delivery",
    response_model=BriefDeliveryConfigResponse,
    dependencies=[Depends(require_diabetic_or_admin)],
)
async def get_brief_delivery_config(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BriefDeliveryConfigResponse:
    """Get the current user's brief delivery configuration.

    Returns defaults (enabled, 07:00 UTC, both channels) if not configured yet.
    """
    config = await get_or_create_brief_config(user.id, db)
    return BriefDeliveryConfigResponse.model_validate(config)


@router.patch(
    "/brief-delivery",
    response_model=BriefDeliveryConfigResponse,
    dependencies=[Depends(require_diabetic_or_admin)],
)
async def patch_brief_delivery_config(
    body: BriefDeliveryConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BriefDeliveryConfigResponse:
    """Update the current user's brief delivery configuration.

    Only provided fields are updated. Validates timezone is a valid IANA zone.
    """
    try:
        config = await update_brief_config(user.id, body, db)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    return BriefDeliveryConfigResponse.model_validate(config)


@router.get(
    "/brief-delivery/defaults",
    response_model=BriefDeliveryConfigDefaults,
)
async def get_brief_delivery_defaults() -> BriefDeliveryConfigDefaults:
    """Get the default brief delivery configuration values for reference.

    This endpoint does not require authentication.
    """
    return BriefDeliveryConfigDefaults()


# ── Data retention configuration endpoints (Story 9.3) ──


@router.get(
    "/data-retention",
    response_model=DataRetentionConfigResponse,
    dependencies=[Depends(require_diabetic_or_admin)],
)
async def get_data_retention_config(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataRetentionConfigResponse:
    """Get the current user's data retention configuration.

    Returns defaults (365d glucose, 365d analysis, 730d audit) if not configured.
    """
    config = await get_or_create_retention_config(user.id, db)
    return DataRetentionConfigResponse.model_validate(config)


@router.patch(
    "/data-retention",
    response_model=DataRetentionConfigResponse,
    dependencies=[Depends(require_diabetic_or_admin)],
)
async def patch_data_retention_config(
    body: DataRetentionConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataRetentionConfigResponse:
    """Update the current user's data retention configuration.

    Only provided fields are updated. All values must be 30-3650 days.
    """
    try:
        config = await update_retention_config(user.id, body, db)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    return DataRetentionConfigResponse.model_validate(config)


@router.get(
    "/data-retention/defaults",
    response_model=DataRetentionConfigDefaults,
)
async def get_data_retention_defaults() -> DataRetentionConfigDefaults:
    """Get the default data retention configuration values for reference.

    This endpoint does not require authentication.
    """
    return DataRetentionConfigDefaults()


@router.get(
    "/data-retention/usage",
    response_model=StorageUsageResponse,
    dependencies=[Depends(require_diabetic_or_admin)],
)
async def get_data_retention_usage(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StorageUsageResponse:
    """Get the current user's storage usage (record counts by category)."""
    return await get_storage_usage(user.id, db)


# ── Safety limits endpoints (Phase 3) ──


@router.get(
    "/safety-limits",
    response_model=SafetyLimitsResponse,
    dependencies=[Depends(require_diabetic_or_admin)],
)
async def get_safety_limits(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SafetyLimitsResponse:
    """Get the current user's safety limits.

    Returns glucose validity bounds and maximum insulin delivery rates.
    Creates defaults if no limits have been configured yet.
    """
    limits = await get_or_create_safety_limits(user.id, db)
    return SafetyLimitsResponse.model_validate(limits)


@router.patch(
    "/safety-limits",
    response_model=SafetyLimitsResponse,
    dependencies=[Depends(require_diabetic_or_admin)],
)
async def patch_safety_limits(
    body: SafetyLimitsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SafetyLimitsResponse:
    """Update the current user's safety limits.

    Only provided fields are updated. Validates that
    min_glucose_mgdl < max_glucose_mgdl after merge with existing values.
    """
    try:
        limits = await update_safety_limits(user.id, body, db)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    return SafetyLimitsResponse.model_validate(limits)


@router.get(
    "/safety-limits/defaults",
    response_model=SafetyLimitsDefaults,
)
async def get_safety_limits_defaults() -> SafetyLimitsDefaults:
    """Get the default safety limits values for reference.

    This endpoint does not require authentication.
    """
    return SafetyLimitsDefaults()


# ── Data purge endpoint (Story 9.4) ──


@router.post(
    "/data-retention/purge",
    response_model=DataPurgeResponse,
    dependencies=[Depends(require_diabetic_or_admin)],
)
async def purge_data(
    body: DataPurgeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataPurgeResponse:
    """Permanently delete all user data except account and settings.

    Requires confirmation_text to be exactly "DELETE" (case-sensitive).
    This action is irreversible. Glucose readings, pump events, AI analysis
    results, and audit records are permanently removed. Account settings
    and configuration preferences are preserved.
    """
    if body.confirmation_text != "DELETE":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail='confirmation_text must be exactly "DELETE"',
        )

    deleted = await purge_all_user_data(user.id, db)
    total = sum(deleted.values())

    return DataPurgeResponse(
        success=True,
        deleted_records=deleted,
        total_deleted=total,
        message=f"Successfully purged {total} records",
    )


# ── Settings export endpoint (Story 9.5) ──


@router.post(
    "/export",
    response_model=SettingsExportResponse,
    dependencies=[Depends(require_diabetic_or_admin)],
)
async def export_settings(
    body: SettingsExportRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SettingsExportResponse:
    """Export user settings and optionally all data as JSON.

    Export types:
    - settings_only: All configuration preferences (no historical data)
    - all_data: Settings plus glucose readings, pump events, AI analysis,
      and audit records

    Integration credentials and API keys are never included in exports.
    """
    include_data = body.export_type == ExportType.ALL_DATA
    export_data = await export_user_data(user.id, db, include_data=include_data)
    return SettingsExportResponse(export_data=export_data)
