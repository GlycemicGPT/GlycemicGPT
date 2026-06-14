"""Story 5.6: Pre-validation safety layer service.

Validates AI-generated suggestions against safety bounds before
they are shown to users. Detects dangerous content and ensures
ratio/factor changes stay within ±20% limits.
"""

import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.logging_config import get_logger
from src.models.safety_log import SafetyLog
from src.schemas.safety_validation import (
    FlaggedSuggestion,
    SafetyStatus,
    SuggestionType,
    ValidationResult,
)

logger = get_logger(__name__)

# Maximum allowed percentage change for any single suggestion
MAX_CHANGE_PCT = 20.0

# Safety disclaimer that must appear in validated output
SAFETY_DISCLAIMER = (
    "\n\n---\n"
    "**Safety Notice:** These are AI-generated observations, not medical advice. "
    "Always discuss changes with your endocrinologist before adjusting pump settings."
)

# Prescriptive action verbs that, near a specific insulin quantity, indicate a
# dosing instruction. Deliberately excludes the NOUNS "bolus"/"dose" (which
# appear in descriptive/historical text like "your bolus was 6 units" or "your
# total daily dose is 24 units"); the imperative "bolus N units" stays covered
# by the tight pattern below.
_PRESCRIPTIVE_DOSE_VERB = (
    r"(?:take|taking|add|adding|give|giving|inject\w*|administer\w*|"
    r"increas\w*|decreas\w*|rais\w*|lower\w*|bump\w*|boost\w*|reduc\w*|"
    r"suggest\w*|recommend\w*|try|trying|need\w*|adjust\w*)"
)

# Dangerous keywords/phrases that indicate unsafe content
DANGEROUS_PATTERNS = [
    r"(?i)\bdouble\s+(?:your|the)\s+(?:dose|insulin|bolus)",
    r"(?i)\bhalf\s+(?:your|the)\s+(?:dose|insulin|bolus)",
    r"(?i)\bstop\s+(?:taking|your)\s+(?:insulin|medication)",
    r"(?i)\bskip\s+(?:your|the)\s+(?:dose|insulin|bolus|medication)",
    r"(?i)\bincrease.*\b(?:by|to)\s+(?:200|300|400|500)\s*%",
    r"(?i)\btriple\s+(?:your|the)\s+(?:dose|insulin|bolus)",
    r"(?i)\bimmediately\s+(?:change|adjust|modify)\s+(?:your|the|all)",
    r"(?i)\bdiscontinue\s+(?:your\s+|the\s+)?(?:insulin|medication)",
    r"(?i)\b(?:take|bolus|inject|give)\s+\d+\s*(?:units?|u)\b",
    # Verb-independent specific dose: a prescriptive verb (with optional words
    # between it and the quantity) followed by "N units" -- catches "add 2
    # units", "I suggest 5 units", "increase the bolus to 12 units".
    r"(?i)\b" + _PRESCRIPTIVE_DOSE_VERB + r"\b[^.\n]{0,25}?\b"
    r"\d+(?:\.\d+)?\s*(?:units?|u|iu)\b",
    # Spelled-out quantity after a prescriptive verb -- "take six units".
    r"(?i)\b" + _PRESCRIPTIVE_DOSE_VERB + r"\b[^.\n]{0,25}?\b"
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten)\s+units?\b",
    # Quantity introduced by should/could/would-be/by/extra/another/additional
    # -- "correction should be 3 units", "an extra 2 units".
    r"(?i)\b(?:should|could|would|by|extra|another|additional)\s+(?:be\s+)?"
    r"\d+(?:\.\d+)?\s*(?:units?|u|iu)\b",
]

# Pattern to extract carb ratio suggestions like "1:8 to 1:7" or "from 1:10 to 1:8"
# Negative lookahead excludes matches followed by mg/dL (those are ISF values)
# (?!\d) prevents backtracking from consuming fewer digits to bypass the lookahead
CARB_RATIO_PATTERN = re.compile(
    r"(?:from\s+)?1\s*:\s*(\d+(?:\.\d+)?)\s+"
    r"(?:to|→|->)\s+"
    r"1\s*:\s*(\d+(?:\.\d+)?)"
    r"(?!\d|\s*(?:mg/dL|mg\b))",
    re.IGNORECASE,
)

