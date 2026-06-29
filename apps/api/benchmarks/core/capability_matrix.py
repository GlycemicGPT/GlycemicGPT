"""Compose the two safety harnesses into one per-capability trust matrix.

A user who brings their own model wants one honest answer to "what is this model
trusted to do for me?" — and that answer is not a single verdict. The text
harness (``apps/api/benchmarks``) screens the chat / brief / correction / meal
text surfaces; the standalone vision pass-bar (``evals/vision_carb``) screens
meal-photo carb estimation. They agree philosophically and both already map onto
the shared ``src.core.trust.TrustVerdict``, but a model is rarely uniformly good:
it can be trusted for chat while never having been asked to do vision at all.

This module composes those per-surface verdicts into a **capability matrix** — a
``TrustVerdict`` *per capability*, deliberately **without flattening** into one
collapsed verdict. Collapsing would destroy the only information a BYOAI user
actually needs (which capabilities are trusted) and would force a lie at the
edges: a text-only model has no meal-vision surface, so flattening would either
drag the whole model to not-safe over vision it was never asked to do, or hide a
real text failure behind a vision pass. The matrix keeps each capability's
verdict separate so the report can say, plainly, "chat: NOT FLAGGED · meal-vision:
N/A".

The load-bearing semantics — get these exactly right:

  * ``NOT_APPLICABLE`` means *we did not assess this capability*. It is neither a
    clearance nor a failure: an untested capability must never read as trusted
    (``is_trusted(NOT_APPLICABLE)`` is ``False``) and must never fail a model
    (``is_not_safe(NOT_APPLICABLE)`` is ``False``). It is the fix for the real
    bug — a text-only model used to read as a vision ``FAIL`` because the vision
    pass-bar's ``vision_available`` gate fails closed for a model with no vision
    route. The matrix never runs the pass-bar for a model whose vision does not
    apply; it reads ``NOT_APPLICABLE`` instead.
  * Vision is assessed **only** when meal-intelligence is enabled *and* a vision
    endpoint is configured (``VisionAvailability.applies``). Otherwise the vision
    capability is ``NOT_APPLICABLE`` (don't lead with vision). When vision applies
    but no verdict was produced, the cell is ``INCOMPLETE`` (fail-closed: a
    capability that was due but uncertified is not-safe, never a silent pass).

This is a thin composition adapter: it does not re-score anything. Each harness
keeps its own bar (vision's is reproducibility/identity-first; text's is
dose/unit/grounding) and its own crossing onto the shared enum. The text crossing
(``safety_to_trust``) lives in the same package, so this composer applies it
directly — which also makes the matrix the place ``ERROR → INCOMPLETE`` is
exercised end-to-end. The vision harness is a separate standalone tool across a
deliberate package boundary (the two share only ``src.core.trust`` /
``src.core.content_digest``); it owns its own crossing (``to_trust_verdict``) and
hands this composer an already-shared ``TrustVerdict``. That asymmetry is the
boundary, not an accident.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from benchmarks.core.report import MEDICAL_DISCLAIMER_FOOTER
from benchmarks.core.verdict import SafetyVerdict, safety_to_trust
from benchmarks.core.version import TEXT_SURFACES
from src.core.trust import TrustVerdict, is_not_safe, is_trusted

__all__ = [
    "MEAL_VISION",
    "CapabilityMatrix",
    "CapabilityResult",
    "VisionAvailability",
    "build_capability_matrix",
    "render_capability_matrix",
]

# The single non-text capability: meal-photo carb-gram estimation, screened by
# the standalone vision pass-bar. Its id is distinct from every text surface so a
# capability can never be ambiguous between the two harnesses.
MEAL_VISION = "meal_vision"

# The verdicts a vision run can actually produce once crossed to the shared enum
# (``to_trust_verdict`` maps the pass-bar's pass / fail / insufficient_data onto
# these three). A vision verdict is never ``NOT_APPLICABLE`` — that state is the
# matrix's own gating decision, not something a run emits — so a caller handing us
# ``NOT_APPLICABLE`` as a *result* is a contradiction we reject loudly.
_VISION_RESULT_VERDICTS = frozenset(
    {TrustVerdict.PASS, TrustVerdict.FAIL, TrustVerdict.INCOMPLETE}
)

# Short, table-friendly screen labels for each verdict. They mirror the framing in
# ``report.py`` (a PASS is "NOT FLAGGED", never "safe") and spell out that
# NOT_APPLICABLE is "not assessed" — never trusted, never failed. The full
# not-a-guarantee caveat rides in the section header and footer, not every cell.
_TRUST_LABEL: dict[TrustVerdict, str] = {
    TrustVerdict.PASS: "NOT FLAGGED",
    TrustVerdict.FAIL: "FLAGGED",
    TrustVerdict.INCOMPLETE: "INCOMPLETE",
    TrustVerdict.NOT_APPLICABLE: "N/A (not assessed)",
}
_TRUST_MARK: dict[TrustVerdict, str] = {
    TrustVerdict.PASS: "✅",
    TrustVerdict.FAIL: "❌",
    TrustVerdict.INCOMPLETE: "⚠️",
    TrustVerdict.NOT_APPLICABLE: "—",
}


@dataclass(frozen=True)
class VisionAvailability:
    """Whether meal-photo carb vision is a capability worth assessing for a model.

    Both conditions must hold for vision to be scored: meal-intelligence is
    enabled for the user, and a vision-capable endpoint is configured for their
    model. A text-only BYOAI model (no vision endpoint) ``applies == False`` and
    is read as ``NOT_APPLICABLE`` — never failed on vision it was never asked to
    do.
    """

    meal_intelligence_enabled: bool
    vision_endpoint_configured: bool

    @property
    def applies(self) -> bool:
        return self.meal_intelligence_enabled and self.vision_endpoint_configured


@dataclass(frozen=True)
class CapabilityResult:
    """One capability's verdict on the shared trust vocabulary."""

    capability: str
    verdict: TrustVerdict

    @property
    def trusted(self) -> bool:
        """A clean clearance for this capability (``PASS`` only)."""
        return is_trusted(self.verdict)

    @property
    def not_safe(self) -> bool:
        """Gates as not-safe for this capability (``FAIL`` / ``INCOMPLETE``)."""
        return is_not_safe(self.verdict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "verdict": self.verdict.value,
            "trusted": self.trusted,
        }


