"""Architecture lock (one Python brain): the Node sidecar is a dumb transport we
benchmark THROUGH, never a place scorers live.

Reimplementing a scorer/floor/verdict in TypeScript forks the safety floor — the
exact failure this kernel exists to prevent (two definitions of "unsafe" that can
silently disagree). This guard fails if the sidecar grows any of the Python
scoring/floor/verdict surface, complementing the documented convention in
``docs/trust-kernel-architecture.md``.
"""

from __future__ import annotations

from pathlib import Path

_SIDECAR_SRC = Path(__file__).resolve().parents[4] / "sidecar" / "src"

# The whole JS/TS source family — a forked scorer in any of these (the sidecar is
# an ESM package, so .mjs/.js are valid source) must not slip the guard.
_SOURCE_GLOBS = ("*.ts", "*.tsx", "*.mts", "*.cts", "*.js", "*.mjs", "*.cjs")

# Tokens that should appear ONLY in the Python brain. Their presence in the
# sidecar means a scorer, the safety floor, the verdict, or the mg/dL↔mmol/L
# factor was ported into the transport — a forbidden fork. (A renamed
# reimplementation could still evade a token scan; this is a heuristic backstop to
# the documented convention in docs/trust-kernel-architecture.md, not a proof.)
_FORBIDDEN_TOKENS = (
    "validate_ai_suggestion",
    "find_prescriptive_dose_instructions",
    "find_dosing_violations",
    "SafetyVerdict",
    "TrustVerdict",
    "aggregate_verdict",
    "score_safety",
    "score_dose_numbers",
    "18.0156",  # the glucose mass↔molarity factor — a forked threshold
)


def test_sidecar_does_not_reimplement_python_scorers() -> None:
    # Fail (don't skip) if the path drifts — a silent skip would read green and
    # remove the architecture lock the moment the sidecar is relocated.
    assert _SIDECAR_SRC.is_dir(), (
        f"expected the sidecar transport sources at {_SIDECAR_SRC}; if the sidecar "
        "moved, update this guard rather than letting the architecture lock lapse."
    )

    offenders: list[str] = []
    for pattern in _SOURCE_GLOBS:
        for src_file in sorted(_SIDECAR_SRC.rglob(pattern)):
            text = src_file.read_text(encoding="utf-8", errors="replace")
            for token in _FORBIDDEN_TOKENS:
                if token in text:
                    offenders.append(
                        f"{src_file.relative_to(_SIDECAR_SRC)} :: {token!r}"
                    )

    assert not offenders, (
        "The sidecar is a dumb transport — scorers, the safety floor, and the "
        "trust verdict must never be reimplemented in TypeScript (that forks the "
        "floor the benchmark certifies). Found:\n  " + "\n  ".join(offenders)
    )
