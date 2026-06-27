"""Compare multiple saved benchmark reports into one recommended-models table.

Run: uv run python -m benchmarks.compare report_a.json report_b.json ...

HARD RULE: a model that failed the safety verdict is never 'recommended',
regardless of quality -- safety is a gate, not a score.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def load_reports(paths: list[str | Path]) -> list[dict[str, Any]]:
    return [json.loads(Path(p).read_text()) for p in paths]


def build_comparison(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Build comparison rows sorted safe-first, then higher quality, then lower
    latency. `recommended` = the top safe row's model, or None if none are safe.
    """

    def sort_key(r: dict[str, Any]) -> tuple:
        safe = bool(r.get("overall_safety_passed"))
        quality = r.get("quality_mean")
        latency = r.get("latency_p50_s")
        return (
            0 if safe else 1,  # safe first
            -(quality if quality is not None else -1.0),  # higher quality first
            latency if latency is not None else float("inf"),  # lower latency first
        )

    rows = sorted(reports, key=sort_key)
    safe_rows = [r for r in rows if r.get("overall_safety_passed")]
    recommended = safe_rows[0]["model"] if safe_rows else None
    return {"rows": rows, "recommended": recommended}


def _fmt(value: Any, prefix: str = "") -> str:
    if value is None:
        return "—"
    return f"{prefix}{value}"


def render_comparison_markdown(comparison: dict[str, Any]) -> str:
    lines = [
        "# Model comparison",
        "",
        "| Model | Safety | Quality | p50 latency (s) | Est. cost | Scenarios |",
        "|---|---|---|---|---|---|",
    ]
    for r in comparison["rows"]:
        safety = "✅ PASS" if r.get("overall_safety_passed") else "❌ FAIL"
        quality = _fmt(r.get("quality_mean"))
        latency = _fmt(r.get("latency_p50_s"))
        cost = (
            _fmt(r.get("total_cost_usd"), prefix="$")
            if r.get("total_cost_usd") is not None
            else "unknown"
        )
        n = _fmt(r.get("scenario_count"))
        lines.append(
            f"| {r.get('model')} | {safety} | {quality} | {latency} | {cost} | {n} |"
        )
    lines.append("")
    if comparison["recommended"]:
        lines.append(
            f"**Recommended:** {comparison['recommended']} "
            "(top model that passed the safety gate)"
        )
    else:
        lines.append(
            "**Recommended:** none passed safety — do not use any of these as-is."
        )
    lines.append("")
    lines.append(
        "> Passing the safety gate is NOT a medical-safety guarantee. See MEDICAL-DISCLAIMER.md."
    )
    return "\n".join(lines)


def main() -> int:
    paths = sys.argv[1:]
    if not paths:
        print(
            "usage: python -m benchmarks.compare report1.json [report2.json ...]",
            file=sys.stderr,
        )
        return 2
    print(render_comparison_markdown(build_comparison(load_reports(paths))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
