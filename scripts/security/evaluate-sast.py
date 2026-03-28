#!/usr/bin/env python3
"""Evaluate Semgrep SAST results from JSON output files.

Reads Semgrep JSON output files and determines pass/fail based on
ERROR-severity findings. Handles every failure mode:
  - Scanner crash (no JSON) -> FAILURE
  - Corrupt JSON -> FAILURE
  - ERROR-severity findings -> FAILURE
  - WARNING-only findings -> SUCCESS (noted)
  - Parse warnings (PartialParsing) -> SUCCESS (noted)
  - Clean scan -> SUCCESS
  - Scan skipped -> SKIPPED

Outputs GitHub Actions step outputs (semgrep_python, semgrep_typescript,
semgrep_kotlin) and exits non-zero if any scan has ERROR findings.

Usage:
    # In CI (reads exit codes from env vars set by scan steps):
    python evaluate-sast.py

    # Locally (just checks JSON files in current directory):
    python evaluate-sast.py
"""
import json
import os
import sys

LANGUAGES = ["python", "typescript", "kotlin"]
GITHUB_OUTPUT = os.environ.get("GITHUB_OUTPUT", "")
FAILED = False


def write_output(key: str, value: str) -> None:
    """Write a GitHub Actions step output."""
    if GITHUB_OUTPUT:
        with open(GITHUB_OUTPUT, "a") as f:
            f.write(f"{key}={value}\n")


def evaluate_scan(lang: str) -> None:
    global FAILED

    json_file = f"semgrep-{lang}.json"
    exit_env = f"semgrep_{lang}_exit"
    exit_code = os.environ.get(exit_env)

    # Scan was skipped (step never ran, no exit code in env)
    if exit_code is None:
        print(f"  {lang}: skipped (no relevant changes)")
        write_output(f"semgrep_{lang}", "skipped")
        return

    # Scan ran but produced no JSON -> crash
    if not os.path.isfile(json_file):
        print(f"  {lang}: FAILURE -- scanner crashed (exit {exit_code}, no JSON output)")
        write_output(f"semgrep_{lang}", "failure")
        FAILED = True
        return

    # Parse and validate JSON
    try:
        with open(json_file) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"  {lang}: FAILURE -- corrupt JSON: {e}")
        write_output(f"semgrep_{lang}", "failure")
        FAILED = True
        return

    # Extract findings by severity
    results = data.get("results", [])
    errors_list = data.get("errors", [])

    error_findings = [
        r for r in results
        if r.get("extra", {}).get("severity") == "ERROR"
    ]
    warning_findings = [
        r for r in results
        if r.get("extra", {}).get("severity") == "WARNING"
    ]
    parse_errors = [
        e for e in errors_list
        if "PartialParsing" in str(e.get("type", ""))
    ]

    # Report
    if error_findings:
        print(f"  {lang}: FAILURE -- {len(error_findings)} ERROR-severity finding(s)")
        for finding in error_findings:
            rule = finding.get("check_id", "unknown").split(".")[-1]
            path = finding.get("path", "?")
            line = finding.get("start", {}).get("line", "?")
            msg = finding.get("extra", {}).get("message", "")[:120]
            print(f"    [{rule}] {path}:{line} -- {msg}")
        write_output(f"semgrep_{lang}", "failure")
        FAILED = True
    elif warning_findings or parse_errors:
        parts = []
        if warning_findings:
            parts.append(f"{len(warning_findings)} warning(s)")
        if parse_errors:
            parts.append(f"{len(parse_errors)} file(s) with parse warnings")
        print(f"  {lang}: success ({', '.join(parts)})")
        write_output(f"semgrep_{lang}", "success")
    else:
        print(f"  {lang}: success (clean)")
        write_output(f"semgrep_{lang}", "success")


def main() -> None:
    global FAILED
    print("=== SAST Evaluation ===")

    for lang in LANGUAGES:
        evaluate_scan(lang)

    print("=======================")
    if FAILED:
        print("SAST FAILED -- see findings above")
        sys.exit(1)
    print("SAST PASSED")


if __name__ == "__main__":
    main()
