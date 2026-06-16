"""Persist and retrieve a meal estimate's audit/provenance trail (Story 50.H3).

Writes the ``food_record_audits`` row that makes an estimate answerable after the
fact: the raw per-sample vision outputs (50.H1), the empirical dispersion summary,
and the precedence decision + identity used (50.H2). The audit is written at
create time (vision-only outcome) and updated at identity-confirmation time (the
grounding decision).

Best-effort everywhere: a failed audit write must never break the estimate or the
confirmation -- the same posture as RAG indexing. Each call runs on its own
session (decoupled from the caller's transaction). Owner-scoped; nothing here is
read by dosing math, and sample content is never logged (only ids/counts).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session_maker
from src.logging_config import get_logger
from src.models.food_record_audit import FoodRecordAudit
from src.schemas.food_record import GroundingDetail
from src.services.meal_estimate_aggregate import AggregatedEstimate

logger = get_logger(__name__)

# The precedence ladder AS IT STOOD WHEN THE DECISION WAS MADE -- recorded per row
# (not just in code) so an audit reads the ordering that actually applied, even
# after 50.E2 reorders it (restaurant slots in above USDA). That decision-time
# fidelity is the point of storing it rather than referencing a live constant.
_PRECEDENCE_LADDER = [
    "own-history corrected",
    "USDA FoodData Central",
    "Open Food Facts",
    "own-history uncorrected",
    "vision-only",
]

_OUTCOME_GROUNDED = "grounded"
_OUTCOME_VISION_ONLY = "vision_only"


def _precedence(
    outcome: str,
    *,
    identity_confirmed: bool,
    chosen_source: str | None = None,
    trust_tier: str | None = None,
    source_url: str | None = None,
    identity_used: str | None = None,
    reason: str | None = None,
) -> dict:
    """Build a precedence-trail payload with a consistent key set.

    Every key is always present (``None`` when not applicable) so a downstream
    reader never has to guess which keys a given row carries.
    """
    return {
        "outcome": outcome,
        "chosen_source": chosen_source,
        "trust_tier": trust_tier,
        "source_url": source_url,
        "identity_used": identity_used,
        "identity_confirmed": identity_confirmed,
        "reason": reason,
        "ladder": _PRECEDENCE_LADDER,
    }


def _samples_payload(aggregate: AggregatedEstimate) -> list[dict]:
    """Lean per-sample audit rows. ``self_reported_confidence`` is internal-only."""
    return [
        {
            "carbs_low": s.carbs_low,
            "carbs_high": s.carbs_high,
            "identity": s.food_description or None,
            "self_reported_confidence": s.self_reported_confidence,
            "parse_ok": s.parse_ok,
        }
        for s in aggregate.samples
    ]


def _dispersion_payload(aggregate: AggregatedEstimate) -> dict:
    return {
        "confidence": aggregate.confidence,
        "coefficient_of_variation": aggregate.dispersion_cv,
        "samples_requested": aggregate.samples_requested,
        "samples_used": aggregate.samples_ok,
        "identity_agreement": aggregate.identity_agreement,
        "distinct_identities": aggregate.distinct_identities,
        "wide_spread": aggregate.wide_spread,
    }


async def record_estimate_audit(
    food_record_id: uuid.UUID,
    user_id: uuid.UUID,
    aggregate: AggregatedEstimate,
) -> None:
    """Persist the create-time audit (raw samples + dispersion + vision-only).

    Idempotent on the 1:1 ``food_record_id`` so a retried create updates rather
    than duplicates. Best-effort: never raises into the caller.
    """
    now = datetime.now(UTC)
    precedence = _precedence(
        _OUTCOME_VISION_ONLY,
        identity_confirmed=False,
        reason="Identity not yet confirmed; estimate is vision-only.",
    )
    values = {
        "food_record_id": food_record_id,
        "user_id": user_id,
        "samples_json": _samples_payload(aggregate),
        "dispersion_json": _dispersion_payload(aggregate),
        "precedence_json": precedence,
    }
    stmt = pg_insert(FoodRecordAudit).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["food_record_id"],
        set_={
            "samples_json": stmt.excluded.samples_json,
            "dispersion_json": stmt.excluded.dispersion_json,
            "precedence_json": stmt.excluded.precedence_json,
            "updated_at": now,
        },
    )
    try:
        async with get_session_maker()() as db:
            await db.execute(stmt)
            await db.commit()
    except Exception:
        logger.warning(
            "Failed to write estimate audit",
            food_record_id=str(food_record_id),
            exc_info=True,
        )


async def record_grounding_decision(
    food_record_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    grounding: GroundingDetail | None,
    identity: str,
    identity_confirmed: bool,
) -> None:
    """Update the audit's precedence trail after an identity confirmation.

    Records which grounding source won (or vision-only) and the identity it was
    keyed on. Idempotent upsert so a re-confirm overwrites the prior decision
    (and a missing create-time audit is still captured, sans samples). Best-effort.
    """
    now = datetime.now(UTC)
    if grounding is not None:
        precedence = _precedence(
            _OUTCOME_GROUNDED,
            identity_confirmed=identity_confirmed,
            chosen_source=grounding.source,
            trust_tier=grounding.trust_tier,
            source_url=grounding.source_url,
            identity_used=identity,
        )
    else:
        precedence = _precedence(
            _OUTCOME_VISION_ONLY,
            identity_confirmed=identity_confirmed,
            chosen_source="vision-only",
            identity_used=identity,
            reason="No source matched the confirmed identity.",
        )
    # Upsert only the precedence: a re-confirm overwrites the decision while the
    # create-time samples_json / dispersion_json are deliberately left intact.
    stmt = pg_insert(FoodRecordAudit).values(
        food_record_id=food_record_id,
        user_id=user_id,
        precedence_json=precedence,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["food_record_id"],
        set_={
            "precedence_json": stmt.excluded.precedence_json,
            "updated_at": now,
        },
    )
    try:
        async with get_session_maker()() as db:
            await db.execute(stmt)
            await db.commit()
    except Exception:
        logger.warning(
            "Failed to update grounding audit",
            food_record_id=str(food_record_id),
            exc_info=True,
        )


async def get_audit(
    db: AsyncSession,
    food_record_id: uuid.UUID,
    user_id: uuid.UUID,
) -> FoodRecordAudit | None:
    """Owner-scoped fetch of a record's audit trail, or None.

    Scoped by ``user_id`` (IDOR defence) in addition to the caller's ownership
    check on the food record itself.
    """
    return await db.scalar(
        select(FoodRecordAudit).where(
            FoodRecordAudit.food_record_id == food_record_id,
            FoodRecordAudit.user_id == user_id,
        )
    )
