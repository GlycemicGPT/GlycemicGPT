"""The shared trust vocabulary and the text harness's mapping onto it.

The mapping must preserve M1's fail-closed gating (no re-scoring), and the
vocabulary must be exactly the four members fixed for the forthcoming capability
matrix — locked here, before anything persists a verdict.
"""

from __future__ import annotations

import pytest

from benchmarks.core.verdict import SafetyVerdict, safety_to_trust
from src.core.trust import TrustVerdict, is_not_safe, is_trusted


def test_vocabulary_is_exactly_the_locked_four() -> None:
    assert {v.value for v in TrustVerdict} == {
        "PASS",
        "FAIL",
        "INCOMPLETE",
        "NOT_APPLICABLE",
    }


def test_mapping_preserves_m1_semantics() -> None:
    # PASS/FAIL carry across unchanged; ERROR ("could not evaluate") unifies to
    # INCOMPLETE (the same meaning the vision pass-bar spells INSUFFICIENT_DATA).
    assert safety_to_trust(SafetyVerdict.PASS) is TrustVerdict.PASS
    assert safety_to_trust(SafetyVerdict.FAIL) is TrustVerdict.FAIL
    assert safety_to_trust(SafetyVerdict.ERROR) is TrustVerdict.INCOMPLETE


def test_fail_and_incomplete_gate_as_not_safe_pass_does_not() -> None:
    assert is_not_safe(safety_to_trust(SafetyVerdict.FAIL)) is True
    assert is_not_safe(safety_to_trust(SafetyVerdict.ERROR)) is True
    assert is_not_safe(safety_to_trust(SafetyVerdict.PASS)) is False


def test_every_safety_verdict_maps() -> None:
    for sv in SafetyVerdict:
        assert isinstance(safety_to_trust(sv), TrustVerdict)


def test_not_applicable_is_excluded_from_the_gate_but_is_not_a_pass() -> None:
    # Forward-compatible member for the capability matrix: a capability the model
    # was never asked to demonstrate must not gate as not-safe...
    assert is_not_safe(TrustVerdict.NOT_APPLICABLE) is False
    # ...and must not be mistaken for a clean clearance.
    assert TrustVerdict.NOT_APPLICABLE is not TrustVerdict.PASS


def test_is_trusted_and_is_not_safe_are_a_pair_not_negations() -> None:
    # Only PASS is trusted; the foot-gun is treating "not is_not_safe" as trusted.
    assert is_trusted(TrustVerdict.PASS) is True
    for verdict in (
        TrustVerdict.FAIL,
        TrustVerdict.INCOMPLETE,
        TrustVerdict.NOT_APPLICABLE,
    ):
        assert is_trusted(verdict) is False
    # NOT_APPLICABLE is the case that proves they are not negations: neither
    # not-safe NOR trusted.
    assert is_not_safe(TrustVerdict.NOT_APPLICABLE) is False
    assert is_trusted(TrustVerdict.NOT_APPLICABLE) is False


def test_gating_helpers_accept_the_serialized_string_form() -> None:
    # The contract backs persisted/cached verdicts, which round-trip as the value
    # string — both helpers must gate a string identically to the enum.
    assert is_trusted("PASS") is True
    assert is_trusted(TrustVerdict.PASS.value) is True
    assert is_not_safe("FAIL") is True
    assert is_not_safe("INCOMPLETE") is True
    assert is_not_safe("PASS") is False
    assert is_not_safe("NOT_APPLICABLE") is False
    assert is_trusted("NOT_APPLICABLE") is False


def test_unknown_serialized_value_fails_loud() -> None:
    # An unrecognized value must raise, never be silently treated as safe.
    with pytest.raises(ValueError):
        is_trusted("DEFINITELY_NOT_A_VERDICT")
    with pytest.raises(ValueError):
        is_not_safe("bogus")
