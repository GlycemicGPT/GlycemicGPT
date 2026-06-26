"""Vision capability gating for the meal-photo carb-estimate path.

A user can point their AI-provider config at any self-hosted, OpenAI-compatible
model (a local Ollama / LM Studio endpoint). Cloud vision is evaluated and known
good; an arbitrary local model is **not** -- the research behind the meal feature
(see ``evals/vision_carb/FINDINGS.md``) shows a local model that is accurate on
average can still swing wildly photo-to-photo or confidently misidentify a simple
food, and either failure is an acute-hypo risk. Producing a silent carb estimate
from such a model is worse than producing none.

So this module gates the *capability* before we ever call the model: a provider
whose vision is verified proceeds; a local model that has not been certified
through the benchmark pass-bar is refused with a clear, actionable message and is
never silently estimated. This is the runtime complement to the offline pass-bar
(``evals/vision_carb/passbar.py``): the pass-bar decides whether a benchmarked
model *clears the bar*; this registry records which models a maintainer has
certified and enabled, and the estimate path consults it per request.

The two are connected by process, not code: a maintainer runs the operational
benchmark, records a PASS, and -- once a transport for that endpoint exists --
adds the model identifier to ``CLEARED_LOCAL_VISION_MODELS``. Until then every
local model is treated as unverified. Nothing here is a dosing decision; it gates
a model's fitness to *describe* a photo.
"""

from __future__ import annotations

from enum import Enum

from src.models.ai_provider import AIProviderType
from src.vision.carb_contract import find_dosing_violations


class VisionCapability(str, Enum):
    """How a configured ``(provider_type, model)`` is treated for vision."""

    # Verified vision (cloud providers evaluated in the vision spike, routed
    # through a sanctioned sidecar mechanism) or a maintainer-certified local
    # model: the estimate path proceeds.
    CLEARED = "cleared"
    # A self-hosted / local model that has not been certified for carb
    # estimation: the estimate path refuses it with a clear message.
    UNVERIFIED_LOCAL = "unverified_local"


# Cloud provider modes whose vision capability is verified (the vision-carb eval)
# and served through the sidecar's sanctioned mechanisms. Their model defaults are
# known vision-capable; an actual no-vision misconfiguration (e.g. an OpenAI key
# without vision access) still surfaces cleanly as the sidecar's HTTP 422
# ``vision_unavailable`` -- this gate does not need to second-guess that.
_CLEARED_CLOUD_PROVIDER_TYPES = frozenset(
    {
        AIProviderType.CLAUDE_API,
        AIProviderType.OPENAI_API,
        AIProviderType.CLAUDE_SUBSCRIPTION,
        AIProviderType.CHATGPT_SUBSCRIPTION,
        # Legacy values kept for backwards compatibility with existing rows.
        AIProviderType.CLAUDE,
        AIProviderType.OPENAI,
    }
)

# Self-hosted / generic OpenAI-compatible endpoints (local Ollama, LM Studio,
# routers). A model here is cleared ONLY by appearing in the allow-list below.
_LOCAL_PROVIDER_TYPES = frozenset({AIProviderType.OPENAI_COMPATIBLE})

# Local vision models certified for carb estimation. A model earns a place here
# only after a maintainer records a PASS for it in the operational benchmark
# (``evals/vision_carb/FINDINGS.md``) AND its endpoint has a wired vision
# transport. It is intentionally EMPTY: no local model has cleared the bar on
# first-party hardware yet, so the product gates every local model rather than
# ship a silent low-quality estimate. Identifiers are matched normalized
# (lower-cased, stripped) against the user's configured model name.
CLEARED_LOCAL_VISION_MODELS: frozenset[str] = frozenset()


def _normalize(model_name: str | None) -> str:
    return (model_name or "").strip().lower()


def classify(provider_type: AIProviderType, model_name: str | None) -> VisionCapability:
    """Classify a configured provider/model for vision carb estimation.

    Cloud sanctioned providers are ``CLEARED``. A local (OpenAI-compatible) model
    is ``CLEARED`` only if certified (in ``CLEARED_LOCAL_VISION_MODELS``),
    otherwise ``UNVERIFIED_LOCAL``. Any unrecognized provider type fails closed to
    ``UNVERIFIED_LOCAL`` -- a model we cannot vouch for is not silently estimated.
    """
    if provider_type in _CLEARED_CLOUD_PROVIDER_TYPES:
        return VisionCapability.CLEARED
    if provider_type in _LOCAL_PROVIDER_TYPES:
        if _normalize(model_name) in CLEARED_LOCAL_VISION_MODELS:
            return VisionCapability.CLEARED
        return VisionCapability.UNVERIFIED_LOCAL
    return VisionCapability.UNVERIFIED_LOCAL


def is_vision_cleared(provider_type: AIProviderType, model_name: str | None) -> bool:
    """True when this provider/model may run the vision carb estimate."""
    return classify(provider_type, model_name) is VisionCapability.CLEARED


def unverified_local_message(model_name: str | None) -> str:
    """A clear, actionable refusal for an unverified local model.

    No dosing language: this is a capability message. It tells the user *why* the
    estimate is off and *what to do*, naming any certified local models if some
    exist, otherwise pointing to the verified path and the guidance.

    The user-configured model name is echoed (in its original casing, trimmed) so
    the user knows which model was rejected -- but it is *defensively scrubbed*
    first: a model name is unvalidated free text, so a pathological one like
    "take 4 units of insulin" would otherwise smuggle dosing phrasing into a
    user-facing message, violating the never-dose-language invariant the rest of
    the codebase defends. If the name itself trips the dosing scan, it is hidden.
    """
    shown = (model_name or "").strip() or "(no model set)"
    if find_dosing_violations(shown):
        shown = "(model name hidden)"
    if CLEARED_LOCAL_VISION_MODELS:
        certified = ", ".join(sorted(CLEARED_LOCAL_VISION_MODELS))
        suggestion = (
            f"Switch to a verified local model ({certified}) or a cloud provider."
        )
    else:
        suggestion = (
            "No local model has been verified for this yet -- use a cloud AI "
            "provider for meal photos, or see the local AI vision guide to check "
            "which models qualify and how to run the benchmark yourself."
        )
    return (
        f"The local model '{shown}' has not been verified to estimate meal carbs "
        "reliably enough, so photo estimates are turned off for it to avoid a "
        f"misleading result. {suggestion}"
    )
