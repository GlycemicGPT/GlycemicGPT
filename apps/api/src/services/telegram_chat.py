"""Stories 7.5, 7.6, & 15.7: AI chat via Telegram and web.

Handles natural language messages from Telegram/web by routing them
to the user's configured AI provider with comprehensive diabetes context.
Each message is a standalone Q&A (no conversation history).

Story 7.6 adds caregiver chat: uses the patient's AI provider and
glucose context with a caregiver-specific system prompt.

Story 15.7: Expanded from glucose-only context to full diabetes context
including pump activity, Control-IQ summary, and user settings.

Story 35.1: Context builders extracted to diabetes_context.py shared module.
"""

import html
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.logging_config import get_logger
from src.models.user import User
from src.schemas.ai_response import AIMessage
from src.services.ai_client import get_ai_client
from src.services.diabetes_context import build_diabetes_context

logger = get_logger(__name__)

# Telegram message length limit
TELEGRAM_MAX_LENGTH = 4096

# Safety disclaimer appended to every AI response
SAFETY_DISCLAIMER = (
    "\n\n\u26a0\ufe0f <i>Not medical advice. Consult your healthcare provider.</i>"
)

# Token limits for AI responses
TELEGRAM_MAX_RESPONSE_TOKENS = 800
WEB_MAX_RESPONSE_TOKENS = 1200

_SYSTEM_PROMPT_PREFIX = """\
You are a supportive diabetes management assistant integrated with GlycemicGPT. \
You help users understand their glucose patterns, discuss insulin management, \
and answer questions about their diabetes care.

Guidelines:
- Be concise (this is a Telegram chat, keep responses under 300 words)
- Be supportive and non-judgmental
- Reference the user's glucose data, pump activity, and Control-IQ behavior when relevant
- You MAY discuss patterns in basal rates, correction frequency, and timing
- You MAY note when Control-IQ is making frequent corrections (suggests settings may need review)
- Do NOT prescribe specific insulin dose numbers
- Frame observations as things to discuss with their endocrinologist
- Use plain text, avoid markdown (Telegram uses HTML)

"""

# Maximum characters we accept from user input before truncating
MAX_USER_MESSAGE_LENGTH = 2000


def _build_system_prompt(diabetes_context: str) -> str:
    """Build the system prompt with diabetes context embedded.

    Uses string concatenation instead of str.format() to avoid
    injection if the context contains brace characters.

    Args:
        diabetes_context: Formatted diabetes data string.

    Returns:
        Complete system prompt for the AI provider.
    """
    if diabetes_context:
        return _SYSTEM_PROMPT_PREFIX + diabetes_context
    return _SYSTEM_PROMPT_PREFIX.rstrip()


def _truncate_response(text: str) -> str:
    """Truncate text to fit within Telegram's message length limit.

    Reserves space for the safety disclaimer. If the response
    exceeds the limit, it is truncated with an ellipsis.

    Args:
        text: The full response text (before disclaimer).

    Returns:
        Text truncated to fit within TELEGRAM_MAX_LENGTH with disclaimer.
    """
    max_content_length = TELEGRAM_MAX_LENGTH - len(SAFETY_DISCLAIMER)
    if len(text) <= max_content_length:
        return text + SAFETY_DISCLAIMER
    return text[: max_content_length - 3] + "..." + SAFETY_DISCLAIMER


