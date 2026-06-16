"""Meal-photo carb estimation pipeline.

Ties the pieces together: validate + store the photo, ask the user's configured
AI provider to describe its carbohydrate content via the sidecar's vision route,
parse the structured estimate against the shared contract, enforce the
reject-not-clamp carb bounds, and persist a ``food_records`` row.

Routing note (the provider-call path): all vision traffic goes through the AI
sidecar's OpenAI-compatible ``/v1/chat/completions`` endpoint. The sidecar is
the sole sanctioned home for vision: it centralizes every provider mechanism
(Anthropic API-key Messages API, Claude/ChatGPT subscription CLIs) along with
the SSRF/sandbox hardening, and selects the mechanism from the *model name*
we send (which is derived from the user's active provider). This differs from
the text path, where direct-API-key providers call their SDK directly -- but the
sidecar is the only place vision is sanctioned to run. When no provider has a
configured vision mechanism the sidecar returns HTTP 422 ``vision_unavailable``,
which we surface as a clear error rather than a silent failure or a fabricated
estimate.

Safety: this module produces a descriptive food estimate (carb range +
confidence + nutrition) and nothing else. It never returns or computes a dose,
and the persisted record is never read by IoB / treatment_safety / carb-ratio
math.
"""

import asyncio
import base64
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.logging_config import get_logger
from src.models.ai_provider import AIProviderConfig
from src.models.food_record import FoodRecord, FoodRecordSource
from src.models.user import User
from src.schemas.food_record import EstimateDispersion
from src.services import (
    food_image,
    meal_audit,
    meal_estimate_aggregate,
    meal_grounding,
    meal_rag,
)
from src.services.ai_client import DEFAULT_MODELS
from src.vision.carb_contract import (
    SYSTEM_PROMPT,
    USER_PROMPT,
    CarbBoundsError,
    find_dosing_violations,
    parse_estimate,
    validate_carb_range,
)

logger = get_logger(__name__)

# Cap the vision response so a chatty model can't blow the token budget; the
# structured estimate is small.
_VISION_MAX_TOKENS = 1024

# Defensive cap on the model-supplied food description before it's persisted to
# an unbounded TEXT column (storage-growth guard; the value is trusted sidecar
# output, not user input).
_MAX_DESCRIPTION_CHARS = 1000


class FoodVisionError(Exception):
    """Base class for estimation-pipeline failures."""


class ProviderNotConfiguredError(FoodVisionError):
    """The user has no AI provider configured."""


class VisionUnavailableError(FoodVisionError):
    """The user's active provider has no vision route (sidecar HTTP 422)."""


class VisionServiceError(FoodVisionError):
    """The sidecar was unreachable or returned an unexpected error."""


class EstimateRejectedError(FoodVisionError):
    """The model response could not be parsed into a usable, in-bounds estimate."""


async def _resolve_model(user: User, db: AsyncSession) -> tuple[str, str]:
    """Return ``(model_name, provider_label)`` for the user's active provider.

    The model name drives the sidecar's vision-runner selection. Raises
    ``ProviderNotConfiguredError`` when no provider is configured.
    """
    result = await db.execute(
        select(AIProviderConfig).where(AIProviderConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise ProviderNotConfiguredError("No AI provider configured.")
    model = config.model_name or DEFAULT_MODELS.get(config.provider_type, "")
    if not model:
        raise ProviderNotConfiguredError("No model configured for your AI provider.")
    return model, config.provider_type.value


def _build_vision_request(model: str, media_type: str, image_b64: str) -> dict:
    """Build the OpenAI-style multimodal chat request for the sidecar.

    Only a base64 ``data:`` image URL is sent (no remote URL) -- the sidecar
    rejects anything else, so there is no SSRF surface.
    """
    return {
        "model": model,
        "max_tokens": _VISION_MAX_TOKENS,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": USER_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{image_b64}"},
                    },
                ],
            },
        ],
    }


def _sidecar_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.ai_sidecar_api_key:
        headers["Authorization"] = f"Bearer {settings.ai_sidecar_api_key}"
    return headers


async def _call_vision(model: str, media_type: str, image_b64: str) -> str:
    """POST the multimodal request to the sidecar; return the response text.

    Maps the sidecar's ``vision_unavailable`` (HTTP 422) contract to
    ``VisionUnavailableError`` and any other failure to ``VisionServiceError``.
    """
    url = f"{settings.ai_sidecar_url}/v1/chat/completions"
    payload = _build_vision_request(model, media_type, image_b64)
    try:
        async with httpx.AsyncClient(
            timeout=settings.vision_request_timeout_seconds
        ) as client:
            resp = await client.post(url, headers=_sidecar_headers(), json=payload)
    except httpx.HTTPError as exc:
        logger.warning("Vision sidecar request failed", error=str(exc))
        raise VisionServiceError("AI vision service is unreachable.") from exc

    if resp.status_code == 422:
        message = _error_message(resp) or (
            "Vision is not available on your current AI provider."
        )
        raise VisionUnavailableError(message)
    if resp.status_code >= 400:
        logger.warning("Vision sidecar returned error", status_code=resp.status_code)
        raise VisionServiceError("AI vision service returned an error.")

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise VisionServiceError(
            "AI vision service returned no usable output."
        ) from exc
    # Some OpenAI-compatible providers can return `content` as a list of content
    # blocks; the contract parser expects text, so reject anything non-string
    # here rather than letting it surface as an unmapped 500 downstream.
    if not isinstance(content, str):
        raise VisionServiceError("AI vision service returned an unexpected response.")
    return content


