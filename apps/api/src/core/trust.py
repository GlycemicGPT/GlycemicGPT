"""The shared, fail-closed trust verdict — one vocabulary every consumer keys off.

Two offline safety harnesses score what a model will actually do to a patient's
data: a text harness (``apps/api/benchmarks``) over the real production prompts +
floor, and a vision pass-bar (``evals/vision_carb``) over carb-photo estimates.
They agreed *philosophically* — both fail-closed, both tri-state — but spoke two
vocabularies (``PASS/FAIL/ERROR`` vs ``pass/fail/insufficient_data``) and shared
no type. This module is that single type: the contract a cached verdict, a
persisted result, and an advisory surface all read, so a "PASS" can always be
traced back to — and invalidated against — what production does.

It lives in ``src.core`` (not in either harness) on purpose: both harnesses must
import the *same* enum object so the vocabulary can never drift between them. The
text harness pulls it natively; the standalone vision harness imports it through
the same lightweight ``apps/api`` path shim it already uses for the carb
contract, so neither forks a copy.

Fail-closed semantics (the whole point):
  * ``PASS``  — every screen ran and none flagged the output. NOT a safety
                certificate; a screen result only.
  * ``FAIL``  — a screen flagged genuinely unsafe output. Gates as not-safe.
  * ``INCOMPLETE`` — the output could not be certified (empty/unparseable, a
                scorer raised, nothing measured, or below the certification N).
                Unifies the text harness's ``ERROR`` and the vision pass-bar's
                ``INSUFFICIENT_DATA``: both mean "this run did not prove the
                model safe," and both gate *exactly* like ``FAIL`` — never
                softened to safe.
  * ``NOT_APPLICABLE`` — the capability was not exercised for this model (e.g. a
                text-only model has no meal-vision surface to assess). Defined
                here, ahead of the capability matrix that will produce it, so the
                vocabulary is fixed once before anything persists it. It is
                EXCLUDED from the safe/not-safe gate: a capability a model was
                never asked to demonstrate must neither drag it to not-safe nor
                count as a clean clearance.
"""

from __future__ import annotations

import enum


class TrustVerdict(str, enum.Enum):
    """The unified, fail-closed trust outcome. See the module docstring."""

    PASS = "PASS"
    FAIL = "FAIL"
    INCOMPLETE = "INCOMPLETE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


# The verdicts that gate as NOT safe. ``INCOMPLETE`` is here with ``FAIL`` — a
# run that could not certify the model is treated as not-safe, never a silent
# pass (fail-closed). ``PASS`` is the only clean clearance; ``NOT_APPLICABLE`` is
# excluded entirely (the capability was not assessed).
_NOT_SAFE = frozenset({TrustVerdict.FAIL, TrustVerdict.INCOMPLETE})


def _coerce(verdict: TrustVerdict | str) -> TrustVerdict:
    """Accept the serialized string form as well as the enum.

    This contract backs cached/persisted verdicts, which round-trip as the value
    string (``"PASS"``), not the enum member — so both gating helpers coerce
    first, ensuring a stored ``"PASS"`` is trusted and a stored ``"FAIL"`` blocks,
    identically to the enum. An unknown value raises ``ValueError`` (fail-loud);
    it is never silently treated as safe.
    """
    return verdict if isinstance(verdict, TrustVerdict) else TrustVerdict(verdict)


def is_not_safe(verdict: TrustVerdict | str) -> bool:
    """Whether a verdict gates as NOT safe — use this to *block*.

    ``FAIL`` and ``INCOMPLETE`` both return ``True`` (fail-closed: an
    uncertifiable run is not safe). ``PASS`` and ``NOT_APPLICABLE`` return
    ``False`` — but for different reasons, and a caller must not conflate them:
    ``PASS`` is a clean clearance, while ``NOT_APPLICABLE`` means the capability
    was never exercised.

    ``is_not_safe`` and ``is_trusted`` are a deliberate pair, NOT negations of
    each other: ``is_not_safe`` blocks, ``is_trusted`` trusts. Never treat
    ``not is_not_safe(v)`` as "trusted" — that would wrongly trust a
    ``NOT_APPLICABLE``. Accepts the enum or its serialized value.
    """
    return _coerce(verdict) in _NOT_SAFE


def is_trusted(verdict: TrustVerdict | str) -> bool:
    """Whether a verdict is a clean clearance — use this to *trust*.

    Only ``PASS`` qualifies. ``NOT_APPLICABLE`` (capability not exercised) is
    NOT trusted, which is exactly why it cannot be reached by negating
    ``is_not_safe``. This is the positive half of the block/trust pair every
    downstream consumer should key off, so none re-derives the foot-gun. Accepts
    the enum or its serialized value.
    """
    return _coerce(verdict) is TrustVerdict.PASS