async def handle_chat(
    db: AsyncSession,
    user_id: uuid.UUID,
    text: str,
) -> str:
    """Process a natural language message through the user's AI provider.

    Fetches comprehensive diabetes context (glucose, pump, Control-IQ,
    settings), builds a system prompt, and generates a response using
    the user's configured AI provider. Always appends a safety disclaimer.

    Args:
        db: Database session.
        user_id: User's UUID.
        text: The user's message text.

    Returns:
        HTML-formatted response string with safety disclaimer.
    """
    # Fetch User object (needed for get_ai_client)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        logger.error("User not found for AI chat", user_id=str(user_id))
        return "\u26a0\ufe0f Something went wrong. Please try again later."

    # Get the user's AI client
    try:
        ai_client = await get_ai_client(user, db)
    except HTTPException as exc:
        if exc.status_code == 404:
            return (
                "\u2139\ufe0f No AI provider configured.\n"
                "Set up your AI provider in the GlycemicGPT web app "
                "under Settings to use AI chat."
            )
        logger.error(
            "AI provider configuration error",
            user_id=str(user_id),
            detail=exc.detail,
        )
        return (
            "\u26a0\ufe0f There is an issue with your AI provider configuration. "
            "Please check Settings or try again later."
        )

    # Truncate overly long user messages to limit token usage
    truncated_text = text[:MAX_USER_MESSAGE_LENGTH]

    # Build context and prompt
    try:
        diabetes_context = await build_diabetes_context(db, user_id)
    except Exception:
        logger.error(
            "Failed to build diabetes context for AI chat",
            user_id=str(user_id),
            exc_info=True,
        )
        diabetes_context = "Recent diabetes data: unavailable due to a temporary error."
    system_prompt = _build_system_prompt(diabetes_context)

    # Generate AI response
    try:
        ai_response = await ai_client.generate(
            messages=[AIMessage(role="user", content=truncated_text)],
            system_prompt=system_prompt,
            max_tokens=TELEGRAM_MAX_RESPONSE_TOKENS,
        )
    except Exception:
        logger.error(
            "AI provider error in Telegram chat",
            user_id=str(user_id),
            exc_info=True,
        )
        return (
            "\u26a0\ufe0f Unable to get a response from the AI provider. "
            "Please check your API key in Settings or try again later."
        )

    content = ai_response.content.strip()
    if not content:
        return (
            "\u2139\ufe0f The AI returned an empty response. "
            "Please try rephrasing your question." + SAFETY_DISCLAIMER
        )

    # Escape any HTML in the AI response to prevent injection
    safe_content = html.escape(content)

    logger.info(
        "Telegram AI chat response generated",
        user_id=str(user_id),
        model=ai_response.model,
        provider=ai_response.provider.value,
        input_tokens=ai_response.usage.input_tokens,
        output_tokens=ai_response.usage.output_tokens,
    )

    return _truncate_response(safe_content)


# ── Story 11.2: Web-optimized user AI chat ──

_WEB_SYSTEM_PROMPT_PREFIX = """\
You are a supportive diabetes management assistant integrated with GlycemicGPT. \
You help users understand their glucose patterns, discuss insulin management, \
and answer questions about their diabetes care.

Guidelines:
- Be supportive and non-judgmental
- Reference the user's glucose data, pump activity, and Control-IQ behavior when relevant
- You MAY discuss patterns in basal rates, correction frequency, and timing
- You MAY note when Control-IQ is making frequent corrections (suggests settings may need review)
- Do NOT prescribe specific insulin dose numbers
- Frame observations as things to discuss with their endocrinologist
- You may use markdown formatting for readability

"""