# Pattern to extract ISF suggestions with 1:X notation requiring mg/dL suffix
# e.g., "from 1:50 to 1:45 mg/dL" — the mg/dL suffix distinguishes ISF from carb ratios
ISF_PATTERN = re.compile(
    r"(?:from\s+)?1\s*:\s*(\d+(?:\.\d+)?)\s+"
    r"(?:to|→|->)\s+"
    r"(?:1\s*:\s*)?(\d+(?:\.\d+)?)"
    r"\s*(?:mg/dL|mg)",
    re.IGNORECASE,
)

# ISF pattern with context keywords (does not require 1: prefix)
# e.g., "correction factor from 50 to 45 mg/dL" or "ISF should be 50 to 45 mg/dL"
ISF_CONTEXT_PATTERN = re.compile(
    r"(?:ISF|correction\s+factor|sensitivity\s+factor|CF)"
    r".*?(?:from\s+)?(\d+(?:\.\d+)?)\s+"
    r"(?:to|→|->)\s+"
    r"(\d+(?:\.\d+)?)"
    r"\s*(?:mg/dL|mg)",
    re.IGNORECASE,
)


def _check_dangerous_content(text: str) -> bool:
    """Check if AI output contains dangerous content.

    Args:
        text: The AI-generated text to check.

    Returns:
        True if dangerous content was detected.
    """
    return any(re.search(pattern, text) for pattern in DANGEROUS_PATTERNS)


def _extract_carb_ratio_changes(text: str) -> list[FlaggedSuggestion]:
    """Extract and validate carb ratio change suggestions.

    Looks for patterns like "1:8 to 1:7" in the AI text
    and checks if the change exceeds ±20%.

    Args:
        text: The AI-generated text.

    Returns:
        List of flagged suggestions that exceed bounds.
    """
    flagged = []
    for match in CARB_RATIO_PATTERN.finditer(text):
        original = float(match.group(1))
        suggested = float(match.group(2))

        if original == 0:
            continue

        # For carb ratios (1:X), a smaller X = stronger ratio = more insulin
        change_pct = abs((suggested - original) / original) * 100

        if change_pct > MAX_CHANGE_PCT:
            flagged.append(
                FlaggedSuggestion(
                    suggestion_type=SuggestionType.CARB_RATIO,
                    original_value=original,
                    suggested_value=suggested,
                    change_pct=round(change_pct, 1),
                    max_allowed_pct=MAX_CHANGE_PCT,
                    reason=(
                        f"Carb ratio change of {change_pct:.0f}% "
                        f"(1:{original} to 1:{suggested}) exceeds "
                        f"maximum allowed change of {MAX_CHANGE_PCT:.0f}%"
                    ),
                )
            )
    return flagged


def _extract_isf_changes(text: str) -> list[FlaggedSuggestion]:
    """Extract and validate ISF/correction factor change suggestions.

    Looks for patterns like "1:50 to 1:45" or "correction factor from 50 to 45 mg/dL"
    in the AI text and checks if the change exceeds ±20%.

    Requires either a 1: prefix (ISF_PATTERN) or a context keyword like
    "ISF", "correction factor", or "sensitivity factor" (ISF_CONTEXT_PATTERN)
    to avoid false positives from glucose reading text.

    Args:
        text: The AI-generated text.

    Returns:
        List of flagged suggestions that exceed bounds.
    """
    flagged = []
    seen: set[tuple[float, float]] = set()

    for pattern in (ISF_PATTERN, ISF_CONTEXT_PATTERN):
        for match in pattern.finditer(text):
            original = float(match.group(1))
            suggested = float(match.group(2))

            if original == 0:
                continue

            # Deduplicate matches found by both patterns
            key = (original, suggested)
            if key in seen:
                continue
            seen.add(key)

            change_pct = abs((suggested - original) / original) * 100

            if change_pct > MAX_CHANGE_PCT:
                flagged.append(
                    FlaggedSuggestion(
                        suggestion_type=SuggestionType.CORRECTION_FACTOR,
                        original_value=original,
                        suggested_value=suggested,
                        change_pct=round(change_pct, 1),
                        max_allowed_pct=MAX_CHANGE_PCT,
                        reason=(
                            f"Correction factor change of {change_pct:.0f}% "
                            f"({original} to {suggested} mg/dL) exceeds "
                            f"maximum allowed change of {MAX_CHANGE_PCT:.0f}%"
                        ),
                    )
                )
    return flagged


