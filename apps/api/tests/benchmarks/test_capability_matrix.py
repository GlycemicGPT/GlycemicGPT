"""The per-capability trust matrix: compose the text + vision harnesses into one
verdict-per-capability without flattening, and never let an unassessed capability
read as trusted.

These are the standing bar for the composition layer. The load-bearing cases are
the bug fix (a text-only model reads vision as ``NOT_APPLICABLE``, never ``FAIL``)
and the no-false-trust invariant (``NOT_APPLICABLE`` is neither trusted nor
failed). The mapping-fidelity and lock-churn halves live in the kernel's own
suites (``test_trust_verdict``, ``test_harness_version_lock``, and the vision
``test_trust_map`` / ``test_passbar``); here we prove they hold *through* the
matrix.
"""

from __future__ import annotations

import pytest

from benchmarks.core.capability_matrix import (
    MEAL_VISION,
    CapabilityMatrix,
    VisionAvailability,
    build_capability_matrix,
    render_capability_matrix,
)
from benchmarks.core.verdict import SafetyVerdict
from benchmarks.core.version import TEXT_SURFACES
from src.core.trust import TrustVerdict, is_not_safe, is_trusted

# Vision is assessed only when both hold; these are the two gating inputs.
_VISION_ON = VisionAvailability(
    meal_intelligence_enabled=True, vision_endpoint_configured=True
)
_TEXT_ONLY = VisionAvailability(
    meal_intelligence_enabled=False, vision_endpoint_configured=False
)


# ---------------------------------------------------------------------------
# Test plan 1 — 4-state reachability: each of PASS / FAIL / INCOMPLETE /
# NOT_APPLICABLE is reachable for a capability, and the matrix renders each.
# ---------------------------------------------------------------------------


def test_all_four_states_are_reachable_per_capability() -> None:
    matrix = build_capability_matrix(
        text_verdicts={
            "chat": SafetyVerdict.PASS,  # -> PASS
            "daily_brief": SafetyVerdict.FAIL,  # -> FAIL
            "correction": SafetyVerdict.ERROR,  # -> INCOMPLETE
        },
        vision=_TEXT_ONLY,  # -> NOT_APPLICABLE
    )
    verdicts = matrix.verdicts_by_capability()
    assert verdicts["chat"] is TrustVerdict.PASS
    assert verdicts["daily_brief"] is TrustVerdict.FAIL
    assert verdicts["correction"] is TrustVerdict.INCOMPLETE
    assert verdicts[MEAL_VISION] is TrustVerdict.NOT_APPLICABLE
    # Every state is a distinct, reachable cell.
    assert set(verdicts.values()) == set(TrustVerdict)


def test_render_shows_every_state() -> None:
    matrix = build_capability_matrix(
        text_verdicts={
            "chat": SafetyVerdict.PASS,
            "daily_brief": SafetyVerdict.FAIL,
            "correction": SafetyVerdict.ERROR,
        },
        vision=_TEXT_ONLY,
    )
    rendered = render_capability_matrix(matrix)
    # Each capability and each verdict label appears in the table.
    for capability in ("chat", "daily_brief", "correction", MEAL_VISION):
        assert capability in rendered
    for label in ("NOT FLAGGED", "FLAGGED", "INCOMPLETE", "N/A (not assessed)"):
        assert label in rendered
    # Framed as a screen, not a guarantee.
    assert "NOT a medical-safety guarantee" in rendered
    assert "MEDICAL-DISCLAIMER.md" in rendered


# ---------------------------------------------------------------------------
# Test plan 2 — the bug fix: a text-only model reads vision as NOT_APPLICABLE,
# never FAIL.
# ---------------------------------------------------------------------------


def test_text_only_model_reads_vision_as_not_applicable_not_fail() -> None:
    matrix = build_capability_matrix(
        text_verdicts={"chat": SafetyVerdict.PASS},
        vision=_TEXT_ONLY,
    )
    vision = matrix.verdict_for(MEAL_VISION)
    assert vision is TrustVerdict.NOT_APPLICABLE
    assert vision is not TrustVerdict.FAIL
    # The model is not dragged to not-safe by vision it was never asked to do.
    assert MEAL_VISION not in matrix.not_safe_capabilities()


# ---------------------------------------------------------------------------
# Test plan 3 — vision-applies gating: vision is scored only with meal-intel AND
# a vision endpoint; otherwise NOT_APPLICABLE (one assertion per branch).
# ---------------------------------------------------------------------------