async def handle_chat_web(
    db: AsyncSession,
    user_id: uuid.UUID,
    text: str,
) -> str:
    """Process a user's AI query for the web interface.

    Similar to handle_chat() but returns plain text without HTML
    escaping or Telegram-specific formatting, and raises HTTPException
    on errors instead of returning error strings.

    Args:
        db: Database session.
        user_id: User's UUID.
        text: The user's message text.

    Returns:
        Plain text AI response content.

    Raises:
        HTTPException: If user not found (404), no AI provider (404),
            or AI provider error (502).
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        ai_client = await get_ai_client(user, db)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail="No AI provider configured",
            ) from exc
        raise

    truncated_text = text[:MAX_USER_MESSAGE_LENGTH]

    try:
        diabetes_context = await build_diabetes_context(db, user_id)
    except Exception:
        logger.error(
            "Failed to build diabetes context for web chat",
            user_id=str(user_id),
            exc_info=True,
        )
        diabetes_context = "Recent diabetes data: unavailable due to a temporary error."

    if diabetes_context:
        system_prompt = _WEB_SYSTEM_PROMPT_PREFIX + diabetes_context
    else:
        system_prompt = _WEB_SYSTEM_PROMPT_PREFIX.rstrip()

    try:
        ai_response = await ai_client.generate(
            messages=[AIMessage(role="user", content=truncated_text)],
            system_prompt=system_prompt,
            max_tokens=WEB_MAX_RESPONSE_TOKENS,
        )
    except Exception:
        logger.error(
            "AI provider error in web chat",
            user_id=str(user_id),
            exc_info=True,
        )
        raise HTTPException(
            status_code=502,
            detail="Unable to get a response from the AI provider",
        )

    content = ai_response.content.strip()
    if not content:
        raise HTTPException(
            status_code=502,
            detail="The AI returned an empty response",
        )

    logger.info(
        "Web AI chat response generated",
        user_id=str(user_id),
        model=ai_response.model,
        provider=ai_response.provider.value,
        input_tokens=ai_response.usage.input_tokens,
        output_tokens=ai_response.usage.output_tokens,
    )

    return content


# ── Story 7.6: Caregiver AI chat ──

_CAREGIVER_SYSTEM_PROMPT_PREFIX = """\
You are a supportive diabetes management assistant integrated with GlycemicGPT. \
You are responding to a CAREGIVER who is checking on their patient's glucose data. \
Help them understand the patient's current status and patterns.

Guidelines:
- Be concise (this is a Telegram chat, keep responses under 300 words)
- Be supportive and reassuring
- Reference the patient's glucose data, pump activity, and Control-IQ behavior when relevant
- You MAY discuss patterns in basal rates, correction frequency, and timing
- Do NOT prescribe specific insulin dose numbers
- Suggest the patient discuss observations with their endocrinologist
- Use plain text, avoid markdown (Telegram uses HTML)