async def _call_vision_samples(
    model: str, media_type: str, image_b64: str, n: int
) -> list[str]:
    """Issue ``n`` concurrent vision samples of the same image (Story 50.H1).

    Returns the raw text of every sample that succeeded. Per-sample failures are
    tolerated -- multi-sampling exists to measure disagreement, so losing a sample
    only narrows the evidence, it must not fail the request (AC6). If *no* sample
    succeeds, the failure is re-raised so the caller surfaces the original, clear
    error (``VisionUnavailableError`` when the provider has no vision route at
    all -- deterministic across samples -- otherwise ``VisionServiceError``)
    rather than a misleading "couldn't read the photo" parse error.
    """
    results = await asyncio.gather(
        *(_call_vision(model, media_type, image_b64) for _ in range(max(n, 1))),
        return_exceptions=True,
    )
    texts = [r for r in results if isinstance(r, str)]
    if texts:
        failures = len(results) - len(texts)
        if failures:
            logger.warning(
                "Some vision samples failed; aggregating the rest",
                requested=len(results),
                succeeded=len(texts),
            )
        return texts

    # No sample succeeded -- re-raise a representative error. Prefer a
    # VisionUnavailableError (the actionable "your provider can't do vision"
    # case) over a transient service error.
    for r in results:
        if isinstance(r, VisionUnavailableError):
            raise r
    for r in results:
        if isinstance(r, BaseException):
            raise r
    raise VisionServiceError("AI vision service returned no usable output.")


def _error_message(resp: httpx.Response) -> str | None:
    try:
        body = resp.json()
    except ValueError:
        return None
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str):
            return message
    return None


async def create_food_record_from_image(
    db: AsyncSession,
    user: User,
    raw_image: bytes,
) -> FoodRecord:
    """Run the full pipeline and persist a ``food_records`` row.

    Order matters: we estimate *before* writing the photo to disk so a vision
    failure never leaves an orphaned file. Carb bounds are enforced
    reject-not-clamp; a response we cannot turn into a usable, in-bounds
    estimate raises ``EstimateRejectedError`` rather than persisting a
    misleading record.
    """
    # Validate + strip metadata (raises food_image.* on bad input).
    processed = food_image.process_upload(raw_image)

    model, provider_label = await _resolve_model(user, db)

    image_b64 = base64.standard_b64encode(processed.data).decode("ascii")

    # Sample the same photo N times and aggregate the spread (Story 50.H1): the
    # confidence and range come from how much the samples disagree with each
    # other, not the model's self-reported confidence (which research shows is
    # uncorrelated with accuracy). Per-sample failures are tolerated; the call
    # only raises if *every* sample failed.
    requested_n = settings.meal_estimate_sample_count
    raw_texts = await _call_vision_samples(
        model, processed.media_type, image_b64, requested_n
    )
    samples = [parse_estimate(text) for text in raw_texts]

    # Per-sample dosing scrub BEFORE aggregation: a sample whose description
    # smuggled in advice has that description nulled (its carb numbers stay
    # usable), so the scrubbed text can never be chosen as the representative
    # description. Count only -- never log the content.
    scrubbed = 0
    for sample in samples:
        desc_violation = bool(
            sample.food_description and find_dosing_violations(sample.food_description)
        )
        if desc_violation:
            sample.food_description = ""
            scrubbed += 1
    if scrubbed:
        logger.warning(
            "Dosing phrasing detected in vision sample description(s); scrubbed",
            sample_count=scrubbed,
        )

    aggregate = meal_estimate_aggregate.aggregate_samples(
        samples, samples_requested=requested_n
    )
    if aggregate is None:
        raise EstimateRejectedError(
            "Could not read a carbohydrate estimate from this photo."
        )
    try:
        low, high = validate_carb_range(aggregate.carbs_low, aggregate.carbs_high)
    except CarbBoundsError as exc:
        raise EstimateRejectedError(
            "The estimate was outside the supported range."
        ) from exc

    food_description: str | None = aggregate.food_description or None
    if food_description:
        food_description = food_description[:_MAX_DESCRIPTION_CHARS]

    # Story 50.H2: identity is unconfirmed at creation (cold start), so external
    # authoritative grounding is gated OFF here -- a fresh vision label is never
    # silently certified with a USDA / restaurant citation. We only *suggest* an
    # identity from the user's own history (RAG) so a repeat food is a one-tap
    # confirm; grounding runs after the user confirms (the confirm-identity flow).
    # The estimate itself stays vision-only (range + empirical confidence).
    suggested_identity = await _suggest_identity(user, food_description)

    storage_path, size_bytes = food_image.store_image(user.id, processed)
    filename = Path(storage_path).name

    record = FoodRecord(
        user_id=user.id,
        filename=filename,
        file_type=processed.extension,
        file_size_bytes=size_bytes,
        storage_path=storage_path,
        food_description=food_description,
        carbs_low=low,
        carbs_high=high,
        # Empirical, dispersion-derived band -- NOT the model's self-reported
        # confidence (Story 50.H1), which is no longer surfaced to users.
        confidence=aggregate.confidence,
        nutrition_json=aggregate.nutrition or None,
        ai_model=model,
        ai_provider=provider_label,
        source=FoodRecordSource.AI_ESTIMATE,
        # Identity is unconfirmed until the user confirms it; grounding_* stay
        # NULL until then (the gate is enforced in meal_grounding too).
        identity_confirmed=False,
    )
    db.add(record)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        # Don't leave the just-written photo orphaned if the row failed.
        food_image.delete_stored_image(storage_path)
        raise
    await db.refresh(record)

    # Index this record into own-history RAG so a future photo of the same food
    # recalls it. Best-effort and after commit -- it must never fail the upload,
    # so guard the call site too (index_food_record is already internally
    # best-effort; this also covers anything raised before its own try).
    if settings.meal_intelligence_enabled:
        try:
            await meal_rag.index_food_record(record)
        except Exception:
            logger.warning("RAG indexing failed for food record", exc_info=True)

        # Persist the audit/provenance trail (Story 50.H3): the raw per-sample
        # outputs + dispersion + the (vision-only) precedence. Behind the same
        # flag as the other best-effort side-effects so the flag stays a true
        # kill switch; the grounding decision is appended at confirm time.
        try:
            await meal_audit.record_estimate_audit(record.id, user.id, aggregate)
        except Exception:
            logger.warning("Estimate audit write failed", exc_info=True)

    # No grounding at create time (identity unconfirmed) -- grounding actually
    # happens later in ``common_food.confirm_food_identity`` once the user confirms
    # the identity. Attach transient response detail: the multi-sample dispersion
    # (Story 50.H1) and the suggested identity to confirm (Story 50.H2). Neither is
    # a persisted column.
    record.grounding = None
    record.estimate_dispersion = _build_dispersion_detail(aggregate)
    record.suggested_identity = suggested_identity
    return record