def test_vision_not_applicable_when_meal_intelligence_off() -> None:
    matrix = build_capability_matrix(
        text_verdicts={"chat": SafetyVerdict.PASS},
        vision=VisionAvailability(
            meal_intelligence_enabled=False, vision_endpoint_configured=True
        ),
    )
    assert matrix.verdict_for(MEAL_VISION) is TrustVerdict.NOT_APPLICABLE


def test_vision_not_applicable_when_no_vision_endpoint() -> None:
    matrix = build_capability_matrix(
        text_verdicts={"chat": SafetyVerdict.PASS},
        vision=VisionAvailability(
            meal_intelligence_enabled=True, vision_endpoint_configured=False
        ),
    )
    assert matrix.verdict_for(MEAL_VISION) is TrustVerdict.NOT_APPLICABLE


def test_vision_is_scored_when_it_applies() -> None:
    matrix = build_capability_matrix(
        text_verdicts={"chat": SafetyVerdict.PASS},
        vision=_VISION_ON,
        vision_verdict=TrustVerdict.PASS,
    )
    assert matrix.verdict_for(MEAL_VISION) is TrustVerdict.PASS


def test_vision_applies_but_unscored_is_incomplete_not_a_pass() -> None:
    # Fail-closed: vision was due but no verdict was produced -> INCOMPLETE
    # (not-safe), never a silent pass and never NOT_APPLICABLE.
    matrix = build_capability_matrix(
        text_verdicts={"chat": SafetyVerdict.PASS},
        vision=_VISION_ON,
        vision_verdict=None,
    )
    vision = matrix.verdict_for(MEAL_VISION)
    assert vision is TrustVerdict.INCOMPLETE
    assert is_not_safe(vision) is True


def test_verdict_without_applicable_vision_is_a_contradiction() -> None:
    # A verdict implies a run that should not have happened for a model whose
    # vision does not apply — reject it loudly rather than silently dropping it.
    with pytest.raises(ValueError):
        build_capability_matrix(
            text_verdicts={"chat": SafetyVerdict.PASS},
            vision=_TEXT_ONLY,
            vision_verdict=TrustVerdict.PASS,
        )


def test_not_applicable_is_not_a_valid_vision_run_result() -> None:
    # A vision run never *produces* NOT_APPLICABLE; that is the matrix's gating
    # decision. Passing it as a result when vision applies is a caller bug.
    with pytest.raises(ValueError):
        build_capability_matrix(
            text_verdicts={"chat": SafetyVerdict.PASS},
            vision=_VISION_ON,
            vision_verdict=TrustVerdict.NOT_APPLICABLE,
        )


# ---------------------------------------------------------------------------
# Test plan 4 — no false trust: NOT_APPLICABLE is neither trusted nor failed.
# ---------------------------------------------------------------------------


def test_not_applicable_vision_is_not_reported_trusted() -> None:
    matrix = build_capability_matrix(
        text_verdicts={"chat": SafetyVerdict.PASS},
        vision=_TEXT_ONLY,
    )
    # Not trusted...
    assert matrix.is_trusted_for(MEAL_VISION) is False
    assert MEAL_VISION not in matrix.trusted_capabilities()
    # ...and not failed.
    assert MEAL_VISION not in matrix.not_safe_capabilities()
    # ...and explicitly surfaced as not-assessed (the third partition).
    assert MEAL_VISION in matrix.not_applicable_capabilities()
    # The kernel invariant the matrix leans on.
    assert is_trusted(TrustVerdict.NOT_APPLICABLE) is False
    assert is_not_safe(TrustVerdict.NOT_APPLICABLE) is False


def test_incomplete_capability_is_not_trusted() -> None:
    matrix = build_capability_matrix(
        text_verdicts={"chat": SafetyVerdict.ERROR},
        vision=_TEXT_ONLY,
    )
    assert matrix.is_trusted_for("chat") is False
    assert "chat" not in matrix.trusted_capabilities()
    assert "chat" in matrix.not_safe_capabilities()


# ---------------------------------------------------------------------------
# Test plan 5 — composition without flattening: a text-PASS + vision-FAIL model
# shows BOTH; trusted for the text capability, not for vision.
# ---------------------------------------------------------------------------


def test_text_pass_and_vision_fail_coexist_without_flattening() -> None:
    matrix = build_capability_matrix(
        text_verdicts={"chat": SafetyVerdict.PASS},
        vision=_VISION_ON,
        vision_verdict=TrustVerdict.FAIL,
    )
    # Both capabilities are present with their own verdicts — not collapsed.
    assert matrix.verdict_for("chat") is TrustVerdict.PASS
    assert matrix.verdict_for(MEAL_VISION) is TrustVerdict.FAIL
    # Trusted for text, not for vision.
    assert matrix.is_trusted_for("chat") is True
    assert matrix.is_trusted_for(MEAL_VISION) is False
    assert matrix.trusted_capabilities() == ["chat"]
    assert matrix.not_safe_capabilities() == [MEAL_VISION]
    # No single flattened verdict exists — trust is only askable per capability.
    assert not hasattr(matrix, "verdict")
    assert not hasattr(matrix, "overall_verdict")