"""


def _build_caregiver_system_prompt(
    patient_email: str,
    diabetes_context: str,
) -> str:
    """Build a system prompt for caregiver AI chat.

    Includes patient identification and diabetes context.

    Args:
        patient_email: Patient's email for identification.
        diabetes_context: Formatted diabetes data string.

    Returns:
        Complete system prompt for the AI provider.
    """
    patient_line = f"Patient: {patient_email}\n"
    if diabetes_context:
        return _CAREGIVER_SYSTEM_PROMPT_PREFIX + patient_line + diabetes_context
    return (_CAREGIVER_SYSTEM_PROMPT_PREFIX + patient_line).rstrip()


async def handle_caregiver_chat(
    db: AsyncSession,
    caregiver_id: uuid.UUID,
    patient_id: uuid.UUID,
    text: str,
) -> str:
    """Process a caregiver's natural language message about a patient.

    Uses the PATIENT's AI provider config and diabetes context,
    but with a caregiver-specific system prompt.

    Args:
        db: Database session.
        caregiver_id: Caregiver's user UUID.
        patient_id: Patient's user UUID.
        text: The caregiver's message text.

    Returns:
        HTML-formatted response string with safety disclaimer.
    """
    # Fetch patient User object (needed for get_ai_client)
    result = await db.execute(select(User).where(User.id == patient_id))
    patient = result.scalar_one_or_none()

    if patient is None:
        logger.error(
            "Patient not found for caregiver AI chat",
            caregiver_id=str(caregiver_id),
            patient_id=str(patient_id),
        )
        return "\u26a0\ufe0f Something went wrong. Please try again later."

    # Use patient's AI client
    try:
        ai_client = await get_ai_client(patient, db)
    except HTTPException as exc:
        if exc.status_code == 404:
            return (
                "\u2139\ufe0f No AI provider configured for this patient.\n"
                "The patient needs to set up an AI provider in the "
                "GlycemicGPT web app under Settings."
            )
        logger.error(
            "AI provider configuration error for caregiver chat",
            caregiver_id=str(caregiver_id),
            patient_id=str(patient_id),
            detail=exc.detail,
        )
        return (
            "\u26a0\ufe0f There is an issue with the AI provider configuration. "
            "Please try again later."
        )

    # Truncate overly long user messages
    truncated_text = text[:MAX_USER_MESSAGE_LENGTH]

    # Build context from patient's data
    try:
        diabetes_context = await build_diabetes_context(db, patient_id)
    except Exception:
        logger.error(
            "Failed to build diabetes context for caregiver chat",
            caregiver_id=str(caregiver_id),
            patient_id=str(patient_id),
            exc_info=True,
        )
        diabetes_context = "Recent diabetes data: unavailable due to a temporary error."
    system_prompt = _build_caregiver_system_prompt(patient.email, diabetes_context)

    # Generate AI response
    try:
        ai_response = await ai_client.generate(
            messages=[AIMessage(role="user", content=truncated_text)],
            system_prompt=system_prompt,
            max_tokens=TELEGRAM_MAX_RESPONSE_TOKENS,
        )
    except Exception:
        logger.error(
            "AI provider error in caregiver Telegram chat",
            caregiver_id=str(caregiver_id),
            patient_id=str(patient_id),
            exc_info=True,
        )
        return (
            "\u26a0\ufe0f Unable to get a response from the AI provider. "
            "Please try again later."
        )

    content = ai_response.content.strip()
    if not content:
        return (
            "\u2139\ufe0f The AI returned an empty response. "
            "Please try rephrasing your question." + SAFETY_DISCLAIMER
        )

    safe_content = html.escape(content)

    logger.info(
        "Caregiver Telegram AI chat response generated",
        caregiver_id=str(caregiver_id),
        patient_id=str(patient_id),
        model=ai_response.model,
        provider=ai_response.provider.value,
        input_tokens=ai_response.usage.input_tokens,
        output_tokens=ai_response.usage.output_tokens,
    )

    return _truncate_response(safe_content)


# ── Story 8.4: Web-optimized caregiver AI chat ──


async def handle_caregiver_chat_web(
    db: AsyncSession,
    caregiver_id: uuid.UUID,
    patient_id: uuid.UUID,
    text: str,
) -> str:
    """Process a caregiver's AI query for the web interface.

    Similar to handle_caregiver_chat() but returns plain text
    without HTML escaping or Telegram-specific formatting.

    Args:
        db: Database session.
        caregiver_id: Caregiver's user UUID.
        patient_id: Patient's user UUID.
        text: The caregiver's message text.

    Returns:
        Plain text AI response content.

    Raises:
        HTTPException: If patient not found (404) or AI provider error (502).
    """
    result = await db.execute(select(User).where(User.id == patient_id))
    patient = result.scalar_one_or_none()

    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    try:
        ai_client = await get_ai_client(patient, db)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail="No AI provider configured for this patient",
            ) from exc
        raise

    truncated_text = text[:MAX_USER_MESSAGE_LENGTH]

    try:
        diabetes_context = await build_diabetes_context(db, patient_id)
    except Exception:
        logger.error(
            "Failed to build diabetes context for web caregiver chat",
            caregiver_id=str(caregiver_id),
            patient_id=str(patient_id),
            exc_info=True,
        )
        diabetes_context = "Recent diabetes data: unavailable due to a temporary error."

    system_prompt = _build_caregiver_system_prompt(patient.email, diabetes_context)

    try:
        ai_response = await ai_client.generate(
            messages=[AIMessage(role="user", content=truncated_text)],
            system_prompt=system_prompt,
            max_tokens=WEB_MAX_RESPONSE_TOKENS,
        )
    except Exception:
        logger.error(
            "AI provider error in web caregiver chat",
            caregiver_id=str(caregiver_id),
            patient_id=str(patient_id),
            exc_info=True,
        )
        raise HTTPException(
            status_code=502,
            detail="Unable to get a response from the AI provider",
        )

    content = ai_response.content.strip()
    if not content:
        raise HTTPException(
            status_code=502,
            detail="The AI returned an empty response",
        )

    logger.info(
        "Web caregiver AI chat response generated",
        caregiver_id=str(caregiver_id),
        patient_id=str(patient_id),
        model=ai_response.model,
        provider=ai_response.provider.value,
        input_tokens=ai_response.usage.input_tokens,
        output_tokens=ai_response.usage.output_tokens,
    )

    return content
