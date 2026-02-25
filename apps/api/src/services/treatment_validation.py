"""Treatment validation service.

Orchestrates the TreatmentSafetyValidator and persists audit logs.
Uses a per-user advisory lock to prevent concurrent validation
races (TOCTOU) for the same user.
"""

import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.treatment_safety.models import BolusRequest, BolusValidationResult
from src.core.treatment_safety.validator import TreatmentSafetyValidator
from src.logging_config import get_logger
from src.models.bolus_validation_log import BolusValidationLog
from src.services.safety_limits import get_or_create_safety_limits

logger = get_logger(__name__)

_validator = TreatmentSafetyValidator()

# Advisory lock namespace to avoid collisions with other lock users.
_BOLUS_VALIDATION_LOCK_NS = 0x424F4C55  # "BOLU" as int32


def _user_lock_key(user_id: uuid.UUID) -> int:
    """Derive a stable int32 lock key from a user UUID."""
    return int(user_id.int % (2**31))


async def validate_bolus(
    user_id: uuid.UUID,
    requested_dose_milliunits: int,
    glucose_at_request_mgdl: int,
    timestamp: datetime,
    source: str,
    user_confirmed: bool,
    db: AsyncSession,
) -> tuple[BolusValidationLog, BolusValidationResult]:
    """Validate a bolus request and persist the audit log.

    Acquires a per-user advisory lock to prevent concurrent
    validation races (two requests both passing daily-total or
    rate-limit checks simultaneously).

    The caller is responsible for committing the session after
    this function returns.  This allows the router to control
    the transaction boundary.

    Args:
        user_id: Requesting user's ID.
        requested_dose_milliunits: Dose in milliunits.
        glucose_at_request_mgdl: CGM glucose at request time.
        timestamp: Client-reported request time (audit only).
        source: BolusSource enum value.
        user_confirmed: Whether user explicitly confirmed.
        db: Database session.

    Returns:
        Tuple of (BolusValidationLog, BolusValidationResult).
    """
    # Fetch (or create) safety limits BEFORE acquiring the advisory
    # lock.  get_or_create_safety_limits may commit/rollback on first
    # use, which would release a transaction-level advisory lock.
    safety_limits = await get_or_create_safety_limits(user_id, db)

    # Acquire a per-user advisory lock for the duration of this
    # transaction.  pg_advisory_xact_lock is released automatically
    # when the transaction commits or rolls back.
    lock_key = _user_lock_key(user_id)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :key)"),
        {"ns": _BOLUS_VALIDATION_LOCK_NS, "key": lock_key},
    )

    request = BolusRequest(
        user_id=user_id,
        requested_dose_milliunits=requested_dose_milliunits,
        glucose_at_request_mgdl=glucose_at_request_mgdl,
        timestamp=timestamp,
        source=source,
        user_confirmed=user_confirmed,
    )

    result = await _validator.validate_bolus_request(
        request, db, safety_limits=safety_limits
    )

    log_entry = BolusValidationLog(
        user_id=user_id,
        requested_dose_milliunits=requested_dose_milliunits,
        glucose_at_request_mgdl=glucose_at_request_mgdl,
        source=source,
        user_confirmed=user_confirmed,
        approved=result.approved,
        validated_dose_milliunits=result.validated_dose_milliunits,
        check_results=[
            cr.model_dump(mode="json") for cr in result.safety_check_results
        ],
        rejection_reasons=result.rejection_reasons,
        request_timestamp=timestamp,
    )
    db.add(log_entry)
    # Flush (not commit) so the log entry gets an ID, but leave
    # the transaction open for the caller to commit atomically.
    await db.flush()

    logger.info(
        "Bolus validation completed",
        user_id=str(user_id),
        approved=result.approved,
        dose_milliunits=requested_dose_milliunits,
        source=source,
        validation_id=str(log_entry.id),
    )

    return log_entry, result
