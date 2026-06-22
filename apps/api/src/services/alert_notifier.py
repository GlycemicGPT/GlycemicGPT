"""Story 7.2: Alert delivery via Telegram.

Formats and sends Telegram notifications for glucose alerts.
Two paths:
  - Path A: Immediate alert delivery to the user's own Telegram
  - Path B: Escalation delivery to emergency contacts' Telegram accounts
"""

import html
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.units import GlucoseUnit, format_glucose
from src.logging_config import get_logger
from src.models.alert import Alert, AlertSeverity, AlertType
from src.services.telegram_bot import (
    TelegramBotError,
    get_telegram_link,
    send_message,
)

logger = get_logger(__name__)

# Severity -> emoji mapping
SEVERITY_EMOJI: dict[AlertSeverity, str] = {
    AlertSeverity.INFO: "\u2139\ufe0f",  # ℹ️
    AlertSeverity.WARNING: "\u26a0\ufe0f",  # ⚠️
    AlertSeverity.URGENT: "\U0001f6a8",  # 🚨
    AlertSeverity.EMERGENCY: "\U0001f198",  # 🆘
}

# Alert type -> headline mapping
ALERT_HEADLINE: dict[AlertType, str] = {
    AlertType.LOW_URGENT: "Urgent Low Glucose",
    AlertType.LOW_WARNING: "Low Glucose Warning",
    AlertType.HIGH_WARNING: "High Glucose Warning",
    AlertType.HIGH_URGENT: "Urgent High Glucose",
    AlertType.IOB_WARNING: "High Insulin on Board",
}

# Alert type -> recommended action
ALERT_ACTION: dict[AlertType, str] = {
    AlertType.LOW_URGENT: "Consume fast-acting carbs immediately",
    AlertType.LOW_WARNING: "Consider eating a snack with carbs",
    AlertType.HIGH_WARNING: "Check insulin dosing and hydration",
    AlertType.HIGH_URGENT: "Check for missed bolus or pump issue",
    AlertType.IOB_WARNING: "Monitor glucose closely for dropping trend",
}


def trend_description(trend_rate: float | None) -> str:
    """Convert a trend rate (mg/dL/min) to a human-readable description."""
    if trend_rate is None:
        return "unknown"
    if trend_rate > 3.0:
        return "\u2191\u2191 rising fast"
    if trend_rate > 1.0:
        return "\u2191 rising"
    if trend_rate > 0.5:
        return "\u2197 rising slowly"
    if trend_rate >= -0.5:
        return "\u2192 stable"
    if trend_rate >= -1.0:
        return "\u2198 falling slowly"
    if trend_rate >= -3.0:
        return "\u2193 falling"
    return "\u2193\u2193 falling fast"


def format_alert_message(
    alert: Alert,
    unit: GlucoseUnit = GlucoseUnit.MGDL,
) -> str:
    """Format an Alert into a rich HTML Telegram message.

    Args:
        alert: The Alert model instance.
        unit: The patient's glucose display unit; the current and predicted
            glucose render in it (stored values stay canonical mg/dL).

    Returns:
        HTML-formatted message string for Telegram.
    """
    emoji = SEVERITY_EMOJI.get(alert.severity, "\u2139\ufe0f")
    headline = ALERT_HEADLINE.get(alert.alert_type, "Glucose Alert")
    action = ALERT_ACTION.get(alert.alert_type, "Check your glucose levels")
    trend = trend_description(alert.trend_rate)

    lines = [
        f"{emoji} <b>{headline}</b>",
        "",
        f"\U0001f4c9 <b>Glucose:</b> {format_glucose(alert.current_value, unit)}",
        f"\U0001f4c8 <b>Trend:</b> {trend}",
    ]

    if alert.predicted_value is not None and alert.prediction_minutes is not None:
        lines.append(
            f"\U0001f52e <b>Predicted:</b> "
            f"{format_glucose(alert.predicted_value, unit)} "
            f"in {alert.prediction_minutes} min"
        )

    if alert.iob_value is not None:
        lines.append(f"\U0001f489 <b>IoB:</b> {alert.iob_value:.1f} units")

    lines.extend(
        [
            "",
            f"\U0001f4a1 <b>Action:</b> {action}",
            "",
            f"/acknowledge_{alert.id}",
        ]
    )

    return "\n".join(lines)


def format_escalation_contact_message(
    alert: Alert,
    user_email: str,
    tier_label: str,
    unit: GlucoseUnit = GlucoseUnit.MGDL,
) -> str:
    """Format a Telegram message for an emergency contact escalation.

    Args:
        alert: The Alert model instance.
        user_email: The user's email for identification.
        tier_label: Human-readable tier label.
        unit: The PATIENT's glucose display unit -- the contact sees the
            patient's glucose in the patient's unit, never the contact's own.

    Returns:
        HTML-formatted message string for Telegram.
    """
    emoji = SEVERITY_EMOJI.get(alert.severity, "\U0001f6a8")
    headline = ALERT_HEADLINE.get(alert.alert_type, "Glucose Alert")
    trend = trend_description(alert.trend_rate)

    safe_email = html.escape(user_email)
    safe_tier = html.escape(tier_label)

    lines = [
        f"{emoji} <b>{safe_tier}</b>",
        "",
        f"<b>{safe_email}</b> has an unacknowledged glucose alert.",
        "",
        f"\U0001f4cb <b>Alert:</b> {headline}",
        f"\U0001f4c9 <b>Glucose:</b> {format_glucose(alert.current_value, unit)}",
        f"\U0001f4c8 <b>Trend:</b> {trend}",
        "",
        "Please check on them immediately.",
    ]

    return "\n".join(lines)


async def notify_user_of_alerts(
    db: AsyncSession,
    user_id: uuid.UUID,
    alerts: list[Alert],
    unit: GlucoseUnit = GlucoseUnit.MGDL,
) -> int:
    """Send Telegram notifications to the user for newly created alerts.

    Fire-and-forget: Telegram failures are logged but never raised.
    Only sends if the user has a verified TelegramLink.

    Args:
        db: Database session (for looking up TelegramLink).
        user_id: The user's UUID.
        alerts: List of newly created Alert instances.
        unit: The patient's glucose display unit for the rendered messages.

    Returns:
        Number of messages successfully sent.
    """
    if not alerts:
        return 0

    link = await get_telegram_link(db, user_id)
    if link is None or not link.is_verified:
        logger.debug(
            "No verified Telegram link, skipping alert notification",
            user_id=str(user_id),
        )
        return 0

    sent_count = 0
    for alert in alerts:
        try:
            message = format_alert_message(alert, unit)
            await send_message(link.chat_id, message)
            sent_count += 1
            logger.info(
                "Telegram alert sent to user",
                user_id=str(user_id),
                alert_id=str(alert.id),
                alert_type=alert.alert_type.value,
                severity=alert.severity.value,
            )
        except TelegramBotError as e:
            logger.warning(
                "Failed to send Telegram alert to user",
                user_id=str(user_id),
                alert_id=str(alert.id),
                error=str(e),
            )
        except Exception as e:
            logger.error(
                "Unexpected error sending Telegram alert",
                user_id=str(user_id),
                alert_id=str(alert.id),
                error=str(e),
            )

    return sent_count
