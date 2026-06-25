"""Story 6.7: Alert escalation engine.

Automatically escalates unacknowledged URGENT and EMERGENCY alerts
to emergency contacts based on user-configured timing.
"""

import html
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.units import GlucoseUnit, format_glucose
from src.logging_config import get_logger
from src.models.alert import Alert, AlertSeverity
from src.models.emergency_contact import ContactPriority, EmergencyContact
from src.models.escalation_config import EscalationConfig
from src.models.escalation_event import (
    EscalationEvent,
    EscalationTier,
    NotificationStatus,
)
from src.models.telegram_link import TelegramLink
from src.services.escalation_config import get_or_create_config
from src.services.glucose_unit import resolve_glucose_unit
from src.services.telegram_bot import TelegramBotError, send_message

logger = get_logger(__name__)


@dataclass
class EscalationDecision:
    """Decision about whether to escalate an alert."""

    should_escalate: bool
    tier: EscalationTier | None
    reason: str


async def get_unacknowledged_critical_alerts(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[Alert]:
    """Get all unacknowledged URGENT or EMERGENCY alerts for a user.

    Args:
        db: Database session.
        user_id: User's UUID.

    Returns:
        List of unacknowledged critical alerts, newest first.
    """
    now = datetime.now(UTC)

    result = await db.execute(
        select(Alert)
        .where(
            and_(
                Alert.user_id == user_id,
                Alert.acknowledged.is_(False),
                Alert.expires_at > now,
                Alert.severity.in_([AlertSeverity.URGENT, AlertSeverity.EMERGENCY]),
            )
        )
        .order_by(Alert.created_at.desc())
    )
    return list(result.scalars().all())


async def get_escalation_events_for_alert(
    db: AsyncSession,
    alert_id: uuid.UUID,
) -> list[EscalationEvent]:
    """Get all escalation events for an alert.

    Args:
        db: Database session.
        alert_id: Alert's UUID.

    Returns:
        List of escalation events, ordered by triggered_at.
    """
    result = await db.execute(
        select(EscalationEvent)
        .where(EscalationEvent.alert_id == alert_id)
        .order_by(EscalationEvent.triggered_at)
    )
    return list(result.scalars().all())


def determine_next_escalation_tier(
    alert: Alert,
    config: EscalationConfig,
    existing_events: list[EscalationEvent],
) -> EscalationDecision:
    """Determine if an alert should escalate and to which tier.

    Args:
        alert: The alert to evaluate.
        config: User's escalation configuration.
        existing_events: Escalation events already triggered for this alert.

    Returns:
        EscalationDecision with tier and reason.
    """
    now = datetime.now(UTC)
    alert_age_minutes = (now - alert.created_at).total_seconds() / 60

    # Build set of tiers already triggered
    triggered_tiers = {event.tier for event in existing_events}

    # Check reminder tier (Tier 1)
    if EscalationTier.REMINDER not in triggered_tiers:
        if alert_age_minutes >= config.reminder_delay_minutes:
            return EscalationDecision(
                should_escalate=True,
                tier=EscalationTier.REMINDER,
                reason=(
                    f"Alert age ({alert_age_minutes:.1f}m) >= "
                    f"reminder delay ({config.reminder_delay_minutes}m)"
                ),
            )
        return EscalationDecision(
            should_escalate=False,
            tier=None,
            reason=(
                f"Alert age ({alert_age_minutes:.1f}m) < "
                f"reminder delay ({config.reminder_delay_minutes}m)"
            ),
        )

    # Check primary contact tier (Tier 2)
    if EscalationTier.PRIMARY_CONTACT not in triggered_tiers:
        if alert_age_minutes >= config.primary_contact_delay_minutes:
            return EscalationDecision(
                should_escalate=True,
                tier=EscalationTier.PRIMARY_CONTACT,
                reason=(
                    f"Alert age ({alert_age_minutes:.1f}m) >= "
                    f"primary delay ({config.primary_contact_delay_minutes}m)"
                ),
            )
        return EscalationDecision(
            should_escalate=False,
            tier=None,
            reason=(
                f"Alert age ({alert_age_minutes:.1f}m) < "
                f"primary delay ({config.primary_contact_delay_minutes}m)"
            ),
        )

    # Check all contacts tier (Tier 3)
    if EscalationTier.ALL_CONTACTS not in triggered_tiers:
        if alert_age_minutes >= config.all_contacts_delay_minutes:
            return EscalationDecision(
                should_escalate=True,
                tier=EscalationTier.ALL_CONTACTS,
                reason=(
                    f"Alert age ({alert_age_minutes:.1f}m) >= "
                    f"all contacts delay ({config.all_contacts_delay_minutes}m)"
                ),
            )
        return EscalationDecision(
            should_escalate=False,
            tier=None,
            reason=(
                f"Alert age ({alert_age_minutes:.1f}m) < "
                f"all contacts delay ({config.all_contacts_delay_minutes}m)"
            ),
        )

    # All tiers already triggered
    return EscalationDecision(
        should_escalate=False,
        tier=None,
        reason="All escalation tiers already triggered",
    )


async def get_contacts_for_tier(
    db: AsyncSession,
    user_id: uuid.UUID,
    tier: EscalationTier,
) -> list[EmergencyContact]:
    """Get emergency contacts to notify for a given tier.

    Args:
        db: Database session.
        user_id: User's UUID.
        tier: Escalation tier.

    Returns:
        List of emergency contacts to notify.
    """
    if tier == EscalationTier.REMINDER:
        # Reminder tier: no contacts (user notification only)
        return []

    if tier == EscalationTier.PRIMARY_CONTACT:
        # Primary tier: only primary contacts
        result = await db.execute(
            select(EmergencyContact)
            .where(
                and_(
                    EmergencyContact.user_id == user_id,
                    EmergencyContact.priority == ContactPriority.PRIMARY,
                )
            )
            .order_by(EmergencyContact.position)
        )
        return list(result.scalars().all())

    # All contacts tier
    result = await db.execute(
        select(EmergencyContact)
        .where(EmergencyContact.user_id == user_id)
        .order_by(EmergencyContact.priority, EmergencyContact.position)
    )
    return list(result.scalars().all())


def build_escalation_message(
    alert: Alert,
    tier: EscalationTier,
    user_email: str,
    unit: GlucoseUnit = GlucoseUnit.MGDL,
) -> str:
    """Build the notification message for an escalation tier.

    Args:
        alert: The alert being escalated.
        tier: Escalation tier.
        user_email: User's email (for identification).
        unit: The PATIENT's glucose display unit; the current glucose renders
            in it. ``alert.message`` was already rendered in the patient's unit
            at persist time, so it is embedded verbatim.

    Returns:
        Formatted message string.
    """
    safe_email = html.escape(user_email)
    safe_message = html.escape(alert.message)
    current_glucose = format_glucose(alert.current_value, unit)

    if tier == EscalationTier.REMINDER:
        return (
            f"[REMINDER] You have an unacknowledged "
            f"{alert.severity.value.upper()} alert:\n"
            f"{safe_message}\n"
            f"Current glucose: {current_glucose}\n"
            f"Please acknowledge this alert if you are okay."
        )

    if tier == EscalationTier.PRIMARY_CONTACT:
        return (
            f"{safe_email} has a glucose emergency and has not responded.\n"
            f"Alert: {safe_message}\n"
            f"Current glucose: {current_glucose}\n"
            f"Severity: {alert.severity.value.upper()}\n"
            f"Please check on them immediately."
        )

    # ALL_CONTACTS
    return (
        f"{safe_email} has a glucose emergency and has not responded.\n"
        f"Alert: {safe_message}\n"
        f"Current glucose: {current_glucose}\n"
        f"Severity: {alert.severity.value.upper()}\n"
        f"Primary contact has not responded. Please check on them immediately."
    )


async def _resolve_contact_chat_id(
    db: AsyncSession,
    telegram_username: str,
) -> int | None:
    """Resolve a Telegram username to a chat_id via TelegramLink.

    Strips leading ``@`` if present for matching against the
    TelegramLink.username field (stored without ``@``).

    Args:
        db: Database session.
        telegram_username: Contact's Telegram username.

    Returns:
        The chat_id if found, or None.
    """
    clean_username = telegram_username.lstrip("@").lower()
    if not clean_username:
        return None

    result = await db.execute(
        select(TelegramLink.chat_id).where(
            func.lower(TelegramLink.username) == clean_username,
            TelegramLink.is_verified.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def dispatch_notification(
    db: AsyncSession,
    tier: EscalationTier,
    message: str,
    contacts: list[EmergencyContact],
) -> NotificationStatus:
    """Dispatch notification to contacts via Telegram.

    For REMINDER tier, the user's own Telegram is handled by Path A
    (Story 7.2 immediate alert delivery in predictive_alerts).
    For contact tiers, resolves each contact's Telegram username to
    a chat_id via TelegramLink and sends the message.

    Args:
        db: Database session.
        tier: Escalation tier.
        message: Message content (HTML formatted).
        contacts: Contacts to notify.

    Returns:
        NotificationStatus indicating success/failure.
    """
    if tier == EscalationTier.REMINDER:
        logger.info(
            "Escalation reminder dispatched (user notification)",
            tier=tier.value,
        )
        return NotificationStatus.SENT

    if not contacts:
        logger.warning(
            "No contacts to notify for escalation",
            tier=tier.value,
        )
        return NotificationStatus.FAILED

    success_count = 0
    for contact in contacts:
        if not contact.telegram_username:
            logger.warning(
                "Contact has no Telegram username, skipping",
                contact_name=contact.name,
                tier=tier.value,
            )
            continue

        chat_id = await _resolve_contact_chat_id(db, contact.telegram_username)
        if chat_id is None:
            logger.warning(
                "Contact not linked to Telegram bot, skipping",
                contact_name=contact.name,
                telegram_username=contact.telegram_username,
                tier=tier.value,
            )
            continue

        try:
            await send_message(chat_id, message)
            success_count += 1
            logger.info(
                "Escalation notification sent to contact",
                tier=tier.value,
                contact_name=contact.name,
                chat_id=chat_id,
            )
        except TelegramBotError:
            logger.warning(
                "Failed to send escalation to contact",
                contact_name=contact.name,
                chat_id=chat_id,
                tier=tier.value,
                exc_info=True,
            )

    return NotificationStatus.SENT if success_count > 0 else NotificationStatus.FAILED


async def create_escalation_event(
    db: AsyncSession,
    alert: Alert,
    tier: EscalationTier,
    message: str,
    contacts: list[EmergencyContact],
    status: NotificationStatus,
) -> EscalationEvent | None:
    """Create an escalation event record.

    Args:
        db: Database session.
        alert: The alert being escalated.
        tier: Escalation tier.
        message: Message content sent.
        contacts: Contacts notified.
        status: Notification delivery status.

    Returns:
        Created EscalationEvent or None if duplicate (race condition).
    """
    now = datetime.now(UTC)
    event = EscalationEvent(
        alert_id=alert.id,
        user_id=alert.user_id,
        tier=tier,
        triggered_at=now,
        message_content=message,
        notification_status=status,
        contacts_notified=[str(c.id) for c in contacts],
        created_at=now,
    )

    db.add(event)

    try:
        await db.commit()
        await db.refresh(event)
        return event
    except IntegrityError:
        # Unique constraint violation: another process already escalated this tier
        await db.rollback()
        logger.debug(
            "Escalation event already exists (race condition)",
            alert_id=str(alert.id),
            tier=tier.value,
        )
        return None


async def escalate_alert(
    db: AsyncSession,
    alert: Alert,
    user_email: str,
    unit: GlucoseUnit = GlucoseUnit.MGDL,
) -> EscalationEvent | None:
    """Escalate an alert to the next tier if appropriate.

    Args:
        db: Database session.
        alert: The alert to potentially escalate.
        user_email: User's email (for message formatting).
        unit: The PATIENT's glucose display unit; escalation messages (to the
            patient and to emergency contacts) render glucose in it.

    Returns:
        EscalationEvent if escalation occurred, None otherwise.
    """
    config = await get_or_create_config(alert.user_id, db)
    existing_events = await get_escalation_events_for_alert(db, alert.id)
    decision = determine_next_escalation_tier(alert, config, existing_events)

    if not decision.should_escalate:
        logger.debug(
            "No escalation needed",
            alert_id=str(alert.id),
            reason=decision.reason,
        )
        return None

    tier = decision.tier
    logger.info(
        "Escalating alert",
        alert_id=str(alert.id),
        tier=tier.value,
        reason=decision.reason,
    )

    contacts = await get_contacts_for_tier(db, alert.user_id, tier)

    # Use HTML-formatted messages for contact tiers (sent via Telegram)
    if tier in (EscalationTier.PRIMARY_CONTACT, EscalationTier.ALL_CONTACTS):
        from src.services.alert_notifier import format_escalation_contact_message

        tier_label = (
            "Primary Contact Alert"
            if tier == EscalationTier.PRIMARY_CONTACT
            else "All Contacts Alert"
        )
        message = format_escalation_contact_message(alert, user_email, tier_label, unit)
    else:
        message = build_escalation_message(alert, tier, user_email, unit)

    # Persist event as PENDING first to ensure audit trail exists
    # before dispatching notification
    event = await create_escalation_event(
        db, alert, tier, message, contacts, NotificationStatus.PENDING
    )

    if event is None:
        # Duplicate — another process already handled this tier
        return None

    # Dispatch notification, then update status
    status = await dispatch_notification(db, tier, message, contacts)
    event.notification_status = status
    await db.commit()
    await db.refresh(event)

    logger.info(
        "Escalation event completed",
        event_id=str(event.id),
        tier=tier.value,
        contacts_count=len(contacts),
        status=status.value,
    )

    return event


async def process_escalations_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    user_email: str,
) -> int:
    """Process all eligible escalations for a single user.

    Args:
        db: Database session.
        user_id: User's UUID.
        user_email: User's email.

    Returns:
        Number of escalations triggered.
    """
    alerts = await get_unacknowledged_critical_alerts(db, user_id)

    if not alerts:
        return 0

    # Resolve the patient's display unit once; escalation messages -- to the
    # patient and to emergency contacts -- render glucose in the patient's unit.
    unit = await resolve_glucose_unit(db, user_id)

    escalation_count = 0
    for alert in alerts:
        event = await escalate_alert(db, alert, user_email, unit)
        if event:
            escalation_count += 1

    return escalation_count
