#!/usr/bin/env python3
"""Evaluate ZAP scan results from JSON report files.

Reads ZAP traditional-json reports and determines pass/fail based on
Medium+ severity findings. Handles every failure mode:
  - No report file -> FAILURE (scanner crashed or auth failed)
  - Corrupt JSON -> FAILURE
  - Medium/High alerts -> FAILURE (with details)
  - Low/Info only -> SUCCESS (noted)
  - Clean scan -> SUCCESS

Suppressions are loaded from zap-suppressions.json (same directory as
this script). Each suppression must include a reason. Suppressed alerts
are still logged but don't fail the build.

Usage:
    python evaluate-zap.py --report results/zap-report.json --name api
    python evaluate-zap.py --report results/zap-web-report.json --name web
"""
import argparse
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SUPPRESSIONS_FILE = os.path.join(SCRIPT_DIR, "zap-suppressions.json")
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


def load_suppressions() -> dict:
    """Load suppressed alert rules from zap-suppressions.json.

    Format:
    {
        "suppressions": [
            {
                "pluginId": "10055",
                "reason": "Next.js requires unsafe-inline/unsafe-eval. See story-35.11b.",
                "scan": "web"      // optional: "api", "web", or omit for both
            }
        ]
    }
    """
    if not os.path.isfile(SUPPRESSIONS_FILE):
        return {}
    try:
        with open(SUPPRESSIONS_FILE) as f:
            data = json.load(f)
        # Index by (pluginId, scan) for fast lookup
        result = {}
        for s in data.get("suppressions", []):
            pid = str(s.get("pluginId", ""))
            scan = s.get("scan")  # None means all scans
            reason = s.get("reason", "no reason given")
            result[(pid, scan)] = reason
            if scan is not None:
                # Also match when scan is None (global suppression)
                pass
            else:
                # Global suppression: match any scan name
                result[(pid, None)] = reason
        return result
    except (json.JSONDecodeError, IOError) as e:
        print(f"  WARNING: Failed to load suppressions: {e}")
        return {}


def is_suppressed(alert: dict, scan_name: str, suppressions: dict) -> str | None:
    """Return the suppression reason if this alert is suppressed, else None."""
    pid = str(alert.get("pluginid", ""))
    # Check scan-specific suppression first, then global
    reason = suppressions.get((pid, scan_name))
    if reason:
        return reason
    reason = suppressions.get((pid, None))
    if reason:
        return reason
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate ZAP scan results")
    parser.add_argument("--report", required=True, help="Path to ZAP JSON report")
    parser.add_argument("--name", required=True, help="Scan name (api or web)")
    args = parser.parse_args()

    output_key = f"zap_{args.name}"
    suppressions = load_suppressions()

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

    # Separate suppressed from active alerts
    active_alerts = []
    suppressed_alerts = []
    for alert in all_alerts:
        reason = is_suppressed(alert, args.name, suppressions)
        if reason:
            suppressed_alerts.append((alert, reason))
        else:
            active_alerts.append(alert)

    # Categorize active alerts by risk
    by_risk = {"0": [], "1": [], "2": [], "3": []}
    for alert in active_alerts:
        risk = str(alert.get("riskcode", "0"))
        if risk in by_risk:
            by_risk[risk].append(alert)

    high = by_risk["3"]
    medium = by_risk["2"]
    low = by_risk["1"]
    info = by_risk["0"]

    # Report summary
    suppressed_count = len(suppressed_alerts)
    active_count = len(active_alerts)
    print(f"  {args.name}: {len(all_alerts)} total alerts, {suppressed_count} suppressed, {active_count} active "
          f"({len(high)} high, {len(medium)} medium, {len(low)} low, {len(info)} info)")

    # Log suppressed alerts
    if suppressed_alerts:
        print(f"  Suppressed:")
        for alert, reason in suppressed_alerts:
            risk_label = RISK_LABELS.get(str(alert.get("riskcode", "0")), "?")
            name = alert.get("name", "?")
            print(f"    [{risk_label}] {name} -- {reason}")

    # Detail medium+ active findings
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
        print(f"  {args.name}: FAILURE -- {len(high)} high + {len(medium)} medium severity active alerts")
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