def validate_ai_suggestion(
    ai_text: str,
    suggestion_type: str,
) -> ValidationResult:
    """Validate an AI-generated suggestion against safety bounds.

    Checks for:
    1. Dangerous content (e.g., "double your dose")
    2. Carb ratio changes exceeding ±20%
    3. Correction factor changes exceeding ±20%

    Args:
        ai_text: The AI-generated analysis text.
        suggestion_type: Type of analysis ("meal_analysis" or "correction_analysis").

    Returns:
        ValidationResult with status and any flagged items.
    """
    has_dangerous = _check_dangerous_content(ai_text)
    flagged_items: list[FlaggedSuggestion] = []

    # Check both ratio and factor changes regardless of type
    # (AI might mention both in any analysis)
    flagged_items.extend(_extract_carb_ratio_changes(ai_text))
    flagged_items.extend(_extract_isf_changes(ai_text))

    # Determine status
    if has_dangerous:
        status = SafetyStatus.REJECTED
    elif flagged_items:
        status = SafetyStatus.FLAGGED
    else:
        status = SafetyStatus.APPROVED

    # Build sanitized text
    sanitized = ai_text
    if has_dangerous:
        sanitized = (
            "**This suggestion has been blocked by the safety system due to "
            "potentially dangerous content. Please consult your healthcare "
            "provider directly for guidance.**"
        )
    elif flagged_items:
        warnings = []
        for item in flagged_items:
            warnings.append(f"- {item.reason}")
        warning_block = (
            "\n\n**Safety Warning:** The following suggestions exceed "
            "recommended change limits:\n" + "\n".join(warnings) + "\n"
            "Discuss these with your endocrinologist before making changes."
        )
        sanitized = ai_text + warning_block

    # Always append safety disclaimer
    sanitized += SAFETY_DISCLAIMER

    return ValidationResult(
        status=status,
        flagged_items=flagged_items,
        original_text=ai_text,
        sanitized_text=sanitized,
        has_dangerous_content=has_dangerous,
    )


async def log_safety_validation(
    user_id: "str | object",
    analysis_type: str,
    analysis_id: "str | object",
    result: ValidationResult,
    db: AsyncSession,
) -> SafetyLog:
    """Log a safety validation decision for audit.

    Args:
        user_id: User's UUID.
        analysis_type: Type of analysis validated.
        analysis_id: ID of the analysis that was validated.
        result: The validation result.
        db: Database session.

    Returns:
        The created SafetyLog record.
    """
    log_entry = SafetyLog(
        user_id=user_id,
        analysis_type=analysis_type,
        analysis_id=analysis_id,
        status=result.status.value,
        flagged_items=[item.model_dump() for item in result.flagged_items],
        has_dangerous_content=result.has_dangerous_content,
    )

    db.add(log_entry)

    logger.info(
        "Safety validation logged",
        user_id=str(user_id),
        analysis_type=analysis_type,
        analysis_id=str(analysis_id),
        status=result.status.value,
        flagged_count=len(result.flagged_items),
        dangerous=result.has_dangerous_content,
    )

    return log_entry


async def list_safety_logs(
    user_id: "str | object",
    db: AsyncSession,
    limit: int = 10,
    offset: int = 0,
) -> tuple[list[SafetyLog], int]:
    """List safety validation logs for a user.

    Args:
        user_id: User's UUID.
        db: Database session.
        limit: Maximum number of logs to return.
        offset: Number of logs to skip.

    Returns:
        Tuple of (logs list, total count).
    """
    count_result = await db.execute(
        select(func.count()).where(SafetyLog.user_id == user_id)
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(SafetyLog)
        .where(SafetyLog.user_id == user_id)
        .order_by(SafetyLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    logs = list(result.scalars().all())

    return logs, total
