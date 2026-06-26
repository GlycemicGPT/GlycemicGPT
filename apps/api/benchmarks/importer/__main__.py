"""CLI: import local glucose data, anonymize, and write daily_brief scenarios.

Examples (from apps/api/):
  uv run python -m benchmarks.importer --source csv --input data.csv --units mg/dL
  uv run python -m benchmarks.importer --source nightscout --input entries.json

Output goes to benchmarks/fixtures_local/daily_brief/ (gitignored). Nothing is committed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from benchmarks.importer.anonymize import anonymize
from benchmarks.importer.scenario_builder import (
    build_daily_brief_scenario,
    write_scenarios,
)
from benchmarks.importer.sources import parse_csv, parse_nightscout_entries

_DEFAULT_OUT = Path(__file__).resolve().parents[1] / "fixtures_local"


def main() -> int:
    parser = argparse.ArgumentParser(prog="benchmarks.importer")
    parser.add_argument("--source", choices=["csv", "nightscout"], required=True)
    parser.add_argument(
        "--input", required=True, help="path to CSV or Nightscout entries.json"
    )
    parser.add_argument("--units", default="mg/dL", choices=["mg/dL", "mmol/L"])
    parser.add_argument("--out", default=str(_DEFAULT_OUT))
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--id", default="local-001")
    args = parser.parse_args()

    raw = Path(args.input).read_text()
    if args.source == "csv":
        series = parse_csv(raw, units=args.units)
    else:
        series = parse_nightscout_entries(json.loads(raw))

    if not series.glucose:
        print("No glucose points parsed from input.", file=sys.stderr)
        return 1

    series = anonymize(series, seed=args.seed)
    scenario = build_daily_brief_scenario(series, args.id)
    out_dir = Path(args.out) / "daily_brief"
    paths = write_scenarios([scenario], out_dir)
    print(f"Wrote {len(paths)} scenario(s) (anonymized, gitignored):")
    for p in paths:
        print(f"  {p}")
    print("\nRun against your configured model:")
    print(f"  uv run python -m benchmarks --scenarios-dir {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
