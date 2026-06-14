# Vision carb-estimation eval harness

A small, dependency-free accuracy harness for Meal Intelligence (vision carb
estimation). It runs a set of food photos with **known** carbohydrate labels
through a vision model and reports how close the model's carb estimate is to the
truth. This is the go/no-go signal for building the feature.

It is a reusable AI evaluation framework: a dataset → runner → metric → report
pipeline. The local-model benchmark reuses it **verbatim** to benchmark local
vision models, so the harness, dataset format, and metric are intentionally
model-agnostic.

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
contract.py     # estimate JSON shape, the descriptive (mirror-not-advisor)
                # prompt, the parser, and the no-dosing safety scan
metrics.py      # MAE / coverage / tolerance / per-confidence scoring
harness.py      # the runner CLI (stdlib only)
dataset/
  manifest.json # committed: known-label items + provenance (ground truth)
  images/       # gitignored: downloaded locally (licensing / PHI)
results/        # gitignored: run outputs (results.json + summary.md)
tests/          # unit tests for contract.py + metrics.py
```

## Dataset format

`dataset/manifest.json`:

```json
{
  "name": "...",
  "items": [
    {
      "id": "banana-medium",
      "image": "banana-medium.jpg",
      "known_carbs_grams": 27,
      "label_basis": "USDA FDC #1102653, medium banana (118 g)",
      "portion_note": "one medium banana",
      "source_url": "https://...",
      "license": "..."
    }
  ]
}
```

`known_carbs_grams` is the ground truth. `label_basis` documents where it came
from (packaged label, USDA FoodData Central, or a brand's published nutrition)
and any portion assumption — vision accuracy is only meaningful against an
honest label.

## Running

```bash
# Cloud, through the sidecar (text-only behavior of the sidecar is unchanged;
# image requests route to the active provider's sanctioned vision mechanism).
SIDECAR_API_KEY=<key> python evals/vision_carb/harness.py \
    --base-url http://localhost:3456 --model claude-sonnet-4-5

# Local model
python evals/vision_carb/harness.py \
    --base-url http://localhost:11434 --model llava:13b --no-auth
```

Outputs `results/results.json` and `results/summary.md`, and prints the headline
MAE to stderr.

## Metrics

- **MAE (mean absolute error, grams)** — the headline accuracy number, error of
  the estimate midpoint vs. the known label.
- **Range coverage** — how often the true value lands inside the predicted
  low–high range (a range product must usually contain the truth).
- **Within ±10/15/20 g** — clinically legible accuracy bands.
- **Mean range width** — keeps coverage honest (a 0–200 g range covers
  everything and means nothing).
- **Per-confidence breakdown** — whether the model's confidence signal tracks
  its accuracy.
- **Dosing-violation count** — must be 0. The output describes food, never a
  dose (the feature's safety posture).

## Safety

Estimates are descriptive nutrition observations, never dosing guidance. The
prompt forbids insulin/dose/units phrasing and the parser scans every response
for it; any hit is a violation. No estimate here flows into IoB,
`treatment_safety`, or any carb-ratio math.

## Running the unit tests

```bash
python -m pytest evals/vision_carb/tests/ -q
```