# ---------------------------------------------------------------------------
# Test plan 6 — mapping fidelity through the matrix: text ERROR -> INCOMPLETE;
# vision INSUFFICIENT_DATA (already INCOMPLETE on the shared enum) carries
# through. (The harness-native crossings are proven in test_trust_verdict and the
# vision test_trust_map; here we prove the matrix preserves them.)
# ---------------------------------------------------------------------------


def test_text_error_maps_to_incomplete_through_the_matrix() -> None:
    matrix = build_capability_matrix(
        text_verdicts={"chat": SafetyVerdict.ERROR},
        vision=_TEXT_ONLY,
    )
    assert matrix.verdict_for("chat") is TrustVerdict.INCOMPLETE


def test_vision_incomplete_carries_through_the_matrix() -> None:
    # The vision pass-bar's INSUFFICIENT_DATA crosses to INCOMPLETE before it
    # reaches the composer (proven in evals/vision_carb/tests/test_trust_map.py);
    # the matrix carries that not-safe verdict through unchanged.
    matrix = build_capability_matrix(
        text_verdicts={"chat": SafetyVerdict.PASS},
        vision=_VISION_ON,
        vision_verdict=TrustVerdict.INCOMPLETE,
    )
    assert matrix.verdict_for(MEAL_VISION) is TrustVerdict.INCOMPLETE
    assert is_not_safe(matrix.verdict_for(MEAL_VISION)) is True


# ---------------------------------------------------------------------------
# Structure, ordering, validation, and serialization.
# ---------------------------------------------------------------------------


def test_rows_are_canonical_order_and_no_surface_is_dropped() -> None:
    matrix = build_capability_matrix(
        # Insertion order deliberately scrambled, and a partial map (most text
        # surfaces omitted) — none may be silently dropped.
        text_verdicts={
            "correction": SafetyVerdict.PASS,
            "chat": SafetyVerdict.PASS,
            "meal_analysis": SafetyVerdict.PASS,
        },
        vision=_TEXT_ONLY,
    )
    ordered = [r.capability for r in matrix.results]
    # EVERY text surface appears, in canonical TEXT_SURFACES order, regardless of
    # insertion order and regardless of which were passed...
    assert ordered[:-1] == list(TEXT_SURFACES)
    # ...and meal-vision is always last.
    assert ordered[-1] == MEAL_VISION
    # The omitted surfaces are surfaced as not-assessed, never dropped.
    assert matrix.verdict_for("daily_brief") is TrustVerdict.NOT_APPLICABLE
    assert "daily_brief" in matrix.not_applicable_capabilities()


def test_unknown_text_surface_fails_loud() -> None:
    with pytest.raises(ValueError):
        build_capability_matrix(
            text_verdicts={"not_a_real_surface": SafetyVerdict.PASS},
            vision=_TEXT_ONLY,
        )


def test_verdict_for_unknown_capability_fails_loud() -> None:
    matrix = build_capability_matrix(
        text_verdicts={"chat": SafetyVerdict.PASS}, vision=_TEXT_ONLY
    )
    with pytest.raises(ValueError):
        matrix.verdict_for("not_a_capability")  # never a real capability


def test_to_dict_is_serializable_and_unflattened() -> None:
    matrix = build_capability_matrix(
        text_verdicts={"chat": SafetyVerdict.PASS},
        vision=_VISION_ON,
        vision_verdict=TrustVerdict.FAIL,
    )
    data = matrix.to_dict()
    # Every text surface (the unassessed ones as NOT_APPLICABLE) plus meal-vision
    # — nothing is silently omitted from the serialized report.
    expected = [
        {
            "capability": surface,
            "verdict": "PASS" if surface == "chat" else "NOT_APPLICABLE",
            "trusted": surface == "chat",
        }
        for surface in TEXT_SURFACES
    ] + [{"capability": MEAL_VISION, "verdict": "FAIL", "trusted": False}]
    assert data == {"capabilities": expected}
    # The serialized form carries no single rolled-up verdict either.
    assert "verdict" not in data
    assert "overall_verdict" not in data


def test_matrix_is_a_capability_matrix_instance() -> None:
    matrix = build_capability_matrix(
        text_verdicts={"chat": SafetyVerdict.PASS}, vision=_TEXT_ONLY
    )
    assert isinstance(matrix, CapabilityMatrix)
