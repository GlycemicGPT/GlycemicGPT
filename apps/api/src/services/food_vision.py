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
from src.schemas.food_record import GroundingDetail
from src.services import food_image, meal_grounding, meal_rag
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
    raw_text = await _call_vision(model, processed.media_type, image_b64)

    estimate = parse_estimate(raw_text)
    if (
        not estimate.parse_ok
        or estimate.carbs_low is None
        or estimate.carbs_high is None
    ):
        raise EstimateRejectedError(
            "Could not read a carbohydrate estimate from this photo."
        )
    try:
        low, high = validate_carb_range(estimate.carbs_low, estimate.carbs_high)
    except CarbBoundsError as exc:
        raise EstimateRejectedError(
            "The estimate was outside the supported range."
        ) from exc

    # Defensive scrub: never persist any dosing/advice phrasing. We already drop
    # the raw prose; null a food description that smuggled in advice and log it
    # for monitoring (count only -- no content).
    food_description: str | None = estimate.food_description or None
    desc_violations = (
        find_dosing_violations(food_description) if food_description else []
    )
    if estimate.dosing_violations or desc_violations:
        logger.warning(
            "Dosing phrasing detected in vision response; scrubbed",
            violation_count=len(estimate.dosing_violations) + len(desc_violations),
        )
        if desc_violations:
            food_description = None

    if food_description:
        food_description = food_description[:_MAX_DESCRIPTION_CHARS]

    # Ground the descriptive estimate against the user's own history (RAG) and
    # published nutrition (USDA / OFF), best-effort. Computed before persisting so
    # the own-history recall sees only prior records, not this one. Any failure
    # falls back to a vision-only (ungrounded) estimate -- grounding never blocks
    # or alters the core estimate, and never produces a dose.
    grounding = await _ground_estimate(user, food_description)

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
        confidence=estimate.confidence,
        nutrition_json=estimate.nutrition or None,
        ai_model=model,
        ai_provider=provider_label,
        source=FoodRecordSource.AI_ESTIMATE,
        grounding_source=grounding.source if grounding else None,
        grounding_source_url=grounding.source_url if grounding else None,
        grounding_trust_tier=grounding.trust_tier if grounding else None,
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

    # Attach the grounding detail (grounded range + citation + disclaimer) for the
    # response. Transient -- not a persisted column; reads of the record later
    # carry only the flat grounding_* attribution fields.
    record.grounding = grounding
    return record


async def _ground_estimate(
    user: User, food_description: str | None
) -> GroundingDetail | None:
    """Compute grounding for an estimate; never raise (fall back to vision-only)."""
    if not settings.meal_intelligence_enabled:
        return None
    try:
        return await meal_grounding.ground_estimate(user.id, food_description)
    except Exception:
        logger.warning("Estimate grounding failed; using vision-only", exc_info=True)
        return None
