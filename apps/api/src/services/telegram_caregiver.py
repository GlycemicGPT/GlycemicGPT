"""Stories 7.6 & 8.3: Caregiver Telegram access with permission enforcement.

Handles Telegram commands from CAREGIVER-role users,
scoping all data access to their linked patients.
Permission checks (Story 8.3) filter data based on per-caregiver
flags set by the patient in the web app.

Supported interactions:
  /status      - Check linked patient's current glucose (requires can_view_glucose)
  /help        - List available caregiver commands
  Plain text   - AI chat about patient's glucose data (requires can_view_ai_suggestions)

Blocked commands (read-only access):
  /acknowledge - Patient-only
  /brief       - Patient-only
"""

import html
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.units import GlucoseUnit, format_glucose
from src.logging_config import get_logger
from src.models.caregiver_link import CaregiverLink

logger = get_logger(__name__)

# Commands that modify state — blocked for caregivers
_BLOCKED_COMMANDS = frozenset({"/acknowledge", "/brief"})


async def get_linked_patients(
    db: AsyncSession,
    caregiver_id: uuid.UUID,
) -> list[CaregiverLink]:
    """Return all CaregiverLink rows for this caregiver.

    Eagerly loads the patient relationship for email access.

    Args:
        db: Database session.
        caregiver_id: Caregiver's user UUID.

    Returns:
        List of CaregiverLink objects (may be empty).
    """
    result = await db.execute(
        select(CaregiverLink)
        .where(CaregiverLink.caregiver_id == caregiver_id)
        .options(selectinload(CaregiverLink.patient))
    )
    return list(result.scalars().all())


async def _handle_caregiver_status(
    db: AsyncSession,
    caregiver_id: uuid.UUID,
    links: list[CaregiverLink],
) -> str:
    """Build glucose status for the caregiver's linked patient(s).

    Checks `can_view_glucose` permission for each patient. If denied,
    shows a "permission not granted" message instead of glucose data.

    If the caregiver has a single patient and permission is granted,
    shows that patient's full glucose status. If multiple patients,
    shows a brief summary for each.
    """
    from src.services.caregiver import check_caregiver_permission

    if len(links) == 1:
        patient = links[0].patient
        patient_label = html.escape(patient.email)

        can_view = await check_caregiver_permission(
            db, caregiver_id, links[0].patient_id, "can_view_glucose"
        )
        if not can_view:
            return (
                f"\U0001f465 <b>Patient:</b> {patient_label}\n\n"
                "\U0001f512 Glucose data not available (permission not granted)"
            )

        # Lazy import to avoid circular dependency
        from src.services.telegram_commands import _handle_status

        status = await _handle_status(db, links[0].patient_id)
        return f"\U0001f465 <b>Patient:</b> {patient_label}\n\n{status}"

    # Multiple patients — brief status for each
    from src.services.alert_notifier import trend_description
    from src.services.dexcom_sync import get_latest_glucose_reading

    lines = ["\U0001f465 <b>Linked Patients</b>", ""]

    for link in links:
        patient = link.patient
        patient_label = html.escape(patient.email)

        can_view = await check_caregiver_permission(
            db, caregiver_id, link.patient_id, "can_view_glucose"
        )
        if not can_view:
            lines.append(
                f"\u2022 <b>{patient_label}:</b> \U0001f512 Permission not granted"
            )
            continue

        reading = await get_latest_glucose_reading(db, link.patient_id)

        if reading is None:
            lines.append(f"\u2022 <b>{patient_label}:</b> No data available")
        else:
            trend = trend_description(reading.trend_rate)
            # Each patient's glucose renders in that patient's own unit. The
            # column is non-nullable, but default to mg/dL defensively here
            # since this loop renders several patients in one message.
            unit = patient.glucose_unit or GlucoseUnit.MGDL
            glucose = format_glucose(reading.value, unit)
            lines.append(f"\u2022 <b>{patient_label}:</b> {glucose} ({trend})")

    return "\n".join(lines)


def _handle_caregiver_help() -> str:
    """Return caregiver-specific help text."""
    return (
        "\U0001f4cb <b>Caregiver Commands</b>\n"
        "\n"
        "/status \u2013 Check your patient's glucose\n"
        "/help \u2013 Show this help message\n"
        "\n"
        "\U0001f4ac Or type a question about your patient's glucose data.\n"
        "\n"
        "\u2139\ufe0f /acknowledge and /brief are not available "
        "for caregiver accounts."
    )


