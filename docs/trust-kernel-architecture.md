# Trust kernel architecture

The trust kernel is what turns the offline safety benchmarks from a developer CLI
into something the product can rely on: one shared, content-versioned verdict that
cannot drift from what production actually does to a patient's data, plus a CI
gate that catches a prompt or scorer change silently flipping a verdict.

## One Python brain

There is exactly **one** place that decides whether a model's output is safe: the
Python scoring layer.

- **Text surfaces** — `apps/api/benchmarks/` scores model output against the *real*
  production prompts (the live `build_meal_prompt` / `build_analysis_prompt` /
  `build_correction_prompt` / chat prompt builders), the *real*
  `validate_ai_suggestion` floor, and the shared prescriptive-dose helper.
- **Vision** — `evals/vision_carb/` scores carb-photo estimates against the real
  `src/vision/carb_contract.py` prompt + dosing scanner, behind the pass-bar.

Both map to a single shared verdict vocabulary, `src/core/trust.py::TrustVerdict`
(`PASS`, `FAIL`, `INCOMPLETE`, `NOT_APPLICABLE`). `INCOMPLETE` and `FAIL` both gate
as not-safe (fail-closed); `NOT_APPLICABLE` is excluded from the gate (the
capability was not exercised) and is reserved for the forthcoming capability
matrix.

## The sidecar is a dumb transport — never a scorer

The Node sidecar (`sidecar/`) exists to *carry* requests to model providers. We
benchmark *through* it (`POST /v1/chat/completions`); we never score *in* it.

**A scorer, the safety floor, or the verdict must never be reimplemented in
TypeScript.** Doing so forks the floor — two definitions of "unsafe" that can
silently disagree — which is the exact failure this kernel exists to prevent. If a
runtime path needs a safety decision, it calls the Python brain; it does not grow
its own copy.

**The primary lock is this reviewed convention** — a sidecar change that adds
scoring logic should be rejected in code review. As a backstop,
`apps/api/tests/benchmarks/test_architecture_lock.py` scans `sidecar/src` (the
whole JS/TS family) and fails CI if any Python scorer / floor / verdict symbol (or
the mg/dL↔mmol/L factor) appears there. The scan is a heuristic, not a proof: a
renamed or rewritten reimplementation could evade a string match, so it raises the
bar but does not replace review. (A full structural/AST check would be
disproportionate for a transport this small; if the sidecar ever grows real logic,
revisit.)

## Content versioning and the CI gate

`compute_harness_version(surface)` is a per-surface `sha256` over the rendered
production prompts + the scorer source + the safety thresholds + the production
floor revision + a digest of the scenario/dataset manifest (refs only for the
license-encumbered vision images — never raw bytes). It is stamped into every
report so a cached or persisted verdict can be content-invalidated.

The expected versions are committed in `apps/api/benchmarks/harness_versions.json`
(the lock). CI recomputes and compares; a change that lands without re-recording
fails the gate. After an *intentional* change, re-record (the "bump"):

Both commands below are run from the repo root (the text one uses a subshell so
its `cd` does not leak into the next command):

```bash
# text surfaces
(cd apps/api && uv run python -m benchmarks.core.version --update-lock)
# vision surface
uv run --project apps/api python evals/vision_carb/harness_version.py --update-lock
```

Scoping is per-surface for prompt/dataset edits (a meal-prompt edit invalidates
only `meal_analysis`); shared inputs — the scorers, the floor, the thresholds —
invalidate every surface, because they determine every surface's verdict.
