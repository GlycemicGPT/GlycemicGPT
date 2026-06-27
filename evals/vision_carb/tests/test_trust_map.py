"""The vision pass-bar maps to the SAME shared ``TrustVerdict`` the text harness
uses — one enum object, no drifting copy — and only in trust mode, so the
standalone ``Verdict`` output and the ``FINDINGS.md`` pin are untouched.
"""

import passbar
from passbar import PassBarResult, Verdict, to_trust_verdict

# passbar's import shim has already put apps/api on sys.path, so the shared enum
# is importable here (same object the text harness uses).
from src.core.trust import TrustVerdict, is_not_safe


def test_verdict_maps_to_the_shared_enum() -> None:
    assert to_trust_verdict(Verdict.PASS) is TrustVerdict.PASS
    assert to_trust_verdict(Verdict.FAIL) is TrustVerdict.FAIL
    # The pass-bar's INSUFFICIENT_DATA and the text harness's ERROR unify here.
    assert to_trust_verdict(Verdict.INSUFFICIENT_DATA) is TrustVerdict.INCOMPLETE


def test_insufficient_data_gates_as_not_safe() -> None:
    assert is_not_safe(to_trust_verdict(Verdict.INSUFFICIENT_DATA)) is True
    assert is_not_safe(to_trust_verdict(Verdict.FAIL)) is True
    assert is_not_safe(to_trust_verdict(Verdict.PASS)) is False


def test_every_vision_verdict_maps() -> None:
    for verdict in Verdict:
        assert isinstance(to_trust_verdict(verdict), TrustVerdict)


def test_shared_enum_is_the_backend_object() -> None:
    # Not a string mirror: the symbol imported here is the very enum the backend
    # defines, so the vocabulary cannot drift between the two harnesses.
    assert passbar.TrustVerdict is TrustVerdict


def test_trust_mode_is_opt_in_so_standalone_output_is_unchanged() -> None:
    result = PassBarResult(
        verdict=Verdict.INSUFFICIENT_DATA,
        has_vision=True,
        repeats=1,
        certifiable_n=False,
    )
    # Default (standalone CLI) output carries no shared-verdict field.
    assert "trust_verdict" not in result.to_dict()
    # A trust-kernel consumer opts in.
    assert result.to_dict(trust_mode=True)["trust_verdict"] == "INCOMPLETE"
    assert result.trust_verdict is TrustVerdict.INCOMPLETE