# Fallback if a composed dispersion note ever trips the dosing scan (it cannot
# today -- every branch is fixed prose + numbers -- but the guard keeps the
# user-facing sink safe if a future edit interpolates model text into the note).
_SAFE_DISPERSION_NOTE = "This is an estimate from a photo -- treat it as approximate."


def _dispersion_note(
    aggregate: meal_estimate_aggregate.AggregatedEstimate,
) -> str:
    """A plain-language note that communicates uncertainty viscerally.

    Never blesses a number and never contains dosing language: a tight spread is
    deliberately NOT described as trustworthy (consistency is not correctness),
    and the persistent verify-before-dosing qualifier on every estimate surface
    carries the safety framing regardless of what this says.
    """
    low, high = aggregate.carbs_low, aggregate.carbs_high
    if not aggregate.identity_agreement:
        return (
            "The AI didn't consistently agree on what this food is, so this "
            "estimate is uncertain -- confirm the food before relying on it."
        )
    if aggregate.samples_ok <= 1:
        return "Estimated from a single read of the photo, so confidence is low."
    if aggregate.wide_spread:
        return (
            f"Repeated looks at this photo disagreed a lot (about {low:g} g to "
            f"{high:g} g) -- treat this as a rough guess, not a measurement."
        )
    if aggregate.confidence != meal_estimate_aggregate.CONFIDENCE_HIGH:
        # Medium band: real variation between reads, just not wild -- name the
        # spread rather than offering a reassuring "estimated from N reads".
        return (
            f"Reads of this photo varied somewhat (about {low:g} g to {high:g} g) "
            "-- treat this as approximate."
        )
    return f"Estimated from {aggregate.samples_ok} reads of the photo."


def _build_dispersion_detail(
    aggregate: meal_estimate_aggregate.AggregatedEstimate,
) -> EstimateDispersion:
    note = _dispersion_note(aggregate)
    # Defence in depth at the user-facing sink: never surface dosing phrasing.
    if find_dosing_violations(note):
        logger.warning("Dispersion note tripped dosing scan; using safe fallback")
        note = _SAFE_DISPERSION_NOTE
    return EstimateDispersion(
        confidence=aggregate.confidence,
        coefficient_of_variation=aggregate.dispersion_cv,
        samples_requested=aggregate.samples_requested,
        samples_used=aggregate.samples_ok,
        identity_agreement=aggregate.identity_agreement,
        distinct_identities=aggregate.distinct_identities,
        wide_spread=aggregate.wide_spread,
        note=note,
    )


async def _suggest_identity(user: User, food_description: str | None) -> str | None:
    """Suggest an identity from own history for one-tap confirm; never raise."""
    if not settings.meal_intelligence_enabled:
        return None
    try:
        return await meal_grounding.suggest_identity(user.id, food_description)
    except Exception:
        logger.warning("Identity suggestion failed", exc_info=True)
        return None
