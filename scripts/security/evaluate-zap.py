#!/usr/bin/env python3
"""Evaluate ZAP scan results from JSON report files.

Reads ZAP traditional-json reports and determines pass/fail based on
Medium+ severity findings. Handles every failure mode:
  - No report file -> FAILURE (scanner crashed or auth failed)
  - Corrupt JSON -> FAILURE
  - Medium/High alerts -> FAILURE (with details)
  - Low/Info only -> SUCCESS (noted)
  - Clean scan -> SUCCESS

Usage:
    python evaluate-zap.py --report results/zap-report.json --name api
    python evaluate-zap.py --report results/zap-web-report.json --name web
"""
import argparse
import json
import os
import sys

GITHUB_OUTPUT = os.environ.get("GITHUB_OUTPUT", "")

RISK_LABELS = {
    "0": "Informational",
    "1": "Low",
    "2": "Medium",
    "3": "High",
}


def write_output(key: str, value: str) -> None:
    """Write a GitHub Actions step output."""
    if GITHUB_OUTPUT:
        with open(GITHUB_OUTPUT, "a") as f:
            f.write(f"{key}={value}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate ZAP scan results")
    parser.add_argument("--report", required=True, help="Path to ZAP JSON report")
    parser.add_argument("--name", required=True, help="Scan name (api or web)")
    args = parser.parse_args()

    output_key = f"zap_{args.name}"

    # No report = failure (scanner crashed or auth failed completely)
    if not os.path.isfile(args.report):
        print(f"  {args.name}: FAILURE -- no report file at {args.report}")
        print("  Scanner may have crashed or authentication failed completely.")
        write_output(output_key, "failure")
        sys.exit(1)

    # Parse report
    try:
        with open(args.report) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"  {args.name}: FAILURE -- corrupt report: {e}")
        write_output(output_key, "failure")
        sys.exit(1)

    # Extract alerts from all sites
    all_alerts = []
    for site in data.get("site", []):
        all_alerts.extend(site.get("alerts", []))

    # Categorize by risk
    by_risk = {"0": [], "1": [], "2": [], "3": []}
    for alert in all_alerts:
        risk = str(alert.get("riskcode", "0"))
        if risk in by_risk:
            by_risk[risk].append(alert)

    high = by_risk["3"]
    medium = by_risk["2"]
    low = by_risk["1"]
    info = by_risk["0"]

    # Report summary
    print(f"  {args.name}: {len(all_alerts)} total alerts "
          f"({len(high)} high, {len(medium)} medium, {len(low)} low, {len(info)} info)")

    # Detail medium+ findings
    if high or medium:
        print(f"")
        for alert in high + medium:
            risk_label = RISK_LABELS.get(str(alert.get("riskcode", "0")), "?")
            name = alert.get("name", "?")
            count = alert.get("count", 0)
            instances = alert.get("instances", [])
            print(f"    [{risk_label}] {name} ({count} instances)")
            for inst in instances[:3]:
                uri = inst.get("uri", "?")[:80]
                print(f"      URL: {uri}")
            if len(instances) > 3:
                print(f"      ... and {len(instances) - 3} more")

        print(f"")
        print(f"  {args.name}: FAILURE -- {len(high)} high + {len(medium)} medium severity alerts")
        write_output(output_key, "failure")
        sys.exit(1)

    # Note low/info findings without failing
    if low:
        print(f"  {args.name}: success ({len(low)} low, {len(info)} info -- not blocking)")
    elif info:
        print(f"  {args.name}: success ({len(info)} informational findings)")
    else:
        print(f"  {args.name}: success (clean)")

    write_output(output_key, "success")


if __name__ == "__main__":
    main()
