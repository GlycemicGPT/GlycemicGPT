"""CLI: run a benchmark suite against the env-configured provider.

Usage (from apps/api/):
  uv run python -m benchmarks --suite meal_analysis [--out report.md]

Provider comes from BENCHMARK_* env vars (see benchmarks/clients.py).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from benchmarks.clients import build_client_from_env
from benchmarks.core.report import render_repeated_markdown
from benchmarks.suites import run_suite_repeated

SCENARIO_ROOT = Path(__file__).resolve().parent / "scenarios"


def _positive_int(raw: str) -> int:
    """argparse type for counts that must be >= 1 (e.g. --repeat). Rejects 0 and
    negatives up front so they can't reach the suite as an empty/IndexError run."""
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {value}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(prog="benchmarks")
    parser.add_argument(
        "--suite",
        default="meal_analysis",
        help="scenario subdirectory under benchmarks/scenarios/",
    )
    parser.add_argument(
        "--scenarios-dir",
        default=None,
        help="run scenarios from this directory instead of the built-in --suite",
    )
    parser.add_argument(
        "--out", default=None, help="write Markdown report to this path"
    )
    parser.add_argument(
        "--json", action="store_true", help="print JSON report to stdout"
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="enable LLM-as-judge quality scoring via JUDGE_* env vars (never affects safety verdict)",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        metavar="PATH",
        help="write JSON report to this path",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        metavar="N",
        help="response token budget per call. Raise it for thinking models "
        "(Qwen3, DeepSeek-R1) that spend tokens on reasoning before answering; "
        "the default budget can truncate them to an empty response (issue #554).",
    )
    parser.add_argument(
        "--repeat",
        type=_positive_int,
        default=5,
        metavar="N",
        help="run each scenario N times; a scenario passes only if ALL runs are safe (default 5)",
    )
    args = parser.parse_args()

    client = build_client_from_env()
    judge_client = build_client_from_env(prefix="JUDGE") if args.judge else None
    scenario_dir = (
        Path(args.scenarios_dir) if args.scenarios_dir else (SCENARIO_ROOT / args.suite)
    )
    report = asyncio.run(
        run_suite_repeated(
            scenario_dir,
            client,
            judge_client=judge_client,
            max_tokens=args.max_tokens,
            repeat=args.repeat,
        )
    )

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2))

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        md = render_repeated_markdown(report)
        print(md)
        if args.out:
            Path(args.out).write_text(md)

    return 0 if report["overall_safety_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
