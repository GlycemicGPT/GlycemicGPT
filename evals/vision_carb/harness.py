#!/usr/bin/env python3
"""Vision carb-estimation accuracy + reproducibility harness.

Runs a known-label food image set through an OpenAI-compatible chat-completions
endpoint, parses the structured carb estimate, and reports accuracy *and*
run-to-run variance.

It talks OpenAI multimodal (`image_url` data URLs) on purpose: the GlycemicGPT
sidecar speaks that dialect for cloud Claude vision today, and a local vision
model served by Ollama speaks the same dialect. So the local-model benchmark
runs local models by pointing `--base-url` / `--model` at Ollama and reusing this
harness verbatim -- the eval set and metric are identical, so cloud and local
numbers are directly comparable.

Three modes:
  * single-shot (default): one estimate per image -- the original accuracy
    number (MAE / coverage / tolerance). Cloud and local single-shot numbers are
    directly comparable because this path is unchanged.
  * `--repeats N`: sample each image N times and report reproducibility
    (coefficient of variation, per-image spread, illustrative worst-case swing)
    and food-identity error, alongside MAE. Average accuracy hides the
    photo-to-photo swing that drives acute-hypo risk; this surfaces it.
  * `--sweep 1,3,5`: sample each image at the largest N once, then score variance
    at each N from the prefix -- the variance-vs-cost curve that tunes the
    production sample count, at the cost of a single max-N sampling.

Usage (cloud single-shot, via the sidecar):
    SIDECAR_API_KEY=... python evals/vision_carb/harness.py \\
        --base-url http://localhost:3456 --model claude-sonnet-4-5

Usage (variance, full set incl. adversarial look-alikes, N=3):
    SIDECAR_API_KEY=... python evals/vision_carb/harness.py \\
        --manifest dataset/manifest.json dataset/adversarial.json --repeats 3

Usage (N sweep for tuning the production sample count):
    SIDECAR_API_KEY=... python evals/vision_carb/harness.py \\
        --manifest dataset/manifest.json dataset/adversarial.json --sweep 1,3,5

Usage (local model certification benchmark -- gate on the pass-bar at N>=5):
    python evals/vision_carb/harness.py \\
        --base-url http://localhost:11434 --model llava:13b --no-auth \\
        --manifest dataset/manifest.json dataset/adversarial.json \\
        --repeats 5 --enforce-pass-bar

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
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contract  # noqa: E402
import metrics  # noqa: E402
import passbar  # noqa: E402

_HERE = Path(__file__).parent
_DEFAULT_MANIFEST = _HERE / "dataset" / "manifest.json"

_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

_RETRYABLE = {429, 500, 502, 503, 504, 529}

# The pass-bar gates a model on the EASY set (a simple, single food is where a
# model has no excuse). The adversarial set is reported for guidance only. These
# are the canonical set names the dataset manifests carry.
_EASY_SET_NAME = "easy"
_ADVERSARIAL_SET_NAME = "adversarial"


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


def _sample_image_n(
    base_url: str,
    api_key: str | None,
    body: dict,
    timeout: float,
    n: int,
) -> list[str | None]:
    """POST the same image request ``n`` times; one entry per attempt.

    A failed attempt is recorded as ``None`` rather than aborting the item, so
    the variance metrics are computed on whatever samples succeeded and the
    shortfall is flagged (partial-failure handling). N independent requests of
    the *same* image are how the model's run-to-run distribution is observed --
    the only validated uncertainty signal.
    """
    raws: list[str | None] = []
    for _ in range(n):
        try:
            raws.append(_post_chat(base_url, api_key, body, timeout))
        except RuntimeError:
            raws.append(None)
    return raws


# ---------------------------------------------------------------------------
# Item loading / preflight (shared by every mode)
# ---------------------------------------------------------------------------


@dataclass
class LoadedItem:
    """One manifest item plus the set it came from and where its image lives."""

    raw: dict
    set_name: str
    images_dir: Path

    @property
    def item_id(self) -> str:
        return self.raw.get("id", "unknown")


def _manifest_paths(args: argparse.Namespace) -> list[str]:
    """The manifests to evaluate (the default easy set when none is given)."""
    return args.manifest or [str(_DEFAULT_MANIFEST)]


def _resolve_manifest_path(raw_path: str) -> Path:
    """Resolve a manifest path, falling back to one relative to this script.

    So a documented command run from the repo root (``--manifest
    dataset/manifest.json``) works even though that path is relative to the
    harness directory, not the caller's cwd. If neither location exists, the
    original path is returned so the resulting error names what the user typed.
    """
    direct = Path(raw_path)
    if direct.exists():
        return direct
    fallback = _HERE / raw_path
    return fallback if fallback.exists() else direct


def _load_items(args: argparse.Namespace) -> list[LoadedItem]:
    """Load and concatenate every requested manifest, tagging each item's set."""
    loaded: list[LoadedItem] = []
    for raw_path in _manifest_paths(args):
        manifest_path = _resolve_manifest_path(raw_path)
        manifest = json.loads(manifest_path.read_text())
        # A manifest may name its set ("easy"/"adversarial"); else use the file
        # stem so per-set reporting still distinguishes them.
        set_name = manifest.get("set") or manifest_path.stem
        images_dir = (
            Path(args.images_dir)
            if args.images_dir
            else manifest_path.parent / "images"
        )
        for item in manifest.get("items", []):
            loaded.append(
                LoadedItem(
                    raw=item,
                    set_name=item.get("set") or set_name,
                    images_dir=images_dir,
                )
            )
    if args.limit:
        loaded = loaded[: args.limit]
    return loaded


