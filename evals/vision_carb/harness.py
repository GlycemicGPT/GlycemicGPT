#!/usr/bin/env python3
"""Vision carb-estimation accuracy harness.

Runs a known-label food image set through an OpenAI-compatible chat-completions
endpoint, parses the structured carb estimate, and reports accuracy.

It talks OpenAI multimodal (`image_url` data URLs) on purpose: the GlycemicGPT
sidecar speaks that dialect for cloud Claude vision today, and a local vision
model served by Ollama speaks the same dialect. So the local-model benchmark
runs local models by pointing `--base-url` / `--model` at Ollama and reusing this
harness verbatim -- the eval set and metric are identical, so cloud and local
numbers are directly comparable.

Usage (cloud, via the sidecar):
    SIDECAR_API_KEY=... python evals/vision_carb/harness.py \\
        --base-url http://localhost:3456 --model claude-sonnet-4-5

Usage (local model benchmark):
    python evals/vision_carb/harness.py \\
        --base-url http://localhost:11434 --model llava:13b --no-auth

No third-party dependencies -- standard library only.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contract  # noqa: E402
import metrics  # noqa: E402

_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

_RETRYABLE = {429, 500, 502, 503, 504, 529}


def _media_type(path: Path) -> str:
    return _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{_media_type(path)};base64,{encoded}"


def _build_request_body(model: str, data_url: str, max_tokens: int) -> dict:
    return {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": contract.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": contract.USER_PROMPT},
                ],
            },
        ],
    }


def _post_chat(
    base_url: str,
    api_key: str | None,
    body: dict,
    timeout: float,
    max_attempts: int = 4,
) -> str:
    """POST to /v1/chat/completions with bounded retries; return assistant text."""
    url = base_url.rstrip("/") + "/v1/chat/completions"
    payload = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    backoff = 1.0
    last_err = "unknown error"
    for attempt in range(1, max_attempts + 1):
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.load(resp)
            try:
                return data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise RuntimeError(f"unexpected response format: {exc}") from exc
        except urllib.error.HTTPError as exc:
            last_err = f"HTTP {exc.code}"
            if exc.code in _RETRYABLE and attempt < max_attempts:
                time.sleep(backoff)
                backoff = min(backoff * 2, 16.0)
                continue
            body_text = exc.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"{last_err}: {body_text}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_err = str(exc)
            if attempt < max_attempts:
                time.sleep(backoff)
                backoff = min(backoff * 2, 16.0)
                continue
            raise RuntimeError(last_err) from exc
    raise RuntimeError(last_err)


def run(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    manifest = json.loads(manifest_path.read_text())
    images_dir = (
        Path(args.images_dir) if args.images_dir else manifest_path.parent / "images"
    )
    api_key = None if args.no_auth else os.environ.get("SIDECAR_API_KEY")

    items = manifest.get("items", [])
    if args.limit:
        items = items[: args.limit]
    if not items:
        print("No items in manifest; nothing to evaluate.", file=sys.stderr)
        return 2

    print(
        f"Evaluating {len(items)} item(s) against {args.base_url} "
        f"(model={args.model})\n",
        file=sys.stderr,
    )

    scores: list[metrics.ItemScore] = []
    records: list[dict] = []
    safety_violations: list[dict] = []

    for idx, item in enumerate(items, 1):
        item_id = item.get("id", f"item-{idx}")
        try:
            truth = float(item["known_carbs_grams"])
        except (KeyError, TypeError, ValueError):
            truth = -1.0
        # A legitimate 0-carb food (e.g. eggs, plain meat) is valid; only a
        # missing or negative label is bad (missing coerces to -1.0 above).
        if truth < 0:
            print(f"[{idx}/{len(items)}] {item_id} ... BAD LABEL", file=sys.stderr)
            records.append(
                {
                    "id": item_id,
                    "error": "known_carbs_grams missing or negative",
                }
            )
            continue
        image_name = item.get("image")
        if not image_name:
            print(f"[{idx}/{len(items)}] {item_id} ... NO IMAGE FIELD", file=sys.stderr)
            scores.append(
                metrics.score_item(
                    item_id, truth, None, None, None, note="no image field"
                )
            )
            records.append({"id": item_id, "error": "manifest item is missing 'image'"})
            continue
        # Constrain to a bare filename inside images_dir: a crafted manifest must
        # not be able to read arbitrary files via "../" or an absolute path.
        if Path(image_name).name != image_name:
            print(
                f"[{idx}/{len(items)}] {item_id} ... UNSAFE IMAGE PATH", file=sys.stderr
            )
            records.append(
                {
                    "id": item_id,
                    "error": "image must be a bare filename (no path components)",
                }
            )
            continue
        image_path = images_dir / image_name
        print(
            f"[{idx}/{len(items)}] {item_id} ...", file=sys.stderr, end=" ", flush=True
        )

        if not image_path.exists():
            print("MISSING IMAGE", file=sys.stderr)
            scores.append(
                metrics.score_item(
                    item_id, truth, None, None, None, note="image not found"
                )
            )
            records.append({"id": item_id, "error": f"image not found: {image_path}"})
            continue

        try:
            body = _build_request_body(
                args.model, _data_url(image_path), args.max_tokens
            )
            raw = _post_chat(args.base_url, api_key, body, args.timeout)
        except RuntimeError as exc:
            print(f"REQUEST FAILED ({exc})", file=sys.stderr)
            scores.append(
                metrics.score_item(item_id, truth, None, None, None, note=str(exc))
            )
            records.append({"id": item_id, "error": str(exc)})
            continue

        est = contract.parse_estimate(raw)
        score = metrics.score_item(
            item_id,
            truth,
            est.carbs_low,
            est.carbs_high,
            est.confidence,
            note=est.parse_error or "",
        )
        scores.append(score)

        if est.dosing_violations:
            safety_violations.append({"id": item_id, "phrases": est.dosing_violations})

        ae = f"{score.abs_error:.1f}g" if score.abs_error is not None else "n/a"
        rng = (
            f"{est.carbs_low:.0f}-{est.carbs_high:.0f}g"
            if est.carbs_low is not None
            else "no-range"
        )
        print(
            f"truth={truth:.0f}g pred={rng} AE={ae} conf={est.confidence}",
            file=sys.stderr,
        )

        records.append(
            {
                "id": item_id,
                "truth_grams": truth,
                "predicted_low": est.carbs_low,
                "predicted_high": est.carbs_high,
                "midpoint": est.midpoint,
                "abs_error": score.abs_error,
                "covered": score.covered,
                "confidence": est.confidence,
                "food_description": est.food_description,
                "parse_ok": est.parse_ok,
                "dosing_violations": est.dosing_violations,
                "label_basis": item.get("label_basis"),
            }
        )

    agg = metrics.aggregate(scores)
    report = {
        "manifest": str(manifest_path),
        "base_url": args.base_url,
        "model": args.model,
        "aggregate": agg.to_dict(),
        "safety": {
            "dosing_violation_count": len(safety_violations),
            "violations": safety_violations,
        },
        "items": records,
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(report, indent=2))
    (out_dir / "summary.md").write_text(_render_markdown(report))

    _print_summary(report)
    return 0


def _render_markdown(report: dict) -> str:
    agg = report["aggregate"]
    lines = [
        "# Vision carb-estimation eval results",
        "",
        f"- **Model:** `{report['model']}`",
        f"- **Endpoint:** `{report['base_url']}`",
        f"- **Items scored:** {agg['n_scored']} / {agg['n_total']}",
        "",
        "## Headline accuracy",
        "",
        f"- **MAE (mean absolute error): {agg['mae_grams']} g** -- the go/no-go number",
        f"- Median absolute error: {agg['median_ae_grams']} g",
        f"- MAPE (mean absolute % error): {agg['mape_pct']} %",
        "",
        "## Range + confidence quality",
        "",
        f"- Range coverage (truth inside predicted range): {_pct(agg['coverage_rate'])}",
        f"- Within +/-10 g: {_pct(agg['within_10g_rate'])}",
        f"- Within +/-15 g: {_pct(agg['within_15g_rate'])}",
        f"- Within +/-20 g: {_pct(agg['within_20g_rate'])}",
        f"- Mean range width: {agg['mean_range_width_g']} g "
        f"(median {agg['median_range_width_g']} g)",
        "",
        "### By confidence level",
        "",
        "| confidence | n | MAE (g) | coverage |",
        "| --- | --- | --- | --- |",
    ]
    for level, stats in agg["by_confidence"].items():
        lines.append(
            f"| {level} | {stats['n']} | {stats['mae_grams']} | {_pct(stats['coverage_rate'])} |"
        )
    safety = report["safety"]
    lines += [
        "",
        "## Safety (descriptive, never advisory)",
        "",
        f"- Dosing/advice-language violations: **{safety['dosing_violation_count']}** "
        "(must be 0)",
        "",
        "## Per-item",
        "",
        "| id | truth (g) | predicted (g) | AE (g) | covered | conf |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in report["items"]:
        if "error" in r:
            lines.append(f"| {r['id']} | - | ERROR | - | - | - |")
            continue
        pred = (
            f"{r['predicted_low']:.0f}-{r['predicted_high']:.0f}"
            if r.get("predicted_low") is not None
            else "n/a"
        )
        ae = f"{r['abs_error']:.1f}" if r.get("abs_error") is not None else "n/a"
        cov = (
            "yes"
            if r.get("covered")
            else ("no" if r.get("covered") is not None else "-")
        )
        lines.append(
            f"| {r['id']} | {r['truth_grams']:.0f} | {pred} | {ae} | {cov} | {r.get('confidence')} |"
        )
    lines.append("")
    return "\n".join(lines)


def _pct(value: float | None) -> str:
    return f"{value * 100:.0f}%" if value is not None else "n/a"


def _print_summary(report: dict) -> None:
    agg = report["aggregate"]
    print("\n" + "=" * 60)
    print("VISION CARB ESTIMATION -- ACCURACY SUMMARY")
    print("=" * 60)
    print(f"  model:            {report['model']}")
    print(f"  items scored:     {agg['n_scored']} / {agg['n_total']}")
    print(f"  MAE (grams):      {agg['mae_grams']}   <-- go/no-go number")
    print(f"  median AE (g):    {agg['median_ae_grams']}")
    print(f"  MAPE (%):         {agg['mape_pct']}")
    print(f"  range coverage:   {_pct(agg['coverage_rate'])}")
    print(f"  within +/-15 g:   {_pct(agg['within_15g_rate'])}")
    print(f"  mean range width: {agg['mean_range_width_g']} g")
    print(
        f"  dosing violations:{report['safety']['dosing_violation_count']}  (must be 0)"
    )
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).parent
    parser.add_argument("--manifest", default=str(here / "dataset" / "manifest.json"))
    parser.add_argument(
        "--images-dir", default=None, help="defaults to <manifest dir>/images"
    )
    parser.add_argument(
        "--base-url", default=os.environ.get("SIDECAR_URL", "http://localhost:3456")
    )
    parser.add_argument("--model", default="claude-sonnet-4-5")
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--limit", type=int, default=0, help="evaluate only the first N items"
    )
    parser.add_argument("--out-dir", default=str(here / "results"))
    parser.add_argument(
        "--no-auth",
        action="store_true",
        help="omit the bearer token (e.g. local Ollama)",
    )
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
