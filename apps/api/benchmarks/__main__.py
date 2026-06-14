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
from benchmarks.core.report import render_markdown
from benchmarks.suites import run_suite

SCENARIO_ROOT = Path(__file__).resolve().parent / "scenarios"


def main() -> int:
    parser = argparse.ArgumentParser(prog="benchmarks")
    parser.add_argument("--suite", default="meal_analysis",
                        help="scenario subdirectory under benchmarks/scenarios/")
    parser.add_argument("--scenarios-dir", default=None,
                        help="run scenarios from this directory instead of the built-in --suite")
    parser.add_argument("--out", default=None, help="write Markdown report to this path")
    parser.add_argument("--json", action="store_true", help="print JSON report to stdout")
    parser.add_argument(
        "--judge", action="store_true",
        help="enable LLM-as-judge quality scoring via JUDGE_* env vars (never affects safety verdict)",
    )
    parser.add_argument("--json-out", default=None, metavar="PATH",
                        help="write JSON report to this path")
    args = parser.parse_args()

    client = build_client_from_env()
    judge_client = build_client_from_env(prefix="JUDGE") if args.judge else None
    scenario_dir = Path(args.scenarios_dir) if args.scenarios_dir else (SCENARIO_ROOT / args.suite)
    report = asyncio.run(run_suite(scenario_dir, client, judge_client=judge_client))

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2))

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        md = render_markdown(report)
        print(md)
        if args.out:
            Path(args.out).write_text(md)

    return 0 if report["overall_safety_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