def _item_truth(raw: dict) -> tuple[float | None, bool, bool]:
    """Return ``(truth_grams, ambiguous, bad_label)`` for an item.

    An ``ambiguous`` item (a mixed plate with no single honest carb value) has no
    truth and is scored for variance/identity only, never MAE. A 0-carb food
    (eggs, plain meat) is valid; only a missing or negative label is bad.
    """
    if raw.get("ambiguous"):
        return None, True, False
    try:
        truth = float(raw["known_carbs_grams"])
    except (KeyError, TypeError, ValueError):
        return None, False, True
    if truth < 0:
        return None, False, True
    return truth, False, False


def _resolve_image(raw: dict, images_dir: Path) -> tuple[Path | None, str | None]:
    """Resolve an item's image path, or return an error string.

    Constrains the image to a bare filename inside ``images_dir`` so a crafted
    manifest cannot read arbitrary files via "../" or an absolute path.
    """
    image_name = raw.get("image")
    if not image_name:
        return None, "manifest item is missing 'image'"
    # Reject path components and the "."/".." specials (Path("..").name == "..",
    # which would otherwise slip the bare-filename check and read a directory).
    if image_name in (".", "..") or Path(image_name).name != image_name:
        return None, "image must be a bare filename (no path components)"
    path = images_dir / image_name
    if not path.is_file():
        return None, f"image not found: {path}"
    return path, None


def _sample_in_bounds(est: contract.ParsedEstimate) -> bool:
    """True when a parsed sample has a present, in-absolute-bounds carb range."""
    low, high = est.carbs_low, est.carbs_high
    return (
        low is not None
        and high is not None
        and contract.CARB_GRAMS_MIN <= low <= high <= contract.CARB_GRAMS_MAX
    )


# ---------------------------------------------------------------------------
# Single-shot mode (unchanged accuracy numbers, kept cloud/local comparable)
# ---------------------------------------------------------------------------