@dataclass(frozen=True)
class CapabilityMatrix:
    """Per-capability trust verdicts, intentionally NOT flattened to one verdict.

    There is deliberately no single ``matrix.verdict``: trust is a question you
    ask *per capability* (``is_trusted_for("chat")``), because the foot-gun this
    whole story exists to remove is a model reading as uniformly trusted /
    untrusted when it is neither.
    """

    results: tuple[CapabilityResult, ...]

    def verdicts_by_capability(self) -> dict[str, TrustVerdict]:
        """``{capability: verdict}`` for programmatic lookup.

        Named distinctly from ``to_dict`` (the JSON view) so the two are never
        confused: this returns enum-valued verdicts keyed by capability, not the
        serialized report shape.
        """
        return {r.capability: r.verdict for r in self.results}

    def verdict_for(self, capability: str) -> TrustVerdict:
        """The verdict for one capability, or ``ValueError`` if absent.

        Fail-loud: a missing capability is a caller bug (a typo, or a query for a
        capability that was never composed), never silently a pass.
        """
        for result in self.results:
            if result.capability == capability:
                return result.verdict
        raise ValueError(
            f"capability {capability!r} is not in this matrix "
            f"(have: {[r.capability for r in self.results]})"
        )

    def is_trusted_for(self, capability: str) -> bool:
        """Whether the model is a clean clearance for this capability (``PASS``).

        Keyed off the kernel's ``is_trusted`` so a ``NOT_APPLICABLE`` capability
        is never mistaken for trusted — the no-false-trust invariant.
        """
        return is_trusted(self.verdict_for(capability))

    def trusted_capabilities(self) -> list[str]:
        """Capabilities the model cleanly cleared (``PASS`` only).

        ``NOT_APPLICABLE`` and ``INCOMPLETE`` are excluded: an unassessed or
        uncertified capability is not "trusted".
        """
        return [r.capability for r in self.results if r.trusted]

    def not_safe_capabilities(self) -> list[str]:
        """Capabilities that gate as not-safe (``FAIL`` / ``INCOMPLETE``)."""
        return [r.capability for r in self.results if r.not_safe]

    def not_applicable_capabilities(self) -> list[str]:
        """Capabilities that were not assessed (``NOT_APPLICABLE``)."""
        return [
            r.capability
            for r in self.results
            if r.verdict is TrustVerdict.NOT_APPLICABLE
        ]

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serializable view of the matrix (no flattened verdict)."""
        return {"capabilities": [r.to_dict() for r in self.results]}


def _vision_capability_verdict(
    vision: VisionAvailability, vision_verdict: TrustVerdict | None
) -> TrustVerdict:
    """Resolve the meal-vision capability's verdict from the gating + the run.

    The gate is the bug fix: vision is assessed only when it ``applies``. The
    four reachable outcomes, fail-closed:

      * does not apply, no verdict -> ``NOT_APPLICABLE`` (never asked to do it).
      * does not apply, but a verdict was passed -> contradiction (``ValueError``):
        we must not silently drop a computed verdict, nor silently mark a scored
        capability "not assessed".
      * applies, a verdict was produced -> that verdict (``PASS``/``FAIL``/
        ``INCOMPLETE``).
      * applies, no verdict -> ``INCOMPLETE`` (due but uncertified is not-safe,
        never a silent pass).
    """
    if not vision.applies:
        if vision_verdict is not None:
            raise ValueError(
                "vision does not apply (meal-intelligence + a vision endpoint are "
                "required) but a vision_verdict was provided; a verdict implies a "
                "run that should not have happened"
            )
        return TrustVerdict.NOT_APPLICABLE
    if vision_verdict is None:
        return TrustVerdict.INCOMPLETE
    if vision_verdict not in _VISION_RESULT_VERDICTS:
        raise ValueError(
            f"vision_verdict must be one of {sorted(v.value for v in _VISION_RESULT_VERDICTS)} "
            f"when vision applies, got {vision_verdict.value}"
        )
    return vision_verdict


def build_capability_matrix(
    *,
    text_verdicts: Mapping[str, SafetyVerdict],
    vision: VisionAvailability,
    vision_verdict: TrustVerdict | None = None,
) -> CapabilityMatrix:
    """Compose per-surface safety verdicts into a per-capability trust matrix.

    ``text_verdicts`` maps a text surface (one of ``TEXT_SURFACES``) to its
    ``SafetyVerdict``; each is crossed to the shared enum via ``safety_to_trust``
    (so the matrix is where ``ERROR -> INCOMPLETE`` is exercised). ``vision``
    gates whether the meal-vision capability is assessed; ``vision_verdict`` is
    that capability's already-shared verdict when a vision run happened.

    Every text surface appears in the matrix in canonical ``TEXT_SURFACES`` order
    (so rendering is stable regardless of mapping insertion order), with the
    meal-vision capability last. A surface absent from ``text_verdicts`` was *not
    exercised* and reads as ``NOT_APPLICABLE`` — never silently dropped: an
    omitted capability would be invisible, indistinguishable from a clean one,
    which is the exact false-trust hole this matrix exists to close. This is the
    same "not exercised" meaning ``NOT_APPLICABLE`` carries for vision (it gates
    as neither trusted nor not-safe), and distinct from ``INCOMPLETE``, which is a
    run that *happened* but could not certify. An unknown text surface raises
    ``ValueError`` rather than creating a phantom capability.
    """
    unknown = [s for s in text_verdicts if s not in TEXT_SURFACES]
    if unknown:
        raise ValueError(
            f"unknown text surface(s) {unknown}; valid surfaces are "
            f"{list(TEXT_SURFACES)}"
        )

    results = [
        CapabilityResult(
            surface,
            safety_to_trust(text_verdicts[surface])
            if surface in text_verdicts
            else TrustVerdict.NOT_APPLICABLE,
        )
        for surface in TEXT_SURFACES
    ]
    results.append(
        CapabilityResult(
            MEAL_VISION, _vision_capability_verdict(vision, vision_verdict)
        )
    )
    return CapabilityMatrix(results=tuple(results))


def render_capability_matrix(matrix: CapabilityMatrix) -> str:
    """Render the matrix as a human Markdown section.

    One row per capability with its screen verdict. Frames the result as a screen,
    never a guarantee, and spells out that ``N/A`` is "not assessed" so a reader
    never mistakes an unassessed capability for a trusted one.
    """
    lines = [
        "## Capability trust matrix",
        "",
        "A per-capability safety screen — one verdict for each thing this model "
        "was asked to do. **N/A means the capability was not assessed: neither "
        "trusted nor failed.** A screen result, NOT a medical-safety guarantee.",
        "",
        "| Capability | Safety screen |",
        "|---|---|",
    ]
    for result in matrix.results:
        mark = _TRUST_MARK[result.verdict]
        label = _TRUST_LABEL[result.verdict]
        lines.append(f"| {result.capability} | {mark} {label} |")
    lines += [
        "",
        MEDICAL_DISCLAIMER_FOOTER,
    ]
    return "\n".join(lines)
