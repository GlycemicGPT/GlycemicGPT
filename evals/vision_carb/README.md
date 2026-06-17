# Vision carb-estimation eval harness

A small, dependency-free harness for Meal Intelligence (vision carb estimation).
It runs food photos with **known** carbohydrate labels through a vision model and
reports both **accuracy** (how close the estimate is to the truth) and, more
importantly, **reproducibility** — the run-to-run variance and food-identity
error that average accuracy is blind to. Average accuracy alone is an optimistic,
incomplete safety signal; a model that is right on average but swings wildly
photo-to-photo, or is confidently wrong about the food, is the one that causes
acute harm. See `FINDINGS.md`.

It is a reusable AI evaluation framework: a dataset → runner → metric → report
pipeline. The local-model benchmark reuses it **verbatim** to benchmark local
vision models on variance, so the harness, dataset format, and metric are
intentionally model-agnostic.

## Modes

- **single-shot** (default): one estimate per image — the accuracy block (MAE /
  coverage / tolerance). Cloud and local single-shot numbers stay comparable.
- **`--repeats N`**: sample each image N times and report variance (CV, per-image
  spread, illustrative worst-case swing) and food-identity error, alongside MAE.
- **`--sweep 1,3,5`**: score variance at each N from **one** max-N sampling
  (prefix-scored) — the variance-vs-cost curve, at the cost of a single max-N run.

## Why it speaks OpenAI multimodal

The runner POSTs OpenAI-style `image_url` chat completions to whatever
`--base-url` you give it:

- **Cloud:** point it at the GlycemicGPT sidecar, which routes the
  request to the active provider's sanctioned vision mechanism (Anthropic
  Messages API for an API key; the official Claude/Codex CLI for a subscription).
- **Local:** point it at Ollama (`--base-url http://localhost:11434
  --model llava:13b --no-auth`). Same request, same metric → directly comparable
  numbers.

## Layout

```text
contract.py        # estimate JSON shape, the descriptive (mirror-not-advisor)
                   # prompt, the parser, and the no-dosing safety scan
metrics.py         # accuracy (MAE/coverage/tolerance) + variance (CV, spread,
                   # worst-case swing, identity error) scoring
harness.py         # the runner CLI (single-shot / --repeats / --sweep; stdlib only)
dataset/
  manifest.json    # committed: easy known-label set + provenance + expected_identity
  adversarial.json # committed: look-alike / systematically-hard set (images not committed)
  images/          # gitignored: downloaded locally (licensing / PHI)
results/           # gitignored: run outputs (results.json + summary.md)
tests/             # unit tests for contract.py, metrics.py, harness.py, datasets
```

## Dataset format

`dataset/manifest.json`:

```json
{
  "name": "...",
  "set": "easy",
  "items": [
    {
      "id": "banana-medium",
      "image": "banana-medium.jpg",
      "known_carbs_grams": 27,
      "expected_identity": ["banana"],
      "label_basis": "USDA FDC #1102653, medium banana (118 g)",
      "portion_note": "one medium banana",
      "source_url": "https://...",
      "license": "..."
    }
  ]
}
```

`known_carbs_grams` is the ground truth. `label_basis` documents where it came
from and any portion assumption — vision accuracy is only meaningful against an
honest label. `expected_identity` is a **synonym list** for the correct food
(a short name like "donut" must not score as a misID against "glazed doughnut"),
used to measure gross identity error.

The adversarial set (`dataset/adversarial.json`, `"set": "adversarial"`) adds
look-alike / systematically-hard foods. Each item also carries `confused_with`
(the look-alike), `failure_mode`, and an `image_todo` (its image is **not
committed** — source a license-clean one before a run). An item with no honest
single carb value is marked `"ambiguous": true` and is scored for variance /
identity only, never MAE.

## Running

```bash
# Cloud single-shot accuracy, through the sidecar (image requests route to the
# active provider's sanctioned vision mechanism).
SIDECAR_API_KEY=<key> python evals/vision_carb/harness.py \
    --base-url http://localhost:3456 --model claude-sonnet-4-5

# Variance on the full set (easy + adversarial look-alikes), N=3:
SIDECAR_API_KEY=<key> python evals/vision_carb/harness.py \
    --manifest dataset/manifest.json dataset/adversarial.json --repeats 3

# The N=1/3/5 variance-vs-cost sweep (one max-N sampling):
SIDECAR_API_KEY=<key> python evals/vision_carb/harness.py \
    --manifest dataset/manifest.json dataset/adversarial.json --sweep 1,3,5

# Local model benchmark (benchmark at N >= 5 -- see FINDINGS.md)
python evals/vision_carb/harness.py \
    --base-url http://localhost:11434 --model llava:13b --no-auth --repeats 5
```

Outputs `results/results.json` and `results/summary.md`, and prints a summary to
stderr. The variance run needs the adversarial images sourced first:
`python evals/vision_carb/fetch_images.py --manifest dataset/adversarial.json`.

## Metrics

Accuracy (single-shot block):

- **MAE (mean absolute error, grams)** — error of the estimate midpoint vs. the
  known label.
- **Range coverage** / **within ±10/15/20 g** / **mean range width** — range
  quality (a 0–200 g range covers everything and means nothing).
- **Per-confidence breakdown** — whether the model's self-reported confidence
  tracks its accuracy (the research finding: it doesn't — hence variance below).

Variance / reproducibility block (`--repeats` / `--sweep`):

- **Coefficient of variation (CV)** — run-to-run dispersion of the per-run
  midpoints. The validated uncertainty signal.
- **Per-image spread** (max − min) and **illustrative worst-case insulin swing**
  (spread ÷ a fixed carb ratio) — the swing is an **analysis device only**, never
  a dose.
- **Food-identity error rate** — how often the model's majority-identified food
  is the wrong food vs the known identity; plus run-to-run identity disagreement.
- **Partial-failure flag** — metrics computed on the samples that succeeded; the
  shortfall is reported.

Safety (every mode):

- **Dosing-violation count** — must be 0. The output describes food, never a dose.

## Safety

Estimates are descriptive nutrition observations, never dosing guidance. The
prompt forbids insulin/dose/units phrasing and the parser scans every response
for it; any hit is a violation. No estimate here flows into IoB,
`treatment_safety`, or any carb-ratio math.

## Running the unit tests

```bash
python -m pytest evals/vision_carb/tests/ -q
```