def _run_single_shot(
    args: argparse.Namespace, items: list[LoadedItem], api_key: str | None
) -> int:
    scores: list[metrics.ItemScore] = []
    records: list[dict] = []
    safety_violations: list[dict] = []

    for idx, loaded in enumerate(items, 1):
        item = loaded.raw
        item_id = loaded.item_id
        truth, ambiguous, bad_label = _item_truth(item)
        if bad_label:
            print(f"[{idx}/{len(items)}] {item_id} ... BAD LABEL", file=sys.stderr)
            records.append(
                {"id": item_id, "error": "known_carbs_grams missing or negative"}
            )
            continue
        if ambiguous:
            # No honest truth to score against; single-shot accuracy mode skips
            # ambiguous items (they are for the variance/identity modes).
            print(
                f"[{idx}/{len(items)}] {item_id} ... AMBIGUOUS (skipped)",
                file=sys.stderr,
            )
            records.append({"id": item_id, "error": "ambiguous item: variance-only"})
            continue

        image_path, image_error = _resolve_image(item, loaded.images_dir)
        if image_error:
            print(f"[{idx}/{len(items)}] {item_id} ... {image_error}", file=sys.stderr)
            # Preserve the original score/record behavior: a missing image field
            # or a not-found image is a scoreable miss; an unsafe path is not.
            if "bare filename" not in image_error:
                note = (
                    "no image field"
                    if "missing 'image'" in image_error
                    else "image not found"
                )
                scores.append(
                    metrics.score_item(item_id, truth, None, None, None, note=note)
                )
            records.append({"id": item_id, "error": image_error})
            continue

        assert truth is not None  # bad_label/ambiguous handled above
        print(
            f"[{idx}/{len(items)}] {item_id} ...", file=sys.stderr, end=" ", flush=True
        )
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
        # Reject-not-clamp, identical to the variance path's per-sample filter:
        # a parseable but out-of-absolute-bounds estimate (parse_estimate enforces
        # the floor but not the CARB_GRAMS_MAX ceiling) is a non-scored miss, not
        # a score-poisoning point. This keeps single-shot MAE identical to scoring
        # the same output at N=1 through the variance/sweep path (single-shot parity).
        in_bounds = est.parse_ok and _sample_in_bounds(est)
        low = est.carbs_low if in_bounds else None
        high = est.carbs_high if in_bounds else None
        note = est.parse_error or ("" if in_bounds else "estimate out of carb bounds")
        score = metrics.score_item(item_id, truth, low, high, est.confidence, note=note)
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
                "set": loaded.set_name,
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
        "mode": "single_shot",
        "manifests": _manifest_paths(args),
        "base_url": args.base_url,
        "model": args.model,
        "aggregate": agg.to_dict(),
        "safety": {
            "dosing_violation_count": len(safety_violations),
            "violations": safety_violations,
        },
        "items": records,
    }
    _write_report(args, report, _render_single_shot_markdown(report))
    _print_single_shot_summary(report)
    return _exit_code(report)


# ---------------------------------------------------------------------------
# Variance sampling (shared by --repeats and --sweep)
# ---------------------------------------------------------------------------


@dataclass
class ItemSamples:
    """The raw responses collected for one image at the largest requested N."""

    item: LoadedItem
    truth: float | None
    ambiguous: bool
    raws: list[str | None]
    error: str | None


def _collect_samples(
    args: argparse.Namespace,
    items: list[LoadedItem],
    max_n: int,
    api_key: str | None,
) -> list[ItemSamples]:
    """Sample every scoreable image ``max_n`` times (one sampling pass).

    Both --repeats and --sweep score from this single pass: --sweep just scores
    prefixes of it at each N, so the variance-vs-cost curve costs one max-N
    sampling rather than N separate runs.
    """
    collected: list[ItemSamples] = []
    for idx, loaded in enumerate(items, 1):
        item = loaded.raw
        item_id = loaded.item_id
        truth, ambiguous, bad_label = _item_truth(item)
        if bad_label:
            print(f"[{idx}/{len(items)}] {item_id} ... BAD LABEL", file=sys.stderr)
            collected.append(
                ItemSamples(
                    loaded, None, False, [], "known_carbs_grams missing or negative"
                )
            )
            continue
        image_path, image_error = _resolve_image(item, loaded.images_dir)
        if image_error:
            print(f"[{idx}/{len(items)}] {item_id} ... {image_error}", file=sys.stderr)
            collected.append(ItemSamples(loaded, truth, ambiguous, [], image_error))
            continue

        print(
            f"[{idx}/{len(items)}] {item_id} x{max_n} ...",
            file=sys.stderr,
            end=" ",
            flush=True,
        )
        body = _build_request_body(args.model, _data_url(image_path), args.max_tokens)
        raws = _sample_image_n(args.base_url, api_key, body, args.timeout, max_n)
        ok = sum(1 for r in raws if r is not None)
        print(f"{ok}/{max_n} ok", file=sys.stderr)
        collected.append(ItemSamples(loaded, truth, ambiguous, raws, None))
    return collected


