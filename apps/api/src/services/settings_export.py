"""Story 9.5: Settings export service.

Collects user settings and optionally all user data into a
structured JSON export suitable for backup or portability.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.logging_config import get_logger
from src.models.ai_provider import AIProviderConfig
from src.models.alert import Alert
from src.models.alert_threshold import AlertThreshold
from src.models.brief_delivery_config import BriefDeliveryConfig
from src.models.correction_analysis import CorrectionAnalysis
from src.models.daily_brief import DailyBrief
from src.models.data_retention_config import DataRetentionConfig
from src.models.emergency_contact import EmergencyContact
from src.models.escalation_config import EscalationConfig
from src.models.glucose import GlucoseReading
from src.models.integration import IntegrationCredential
from src.models.meal_analysis import MealAnalysis
from src.models.pump_data import PumpEvent
from src.models.safety_log import SafetyLog
from src.models.suggestion_response import SuggestionResponse
from src.models.target_glucose_range import TargetGlucoseRange

logger = get_logger(__name__)

# Maximum records per category to prevent memory exhaustion on large datasets.
MAX_EXPORT_RECORDS_PER_CATEGORY = 100_000


async def _export_settings(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """Collect all user settings into a dict.

    Queries each settings table and returns defaults-compatible
    values when a row does not yet exist.
    """
    settings: dict = {}

    # Target glucose range
    result = await db.execute(
        select(TargetGlucoseRange).where(TargetGlucoseRange.user_id == user_id)
    )
    tgr = result.scalar_one_or_none()
    settings["target_glucose_range"] = (
        {
            "low_target": tgr.low_target,
            "high_target": tgr.high_target,
        }
        if tgr
        else {"low_target": 70.0, "high_target": 180.0}
    )

    # Alert thresholds
    result = await db.execute(
        select(AlertThreshold).where(AlertThreshold.user_id == user_id)
    )
    at = result.scalar_one_or_none()
    settings["alert_thresholds"] = (
        {
            "low_warning": at.low_warning,
            "urgent_low": at.urgent_low,
            "high_warning": at.high_warning,
            "urgent_high": at.urgent_high,
            "iob_warning": at.iob_warning,
        }
        if at
        else {
            "low_warning": 70.0,
            "urgent_low": 55.0,
            "high_warning": 180.0,
            "urgent_high": 250.0,
            "iob_warning": 3.0,
        }
    )

    # Escalation config
    result = await db.execute(
        select(EscalationConfig).where(EscalationConfig.user_id == user_id)
    )
    ec = result.scalar_one_or_none()
    settings["escalation_config"] = (
        {
            "reminder_delay_minutes": ec.reminder_delay_minutes,
            "primary_contact_delay_minutes": ec.primary_contact_delay_minutes,
            "all_contacts_delay_minutes": ec.all_contacts_delay_minutes,
        }
        if ec
        else {
            "reminder_delay_minutes": 5,
            "primary_contact_delay_minutes": 10,
            "all_contacts_delay_minutes": 20,
        }
    )

    # Brief delivery config
    result = await db.execute(
        select(BriefDeliveryConfig).where(BriefDeliveryConfig.user_id == user_id)
    )
    bdc = result.scalar_one_or_none()
    settings["brief_delivery"] = (
        {
            "enabled": bdc.enabled,
            "delivery_time": bdc.delivery_time.isoformat(),
            "timezone": bdc.timezone,
            "channel": bdc.channel.value,
        }
        if bdc
        else {
            "enabled": True,
            "delivery_time": "07:00:00",
            "timezone": "UTC",
            "channel": "both",
        }
    )

    # Data retention config
    result = await db.execute(
        select(DataRetentionConfig).where(DataRetentionConfig.user_id == user_id)
    )
    drc = result.scalar_one_or_none()
    settings["data_retention"] = (
        {
            "glucose_retention_days": drc.glucose_retention_days,
            "analysis_retention_days": drc.analysis_retention_days,
            "audit_retention_days": drc.audit_retention_days,
        }
        if drc
        else {
            "glucose_retention_days": 365,
            "analysis_retention_days": 365,
            "audit_retention_days": 730,
        }
    )

    # AI provider config (no API key!)
    result = await db.execute(
        select(AIProviderConfig).where(AIProviderConfig.user_id == user_id)
    )
    apc = result.scalar_one_or_none()
    settings["ai_provider"] = (
        {
            "provider_type": apc.provider_type.value,
            "model_name": apc.model_name,
            "status": apc.status.value,
        }
        if apc
        else None
    )

    # Integrations (no credentials!)
    result = await db.execute(
        select(IntegrationCredential).where(IntegrationCredential.user_id == user_id)
    )
    integrations = result.scalars().all()
    settings["integrations"] = [
        {
            "integration_type": ic.integration_type.value,
            "status": ic.status.value,
            "region": ic.region,
            "last_sync_at": ic.last_sync_at.isoformat() if ic.last_sync_at else None,
        }
        for ic in integrations
    ]

    # Emergency contacts
    result = await db.execute(
        select(EmergencyContact)
        .where(EmergencyContact.user_id == user_id)
        .order_by(EmergencyContact.position)
    )
    contacts = result.scalars().all()
    settings["emergency_contacts"] = [
        {
            "name": c.name,
            "telegram_username": c.telegram_username,
            "priority": c.priority.value,
            "position": c.position,
        }
        for c in contacts
    ]

    return settings


async def _export_all_data(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """Collect all user data records into a dict.

    Includes glucose readings, pump events, AI analysis results,
    and audit records.  Each category is capped at
    MAX_EXPORT_RECORDS_PER_CATEGORY to prevent memory exhaustion.
    """
    data: dict = {}
    limit = MAX_EXPORT_RECORDS_PER_CATEGORY

    # Glucose readings
    result = await db.execute(
        select(GlucoseReading)
        .where(GlucoseReading.user_id == user_id)
        .order_by(GlucoseReading.reading_timestamp)
        .limit(limit)
    )
    readings = result.scalars().all()
    data["glucose_readings"] = [
        {
            "value": r.value,
            "reading_timestamp": r.reading_timestamp.isoformat(),
            "trend": r.trend.value,
            "trend_rate": r.trend_rate,
            "source": r.source,
        }
        for r in readings
    ]

    # Pump events
    result = await db.execute(
        select(PumpEvent)
        .where(PumpEvent.user_id == user_id)
        .order_by(PumpEvent.event_timestamp)
        .limit(limit)
    )
    events = result.scalars().all()
    data["pump_events"] = [
        {
            "event_type": e.event_type.value,
            "event_timestamp": e.event_timestamp.isoformat(),
            "units": e.units,
            "duration_minutes": e.duration_minutes,
            "is_automated": e.is_automated,
            "source": e.source,
        }
        for e in events
    ]

    # Daily briefs
    result = await db.execute(
        select(DailyBrief)
        .where(DailyBrief.user_id == user_id)
        .order_by(DailyBrief.period_start)
        .limit(limit)
    )
    briefs = result.scalars().all()
    data["daily_briefs"] = [
        {
            "period_start": b.period_start.isoformat(),
            "period_end": b.period_end.isoformat(),
            "ai_summary": b.ai_summary,
            "time_in_range_pct": b.time_in_range_pct,
            "average_glucose": b.average_glucose,
            "readings_count": b.readings_count,
            "created_at": b.created_at.isoformat(),
        }
        for b in briefs
    ]

    # Meal analyses
    result = await db.execute(
        select(MealAnalysis)
        .where(MealAnalysis.user_id == user_id)
        .order_by(MealAnalysis.period_start)
        .limit(limit)
    )
    meals = result.scalars().all()
    data["meal_analyses"] = [
        {
            "period_start": m.period_start.isoformat(),
            "period_end": m.period_end.isoformat(),
            "ai_analysis": m.ai_analysis,
            "total_boluses": m.total_boluses,
            "total_spikes": m.total_spikes,
            "avg_post_meal_peak": m.avg_post_meal_peak,
            "created_at": m.created_at.isoformat(),
        }
        for m in meals
    ]

    # Correction analyses
    result = await db.execute(
        select(CorrectionAnalysis)
        .where(CorrectionAnalysis.user_id == user_id)
        .order_by(CorrectionAnalysis.period_start)
        .limit(limit)
    )
    corrections = result.scalars().all()
    data["correction_analyses"] = [
        {
            "period_start": c.period_start.isoformat(),
            "period_end": c.period_end.isoformat(),
            "ai_analysis": c.ai_analysis,
            "total_corrections": c.total_corrections,
            "under_corrections": c.under_corrections,
            "over_corrections": c.over_corrections,
            "avg_observed_isf": c.avg_observed_isf,
            "created_at": c.created_at.isoformat(),
        }
        for c in corrections
    ]

    # Suggestion responses
    result = await db.execute(
        select(SuggestionResponse)
        .where(SuggestionResponse.user_id == user_id)
        .order_by(SuggestionResponse.created_at)
        .limit(limit)
    )
    responses = result.scalars().all()
    data["suggestion_responses"] = [
        {
            "analysis_type": sr.analysis_type,
            "response": sr.response,
            "reason": sr.reason,
            "created_at": sr.created_at.isoformat(),
        }
        for sr in responses
    ]

    # Safety logs
    result = await db.execute(
        select(SafetyLog)
        .where(SafetyLog.user_id == user_id)
        .order_by(SafetyLog.created_at)
        .limit(limit)
    )
    logs = result.scalars().all()
    data["safety_logs"] = [
        {
            "analysis_type": sl.analysis_type,
            "status": sl.status,
            "has_dangerous_content": sl.has_dangerous_content,
            "created_at": sl.created_at.isoformat(),
        }
        for sl in logs
    ]

    # Alerts
    result = await db.execute(
        select(Alert)
        .where(Alert.user_id == user_id)
        .order_by(Alert.created_at)
        .limit(limit)
    )
    alerts = result.scalars().all()
    data["alerts"] = [
        {
            "alert_type": a.alert_type.value,
            "severity": a.severity.value,
            "message": a.message,
            "acknowledged": a.acknowledged,
            "created_at": a.created_at.isoformat(),
        }
        for a in alerts
    ]

    return data


def _record_counts_from_data(data: dict) -> dict[str, int]:
    """Derive record counts from already-loaded data lists."""
    return {key: len(records) for key, records in data.items()}


async def export_user_data(
    user_id: uuid.UUID,
    db: AsyncSession,
    *,
    include_data: bool = False,
) -> dict:
    """Build a complete export payload for the user.

    Args:
        user_id: User's UUID.
        db: Database session.
        include_data: When True, include all historical data
            (glucose, pump, analysis, audit records).

    Returns:
        Structured dict ready for JSON serialization.
    """
    logger.info(
        "Settings export initiated",
        user_id=str(user_id),
        include_data=include_data,
    )

    export: dict = {
        "metadata": {
            "export_date": datetime.now(UTC).isoformat(),
            "export_type": "all_data" if include_data else "settings_only",
            "version": "1.0",
        },
        "settings": await _export_settings(user_id, db),
    }

    if include_data:
        export["data"] = await _export_all_data(user_id, db)
        export["metadata"]["record_counts"] = _record_counts_from_data(export["data"])

    logger.info(
        "Settings export completed",
        user_id=str(user_id),
        include_data=include_data,
    )

    return export