def _handle_blocked_command() -> str:
    """Return message for commands blocked for caregivers."""
    return (
        "\u26d4 This command is only available for patient accounts.\n"
        "As a caregiver, you can use /status or ask questions in plain text."
    )


def _handle_no_patients() -> str:
    """Return message when caregiver has no linked patients."""
    return (
        "\u2139\ufe0f No patients linked to your account.\n"
        "Ask your patient to link you as a caregiver in the "
        "GlycemicGPT web app."
    )


def _resolve_patient_for_chat(
    links: list[CaregiverLink],
    text: str,
) -> CaregiverLink | None:
    """Resolve which patient a caregiver chat message is about.

    If single patient, returns that link. If multiple, attempts
    to match patient email from the message text.

    Args:
        links: Caregiver's patient links.
        text: The user's message text.

    Returns:
        The matching CaregiverLink, or None if ambiguous.
    """
    if len(links) == 1:
        return links[0]

    # Try name matching against patient emails
    lower_text = text.lower()
    for link in links:
        email_prefix = link.patient.email.split("@")[0].lower()
        if email_prefix in lower_text:
            return link

    return None


async def _handle_caregiver_chat(
    db: AsyncSession,
    caregiver_id: uuid.UUID,
    links: list[CaregiverLink],
    text: str,
) -> str:
    """Route a caregiver's natural language message to AI chat.

    Checks `can_view_ai_suggestions` permission before allowing AI chat.
    Resolves the target patient and delegates to handle_caregiver_chat
    in telegram_chat.py.
    """
    link = _resolve_patient_for_chat(links, text)

    if link is None:
        # Multiple patients, couldn't resolve — list them
        patient_list = ", ".join(
            html.escape(link_item.patient.email) for link_item in links
        )
        return (
            "\u2139\ufe0f You have multiple linked patients. "
            "Please mention their name in your message.\n"
            f"Linked patients: {patient_list}"
        )

    # Check AI suggestion permission (Story 8.3)
    from src.services.caregiver import check_caregiver_permission

    can_use_ai = await check_caregiver_permission(
        db, caregiver_id, link.patient_id, "can_view_ai_suggestions"
    )
    if not can_use_ai:
        return "\U0001f512 AI chat is not enabled for this patient."

    try:
        from src.services.telegram_chat import handle_caregiver_chat
    except ImportError:
        logger.error("Failed to import telegram_chat module", exc_info=True)
        return (
            "\u26a0\ufe0f AI chat is temporarily unavailable. Please try again later."
        )

    return await handle_caregiver_chat(db, caregiver_id, link.patient_id, text)


async def handle_caregiver_command(
    db: AsyncSession,
    caregiver_id: uuid.UUID,
    text: str,
) -> str:
    """Route a caregiver's Telegram message to the appropriate handler.

    Always returns a response string. Exceptions are caught and
    converted to user-friendly error messages.

    Args:
        db: Database session.
        caregiver_id: Caregiver's user UUID.
        text: Raw message text.

    Returns:
        HTML-formatted response string.
    """
    try:
        return await _route_caregiver_command(db, caregiver_id, text)
    except Exception:
        logger.error(
            "Unexpected error in caregiver command handler",
            caregiver_id=str(caregiver_id),
            exc_info=True,
        )
        return "\u26a0\ufe0f Something went wrong. Please try again later."


async def _route_caregiver_command(
    db: AsyncSession,
    caregiver_id: uuid.UUID,
    text: str,
) -> str:
    """Internal caregiver command router (may raise)."""
    stripped = text.strip()
    lower = stripped.lower()

    # Check for blocked commands
    if lower in _BLOCKED_COMMANDS or lower.startswith("/acknowledge_"):
        return _handle_blocked_command()

    # Help doesn't need DB access
    if lower == "/help":
        return _handle_caregiver_help()

    # Get linked patients (needed for remaining handlers)
    links = await get_linked_patients(db, caregiver_id)

    if lower == "/status":
        if not links:
            return _handle_no_patients()
        return await _handle_caregiver_status(db, caregiver_id, links)

    # Unknown /commands
    if stripped.startswith("/"):
        return (
            "\u2753 Unrecognized command.\n"
            "Send /help to see available caregiver commands."
        )

    # Plain text — AI chat
    if not links:
        return _handle_no_patients()
    return await _handle_caregiver_chat(db, caregiver_id, links, stripped)