def _score_samples_at_n(
    sampled: ItemSamples, n: int, illustrative_icr: float
) -> tuple[metrics.VarianceScore | None, list[str], dict | None]:
    """Score one item's first ``n`` samples; return (score, dosing_phrases, error).

    Returns ``(None, [], error_record)`` for an item that could not be sampled
    (bad label / missing image) so it is reported but excluded from aggregates.
    """
    if sampled.error is not None:
        return None, [], {"id": sampled.item.item_id, "error": sampled.error}

    midpoints: list[float] = []
    descriptions: list[str] = []
    dosing_phrases: list[str] = []
    for raw in sampled.raws[:n]:
        if raw is None:
            continue
        est = contract.parse_estimate(raw)
        if est.dosing_violations:
            dosing_phrases.extend(est.dosing_violations)
        # Drop a hallucinated out-of-range sample so it can't poison the spread
        # (reject-not-clamp, per sample) -- mirrors the production aggregator.
        if est.parse_ok and est.midpoint is not None and _sample_in_bounds(est):
            midpoints.append(est.midpoint)
            descriptions.append(est.food_description)

    score = metrics.score_variance(
        sampled.item.item_id,
        set_name=sampled.item.set_name,
        truth_grams=sampled.truth,
        expected_identity=sampled.item.raw.get("expected_identity"),
        sample_midpoints=midpoints,
        sample_descriptions=descriptions,
        samples_requested=n,
        ambiguous=sampled.ambiguous,
        illustrative_icr=illustrative_icr,
    )
    return score, dosing_phrases, None


def _by_set(
    scores: list[metrics.VarianceScore], repeats: int, illustrative_icr: float
) -> dict:
    """Per-set (easy/adversarial) variance aggregates."""
    sets: dict[str, list[metrics.VarianceScore]] = {}
    for s in scores:
        sets.setdefault(s.set_name, []).append(s)
    return {
        name: metrics.aggregate_variance(
            group, repeats=repeats, illustrative_icr=illustrative_icr
        ).to_dict()
        for name, group in sorted(sets.items())
    }


def evaluate_run_pass_bar(
    scores: list[metrics.VarianceScore],
    *,
    repeats: int,
    dosing_violation_count: int,
    illustrative_icr: float = metrics.DEFAULT_ILLUSTRATIVE_ICR,
) -> passbar.PassBarResult:
    """Apply the local-model pass-bar to a variance run's scores.

    Gates on the EASY-set aggregate (the bar is set where a model has no excuse);
    the adversarial-set aggregate, when present, is passed for the informational
    comparison only. ``has_vision`` is derived from whether any usable sample was
    produced fleet-wide -- a model that returned nothing usable served no vision.
    """
    easy_scores = [s for s in scores if s.set_name == _EASY_SET_NAME]
    adversarial_scores = [s for s in scores if s.set_name == _ADVERSARIAL_SET_NAME]

    easy = (
        metrics.aggregate_variance(
            easy_scores, repeats=repeats, illustrative_icr=illustrative_icr
        )
        if easy_scores
        else None
    )
    adversarial = (
        metrics.aggregate_variance(
            adversarial_scores, repeats=repeats, illustrative_icr=illustrative_icr
        )
        if adversarial_scores
        else None
    )
    # No usable sample anywhere => the model served no vision (or was unreachable).
    has_vision = any(s.samples_ok > 0 for s in scores)

    return passbar.evaluate_pass_bar(
        has_vision=has_vision,
        dosing_violation_count=dosing_violation_count,
        easy=easy,
        repeats=repeats,
        adversarial=adversarial,
    )


# ---------------------------------------------------------------------------
# --repeats mode
# ---------------------------------------------------------------------------


def _run_variance(
    args: argparse.Namespace, items: list[LoadedItem], api_key: str | None
) -> int:
    n = args.repeats
    sampled = _collect_samples(args, items, n, api_key)

    scores: list[metrics.VarianceScore] = []
    records: list[dict] = []
    safety_violations: list[dict] = []
    for s in sampled:
        score, dosing_phrases, error = _score_samples_at_n(s, n, args.illustrative_icr)
        if error is not None:
            records.append(error)
            continue
        assert score is not None
        scores.append(score)
        records.append(score.to_dict())
        if dosing_phrases:
            safety_violations.append({"id": score.item_id, "phrases": dosing_phrases})

    agg = metrics.aggregate_variance(
        scores, repeats=n, illustrative_icr=args.illustrative_icr
    )
    pass_bar = evaluate_run_pass_bar(
        scores,
        repeats=n,
        dosing_violation_count=len(safety_violations),
        illustrative_icr=args.illustrative_icr,
    )
    report = {
        "mode": "variance",
        "manifests": _manifest_paths(args),
        "base_url": args.base_url,
        "model": args.model,
        "repeats": n,
        "illustrative_icr_g_per_u": args.illustrative_icr,
        "variance_aggregate": agg.to_dict(),
        "by_set": _by_set(scores, n, args.illustrative_icr),
        "pass_bar": pass_bar.to_dict(),
        "enforce_pass_bar": bool(args.enforce_pass_bar),
        "safety": {
            "dosing_violation_count": len(safety_violations),
            "violations": safety_violations,
        },
        "items": records,
    }
    _write_report(args, report, _render_variance_markdown(report))
    _print_variance_summary(report)
    return _exit_code(report)


# ---------------------------------------------------------------------------
# --sweep mode
# ---------------------------------------------------------------------------


def _run_sweep(
    args: argparse.Namespace, items: list[LoadedItem], api_key: str | None
) -> int:
    sweep_ns = args.sweep
    max_n = max(sweep_ns)
    sampled = _collect_samples(args, items, max_n, api_key)

    curve: list[dict] = []
    safety_violations: list[dict] = []
    items_at_max: list[dict] = []
    for n in sweep_ns:
        scores: list[metrics.VarianceScore] = []
        for s in sampled:
            score, dosing_phrases, error = _score_samples_at_n(
                s, n, args.illustrative_icr
            )
            if error is not None:
                continue
            assert score is not None
            scores.append(score)
            # Safety is tallied once, on the full (max-N) pass, so a phrase in an
            # early sample is not double-counted across the prefix iterations.
            if n == max_n:
                items_at_max.append(score.to_dict())
                if dosing_phrases:
                    safety_violations.append(
                        {"id": score.item_id, "phrases": dosing_phrases}
                    )
        agg = metrics.aggregate_variance(
            scores, repeats=n, illustrative_icr=args.illustrative_icr
        ).to_dict()
        agg["n"] = n
        # Cost is what a *standalone* run at this N would cost; the sweep itself
        # paid for one max-N sampling and scores prefixes of it.
        agg["requests_per_image_standalone"] = n
        curve.append(agg)
    report = {
        "mode": "sweep",
        "manifests": _manifest_paths(args),
        "base_url": args.base_url,
        "model": args.model,
        "sweep": sweep_ns,
        "max_repeats": max_n,
        "illustrative_icr_g_per_u": args.illustrative_icr,
        "sweep_curve": curve,
        "items_at_max_n": items_at_max,
        "safety": {
            "dosing_violation_count": len(safety_violations),
            "violations": safety_violations,
        },
    }
    _write_report(args, report, _render_sweep_markdown(report))
    _print_sweep_summary(report)
    return _exit_code(report)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _write_report(args: argparse.Namespace, report: dict, markdown: str) -> None:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(report, indent=2))
    (out_dir / "summary.md").write_text(markdown)


# Exit code returned when a run surfaces dosing/advice language in any response.
# Non-zero so the "must be 0" safety check actually gates a scripted/CI run.
_DOSING_VIOLATION_EXIT = 3
# Exit code when a certification run (--enforce-pass-bar) does not return a clean
# PASS, so a benchmark script can gate on "this model cleared the bar".
_PASS_BAR_FAIL_EXIT = 4


def _exit_code(report: dict) -> int:
    """Process exit code for a run.

    A dosing-language violation is the highest-priority failure (it is a safety
    breach in any mode). Otherwise, a variance run invoked with
    ``--enforce-pass-bar`` returns non-zero unless the model cleared the bar
    (verdict ``pass``) -- so the certification command gates the way the dosing
    check does. Without ``--enforce-pass-bar`` the pass-bar is informational only
    and never changes the exit code (existing/cloud runs are unaffected).
    """
    if report["safety"]["dosing_violation_count"]:
        return _DOSING_VIOLATION_EXIT
    if (
        report.get("enforce_pass_bar")
        and report.get("pass_bar", {}).get("verdict") != passbar.Verdict.PASS.value
    ):
        return _PASS_BAR_FAIL_EXIT
    return 0


def _pct(value: float | None) -> str:
    return f"{value * 100:.0f}%" if value is not None else "n/a"


_SWING_DISCLAIMER = (
    "> The illustrative insulin-equivalent swing is an ANALYSIS DEVICE only: a "
    "carb spread divided by a fixed textbook carb ratio, to make a variance "
    "number legible as a potential consequence. It is never a dose, never a "
    "recommendation, and no dosing code reads it. A tight spread on a "
    "systematically-wrong food is still wrong -- consistency is not correctness."
)


def _render_single_shot_markdown(report: dict) -> str:
    agg = report["aggregate"]
    lines = [
        "# Vision carb-estimation eval results (single-shot)",
        "",
        f"- **Model:** `{report['model']}`",
        f"- **Endpoint:** `{report['base_url']}`",
        f"- **Items scored:** {agg['n_scored']} / {agg['n_total']}",
        "",
        "## Headline accuracy",
        "",
        f"- **MAE (mean absolute error): {agg['mae_grams']} g**",
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


def _g(value: float | None) -> str:
    return f"{value:.1f}" if value is not None else "n/a"


def _cv(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "n/a"


def _render_pass_bar_section(pass_bar: dict | None) -> list[str]:
    """Render the local-model pass-bar verdict + per-criterion table."""
    if not pass_bar:
        return []
    lines = [
        "## Local-model pass-bar",
        "",
        f"- **Verdict: {pass_bar['verdict'].upper()}** "
        f"(N={pass_bar['repeats']}, certifies at N>={pass_bar['min_certification_repeats']})",
        f"- {pass_bar['summary']}",
        "",
        "| gate | observed | bar | result |",
        "| --- | --- | --- | --- |",
    ]
    for c in pass_bar["criteria"]:
        result = (
            "PASS"
            if c["passed"] is True
            else ("FAIL" if c["passed"] is False else "n/a")
        )
        observed = c["observed"]
        observed_str = "n/a" if observed is None else str(observed)
        lines.append(f"| {c['name']} | {observed_str} | {c['threshold']} | {result} |")
    lines.append("")
    return lines


def _render_variance_markdown(report: dict) -> str:
    agg = report["variance_aggregate"]
    lines = [
        f"# Vision carb-estimation variance results (N={report['repeats']})",
        "",
        f"- **Model:** `{report['model']}`",
        f"- **Endpoint:** `{report['base_url']}`",
        f"- **Samples per image (N):** {report['repeats']}",
        f"- **Items with samples:** {agg['n_with_samples']} / {agg['n_items']}",
        f"- **Illustrative ICR:** {report['illustrative_icr_g_per_u']} g/U "
        "(analysis device only -- see note below)",
        "",
        "## Reproducibility (the headline safety bar)",
        "",
        f"- **Max CV (worst run-to-run dispersion): {_cv(agg['max_cv'])}**",
        f"- Mean CV: {_cv(agg['mean_cv'])} (median {_cv(agg['median_cv'])})",
        f"- **Max per-image spread: {_g(agg['max_spread_g'])} g** "
        f"(mean {_g(agg['mean_spread_g'])} g)",
        f"- Max illustrative insulin-equivalent swing: "
        f"{_g(agg['max_illustrative_insulin_swing_units'])} U",
        "",
        "## Accuracy (mean estimate vs truth)",
        "",
        f"- MAE: {_g(agg['mae_grams'])} g (median {_g(agg['median_ae_grams'])} g)",
        "",
        "## Identity (misidentification is upstream of carb error)",
        "",
        f"- **Identity-error rate: {_pct(agg['identity_error_rate'])}** "
        f"(measurable on {agg['n_identity_measurable']} items)",
        f"- Run-to-run identity disagreement rate: "
        f"{_pct(agg['identity_disagreement_rate'])}",
        "",
        "## Reliability",
        "",
        f"- Items with a partial sample shortfall: {agg['n_partial_failures']}",
        f"- Usable samples (parsed, in-bounds): {agg['samples_ok_total']} / "
        f"{agg['samples_requested_total']} requested",
        "",
        "## Safety",
        "",
        f"- Dosing/advice-language violations: **{report['safety']['dosing_violation_count']}** "
        "(must be 0)",
        "",
        _SWING_DISCLAIMER,
        "",
    ]
    lines += _render_pass_bar_section(report.get("pass_bar"))
    lines += [
        "## By set",
        "",
        "| set | items | max CV | max spread (g) | id-error | MAE (g) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, stats in report["by_set"].items():
        lines.append(
            f"| {name} | {stats['n_items']} | {_cv(stats['max_cv'])} | "
            f"{_g(stats['max_spread_g'])} | {_pct(stats['identity_error_rate'])} | "
            f"{_g(stats['mae_grams'])} |"
        )
    lines += [
        "",
        "## Per-item",
        "",
        "| id | set | ok/req | CV | spread (g) | swing (U) | MAE (g) | id-error |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in report["items"]:
        if "error" in r:
            lines.append(f"| {r['id']} | - | ERROR | - | - | - | - | - |")
            continue
        id_err = (
            "WRONG"
            if r["identity_error"] is True
            else ("ok" if r["identity_error"] is False else "-")
        )
        lines.append(
            f"| {r['item_id']} | {r['set']} | {r['samples_ok']}/{r['samples_requested']} | "
            f"{_cv(r['cv'])} | {_g(r['spread_g'])} | "
            f"{_g(r['illustrative_insulin_swing_units'])} | {_g(r['mae_grams'])} | "
            f"{id_err} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_sweep_markdown(report: dict) -> str:
    lines = [
        "# Vision carb-estimation N-sweep (variance vs cost)",
        "",
        f"- **Model:** `{report['model']}`",
        f"- **Endpoint:** `{report['base_url']}`",
        f"- **Swept N:** {report['sweep']} (sampled once at N={report['max_repeats']}, "
        "each smaller N scored from the prefix)",
        "",
        "The variance-vs-cost curve that tunes the production sample count. Cost "
        "is what a *standalone* run at each N would cost; this sweep paid for one "
        f"N={report['max_repeats']} sampling. Rows share draws (each N is a prefix "
        "of the same samples), so they are correlated, not independent runs.",
        "",
        "| N | requests/image | max CV | mean CV | max spread (g) | max swing (U) | "
        "id-error | MAE (g) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["sweep_curve"]:
        lines.append(
            f"| {row['n']} | {row['requests_per_image_standalone']} | "
            f"{_cv(row['max_cv'])} | {_cv(row['mean_cv'])} | "
            f"{_g(row['max_spread_g'])} | "
            f"{_g(row['max_illustrative_insulin_swing_units'])} | "
            f"{_pct(row['identity_error_rate'])} | {_g(row['mae_grams'])} |"
        )
    lines += [
        "",
        f"- Dosing/advice-language violations across the sweep: "
        f"**{report['safety']['dosing_violation_count']}** (must be 0)",
        "",
        _SWING_DISCLAIMER,
        "",
    ]
    return "\n".join(lines)


def _print_single_shot_summary(report: dict) -> None:
    agg = report["aggregate"]
    print("\n" + "=" * 60)
    print("VISION CARB ESTIMATION -- ACCURACY SUMMARY (single-shot)")
    print("=" * 60)
    print(f"  model:            {report['model']}")
    print(f"  items scored:     {agg['n_scored']} / {agg['n_total']}")
    print(f"  MAE (grams):      {agg['mae_grams']}")
    print(f"  median AE (g):    {agg['median_ae_grams']}")
    print(f"  range coverage:   {_pct(agg['coverage_rate'])}")
    print(f"  within +/-15 g:   {_pct(agg['within_15g_rate'])}")
    print(
        f"  dosing violations:{report['safety']['dosing_violation_count']}  (must be 0)"
    )
    print("=" * 60)


def _print_variance_summary(report: dict) -> None:
    agg = report["variance_aggregate"]
    print("\n" + "=" * 60)
    print(f"VISION CARB ESTIMATION -- VARIANCE SUMMARY (N={report['repeats']})")
    print("=" * 60)
    print(f"  model:            {report['model']}")
    print(f"  items w/ samples: {agg['n_with_samples']} / {agg['n_items']}")
    print(f"  MAX CV:           {_cv(agg['max_cv'])}   <-- worst dispersion")
    print(f"  mean CV:          {_cv(agg['mean_cv'])}")
    print(f"  MAX spread (g):   {_g(agg['max_spread_g'])}")
    print(f"  identity error:   {_pct(agg['identity_error_rate'])}")
    print(f"  partial failures: {agg['n_partial_failures']}")
    print(
        f"  dosing violations:{report['safety']['dosing_violation_count']}  (must be 0)"
    )
    pass_bar = report.get("pass_bar")
    if pass_bar:
        enforced = " [enforced]" if report.get("enforce_pass_bar") else ""
        print(f"  PASS-BAR:         {pass_bar['verdict'].upper()}{enforced}")
        if pass_bar["failures"]:
            print(f"    failed gates:   {', '.join(pass_bar['failures'])}")
    print("=" * 60)


def _print_sweep_summary(report: dict) -> None:
    print("\n" + "=" * 60)
    print("VISION CARB ESTIMATION -- N-SWEEP (variance vs cost)")
    print("=" * 60)
    print(f"  model: {report['model']}")
    print("  N    max-CV   mean-CV   max-spread(g)   id-error   MAE(g)")
    for row in report["sweep_curve"]:
        print(
            f"  {row['n']:<4} {_cv(row['max_cv']):<8} {_cv(row['mean_cv']):<9} "
            f"{_g(row['max_spread_g']):<15} {_pct(row['identity_error_rate']):<10} "
            f"{_g(row['mae_grams'])}"
        )
    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_sweep(spec: str) -> list[int]:
    """Parse a "1,3,5" sweep spec into a sorted, de-duplicated list of N>=1."""
    values = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        n = int(part)  # ValueError -> caller reports a clean error
        if n < 1:
            raise ValueError(f"sweep N must be >= 1, got {n}")
        values.append(n)
    if not values:
        raise ValueError("sweep spec is empty")
    return sorted(set(values))


def run(args: argparse.Namespace) -> int:
    items = _load_items(args)
    if not items:
        print("No items in manifest(s); nothing to evaluate.", file=sys.stderr)
        return 2
    api_key = None if args.no_auth else os.environ.get("SIDECAR_API_KEY")

    mode = "single-shot"
    if args.sweep:
        mode = f"sweep {args.sweep}"
    elif args.repeats > 1:
        mode = f"variance N={args.repeats}"
    print(
        f"Evaluating {len(items)} item(s) against {args.base_url} "
        f"(model={args.model}, mode={mode})\n",
        file=sys.stderr,
    )

    if args.sweep:
        return _run_sweep(args, items, api_key)
    if args.repeats > 1:
        return _run_variance(args, items, api_key)
    return _run_single_shot(args, items, api_key)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        nargs="+",
        default=None,
        help="one or more manifest paths (default: the v1 easy set). Pass the "
        "adversarial manifest too to run the full set.",
    )
    parser.add_argument(
        "--images-dir",
        default=None,
        help="override image dir for ALL manifests (default: each manifest's images/)",
    )
    parser.add_argument(
        "--base-url", default=os.environ.get("SIDECAR_URL", "http://localhost:3456")
    )
    parser.add_argument("--model", default="claude-sonnet-4-5")
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="sample each image N times and report variance (default 1 = single-shot)",
    )
    parser.add_argument(
        "--sweep",
        type=str,
        default=None,
        help="comma-separated N values, e.g. '1,3,5'; scores variance at each N "
        "from one max-N sampling (overrides --repeats)",
    )
    parser.add_argument(
        "--illustrative-icr",
        type=float,
        default=metrics.DEFAULT_ILLUSTRATIVE_ICR,
        help="illustrative carb ratio (g/U) for the worst-case-swing ANALYSIS "
        "metric only -- never a dose (default %(default)s)",
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="evaluate only the first N items"
    )
    parser.add_argument("--out-dir", default=str(_HERE / "results"))
    parser.add_argument(
        "--no-auth",
        action="store_true",
        help="omit the bearer token (e.g. local Ollama)",
    )
    parser.add_argument(
        "--enforce-pass-bar",
        action="store_true",
        help="(variance mode) exit non-zero unless the model clears the local-model "
        "pass-bar -- the certification gate; run with --repeats >= 5",
    )
    args = parser.parse_args()

    if args.repeats < 1:
        parser.error("--repeats must be >= 1")
    if args.illustrative_icr <= 0:
        parser.error("--illustrative-icr must be > 0")
    if args.sweep is not None:
        try:
            args.sweep = _parse_sweep(args.sweep)
        except ValueError as exc:
            parser.error(f"invalid --sweep: {exc}")
        if args.repeats > 1:
            print(
                f"note: --sweep overrides --repeats; sweeping {args.sweep}",
                file=sys.stderr,
            )

    # The pass-bar is only computed in variance mode (--repeats N), so enforcing
    # it anywhere else would silently exit 0 and bless an unverified model. Fail
    # loud instead -- a fail-closed certification gate must never no-op quietly.
    if args.enforce_pass_bar and (args.sweep is not None or args.repeats < 2):
        parser.error(
            "--enforce-pass-bar requires variance mode: pass --repeats >= 5 "
            "(and not --sweep)"
        )

    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
