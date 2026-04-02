#!/usr/bin/env python3
"""Create GitHub Issues from security scan findings.

Reads SAST (Semgrep) and DAST (ZAP, Nuclei) scan results, normalizes
findings, deduplicates against existing GitHub Issues, and creates or
updates issues via the GitHub API.

Deduplication uses a deterministic fingerprint stored as an HTML comment
in each issue body. Existing issues are found by bulk-fetching all issues
with the 'security' + 'automated' labels and extracting fingerprints.

Lifecycle:
  - PR scan: create new issues, reopen closed ones. Auto-close issues
    tagged with the current PR when the finding is no longer detected
    (scoped: only closes this PR's issues, never other PRs' or full-suite's).
  - Full suite: same create/reopen, plus auto-close open issues whose
    findings are no longer detected (guarded: only closes issues from
    tools that actually produced results this run).

This script ALWAYS exits 0. It must never block CI.

Usage:
    python create-finding-issues.py \\
        --sast-results sast-results/ \\
        --dast-results dast-results/ \\
        --scan-type pr \\
        --run-id 12345 --run-url "https://..." \\
        --repo owner/repo \\
        --pr-author username \\
        --branch main --sha abc1234 \\
        --dry-run
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SUPPRESSIONS_FILE = SCRIPT_DIR / "zap-suppressions.json"
GITHUB_OUTPUT = os.environ.get("GITHUB_OUTPUT", "")


def write_output(key: str, value: str) -> None:
    """Write a GitHub Actions step output."""
    if GITHUB_OUTPUT:
        with open(GITHUB_OUTPUT, "a") as f:
            f.write(f"{key}={value}\n")

# Severity threshold: create issues for Low and above, skip Informational
ISSUE_SEVERITIES = {"critical", "high", "medium", "low"}

SEVERITY_EMOJI = {
    "critical": ":purple_circle:",
    "high": ":red_circle:",
    "medium": ":orange_circle:",
    "low": ":yellow_circle:",
}

SEVERITY_LABELS = {
    "critical": "severity: critical",
    "high": "severity: high",
    "medium": "severity: medium",
    "low": "severity: low",
}

LABEL_COLORS = {
    "security": "d73a49",
    "automated": "0e8a16",
    "accepted-risk": "c5def5",
    "severity: critical": "b60205",
    "severity: high": "d93f0b",
    "severity: medium": "fbca04",
    "severity: low": "e4e669",
    "component: api": "1d76db",
    "component: web": "5319e7",
    "component: mobile": "006b75",
}

TOOL_COMPONENT = {
    "semgrep": None,  # derived from file path
    "zap-api": "component: api",
    "zap-web": "component: web",
    "zap-unauth-api": "component: api",
    "zap-unauth-web": "component: web",
    "nuclei-api": "component: api",
    "nuclei-web": "component: web",
}


@dataclass
class SecurityFinding:
    tool: str
    rule_id: str
    title: str
    severity: str
    description: str
    locations: list[str] = field(default_factory=list)
    remediation: str = ""
    references: list[str] = field(default_factory=list)
    cwe: str | None = None
    owasp: list[str] = field(default_factory=list)
    fingerprint: str = ""
    suppressed: bool = False
    suppression_reason: str | None = None


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def html_to_markdown(html: str) -> str:
    """Convert ZAP's simple HTML fragments to GitHub-flavored markdown."""
    if not html:
        return ""
    text = html
    text = re.sub(r"<p>(.*?)</p>", r"\1\n\n", text, flags=re.DOTALL)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<a\s+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", r"[\2](\1)", text)
    text = re.sub(r"<li>(.*?)</li>", r"- \1\n", text, flags=re.DOTALL)
    text = re.sub(r"</?(?:ul|ol|div|span|strong|em|b|i)>", "", text)
    text = re.sub(r"<[^>]+>", "", text)  # strip remaining tags
    text = unescape(text)
    return text.strip()


def component_from_path(path: str) -> str | None:
    """Derive component label from a file path."""
    if path.startswith("apps/api/") or path.startswith("scripts/security/"):
        return "component: api"
    if path.startswith("apps/web/") or path.startswith("sidecar/"):
        return "component: web"
    if path.startswith("apps/mobile/") or path.startswith("plugins/"):
        return "component: mobile"
    return None


def load_zap_suppressions() -> dict[tuple[str, str | None], str]:
    """Load ZAP suppressions. Returns {(pluginid, scan_name|None): reason}.

    Scan-aware: a suppression with "scan": "web" only matches the "web" scan,
    not "unauth-web". Global suppressions (no "scan" field) match all scans.
    This matches the behavior of evaluate-zap.py's is_suppressed().
    """
    if not SUPPRESSIONS_FILE.is_file():
        return {}
    try:
        data = json.loads(SUPPRESSIONS_FILE.read_text())
        result: dict[tuple[str, str | None], str] = {}
        for s in data.get("suppressions", []):
            pid = str(s.get("pluginId", ""))
            scan = s.get("scan")  # None means global (matches all scans)
            reason = s.get("reason", "no reason given")
            # Key is (pluginId, scan_name_or_None). Lookup checks
            # (pid, scan_name) first, then (pid, None) for global match.
            result[(pid, scan)] = reason
        return result
    except (json.JSONDecodeError, IOError):
        return {}


def parse_semgrep_results(results_dir: str) -> list[SecurityFinding]:
    """Parse Semgrep JSON output files."""
    findings = []
    for path in sorted(glob.glob(os.path.join(results_dir, "semgrep-*.json"))):
        try:
            data = json.loads(Path(path).read_text())
        except (json.JSONDecodeError, IOError):
            continue

        for result in data.get("results", []):
            raw_severity = result.get("extra", {}).get("severity", "")
            if raw_severity == "ERROR":
                severity = "high"
            elif raw_severity == "WARNING":
                severity = "medium"
            else:
                continue

            check_id = result.get("check_id", "unknown")
            file_path = result.get("path", "unknown")
            line = result.get("start", {}).get("line", 0)
            meta = result.get("extra", {}).get("metadata", {})

            fingerprint = f"semgrep:{check_id}:{file_path}"
            rule_short = check_id.split(".")[-1]

            refs = []
            if meta.get("source"):
                refs.append(meta["source"])
            if meta.get("shortlink"):
                refs.append(meta["shortlink"])
            refs.extend(meta.get("references", []))

            cwe_list = meta.get("cwe", [])
            cwe = cwe_list[0] if cwe_list else None

            findings.append(SecurityFinding(
                tool="semgrep",
                rule_id=check_id,
                title=f"{rule_short} in {file_path}",
                severity=severity,
                description=result.get("extra", {}).get("message", ""),
                locations=[f"`{file_path}:{line}`"],
                remediation=f"See rule documentation: {meta.get('source', 'N/A')}",
                references=refs,
                cwe=cwe,
                owasp=meta.get("owasp", []),
                fingerprint=fingerprint,
            ))
    return findings


def parse_zap_results(results_dir: str) -> list[SecurityFinding]:
    """Parse ZAP traditional-json report files."""
    findings = []
    suppressions = load_zap_suppressions()

    for report_name, scan_name in [
        ("zap-report.json", "api"),
        ("zap-web-report.json", "web"),
        ("zap-unauth-api-report.json", "unauth-api"),
        ("zap-unauth-web-report.json", "unauth-web"),
    ]:
        report_path = os.path.join(results_dir, report_name)
        if not os.path.isfile(report_path):
            continue

        try:
            data = json.loads(Path(report_path).read_text())
        except (json.JSONDecodeError, IOError):
            continue

        for site in data.get("site", []):
            for alert in site.get("alerts", []):
                riskcode = int(alert.get("riskcode", 0))
                # Map riskcode to severity
                if riskcode == 3:
                    severity = "high"
                elif riskcode == 2:
                    severity = "medium"
                elif riskcode == 1:
                    severity = "low"
                else:
                    continue  # skip Informational

                plugin_id = str(alert.get("pluginid", ""))
                fingerprint = f"zap-{scan_name}:{plugin_id}"

                # Check suppression: scan-specific first, then global
                suppression_reason = suppressions.get((plugin_id, scan_name))
                if not suppression_reason:
                    suppression_reason = suppressions.get((plugin_id, None))
                suppressed = suppression_reason is not None

                # Build locations from instances
                locations = []
                for inst in alert.get("instances", [])[:10]:
                    uri = inst.get("uri", "")
                    method = inst.get("method", "")
                    param = inst.get("param", "")
                    loc = f"`{method} {uri}`"
                    if param:
                        loc += f" (param: `{param}`)"
                    locations.append(loc)

                total = int(alert.get("count", len(locations)))
                if total > 10:
                    locations.append(f"... and {total - 10} more instances")

                # Parse references
                refs = []
                ref_html = alert.get("reference", "")
                for match in re.findall(r'href=["\']([^"\']+)["\']', ref_html):
                    refs.append(match)
                if not refs:
                    ref_text = html_to_markdown(ref_html)
                    refs = [url.strip() for url in ref_text.split("\n") if url.strip().startswith("http")]

                cwe_id = alert.get("cweid", "")
                cwe = f"CWE-{cwe_id}" if cwe_id and cwe_id != "0" else None

                findings.append(SecurityFinding(
                    tool=f"zap-{scan_name}",
                    rule_id=plugin_id,
                    title=alert.get("name", "Unknown Alert"),
                    severity=severity,
                    description=html_to_markdown(alert.get("desc", "")),
                    locations=locations,
                    remediation=html_to_markdown(alert.get("solution", "")),
                    references=refs,
                    cwe=cwe,
                    fingerprint=fingerprint,
                    suppressed=suppressed,
                    suppression_reason=suppression_reason,
                ))
    return findings


def parse_nuclei_results(results_dir: str) -> list[SecurityFinding]:
    """Parse Nuclei JSONL output files."""
    findings = []

    # Handle both naming patterns
    patterns = [
        os.path.join(results_dir, "nuclei-api.json"),
        os.path.join(results_dir, "nuclei-web.json"),
    ]
    # Also check timestamped files from run-dast.sh
    patterns.extend(glob.glob(os.path.join(results_dir, "nuclei-2*.json")))

    for path in patterns:
        if not os.path.isfile(path):
            continue

        basename = os.path.basename(path)
        try:
            content = Path(path).read_text().strip()
        except IOError:
            continue

        if not content or content == "[]":
            continue

        # JSONL: one JSON object per line. Also handle JSON array.
        lines = []
        if content.startswith("["):
            try:
                lines = json.loads(content)
            except json.JSONDecodeError:
                continue
        else:
            for line in content.split("\n"):
                line = line.strip()
                if line:
                    try:
                        lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        for entry in lines:
            info = entry.get("info", {})
            raw_severity = info.get("severity", "info").lower()
            if raw_severity not in ISSUE_SEVERITIES:
                continue

            template_id = entry.get("template-id", "unknown")
            matched_at = entry.get("matched-at", "")

            # Determine scan target from URL or filename
            if "nuclei-api" in basename or ":8001" in matched_at:
                scan_name = "api"
            elif "nuclei-web" in basename or ":3001" in matched_at:
                scan_name = "web"
            else:
                scan_name = "combined"

            fingerprint = f"nuclei-{scan_name}:{template_id}"

            refs = []
            ref = info.get("reference")
            if isinstance(ref, list):
                refs = ref
            elif isinstance(ref, str) and ref:
                refs = [ref]
            if entry.get("template-url"):
                refs.append(entry["template-url"])

            findings.append(SecurityFinding(
                tool=f"nuclei-{scan_name}",
                rule_id=template_id,
                title=info.get("name", "Unknown"),
                severity=raw_severity,
                description=info.get("description", ""),
                locations=[f"`{matched_at}`"] if matched_at else [],
                remediation=info.get("remediation", ""),
                references=refs,
                fingerprint=fingerprint,
            ))
    return findings


# ---------------------------------------------------------------------------
# GitHub API Client
# ---------------------------------------------------------------------------

class GitHubIssueClient:
    """Thin wrapper for GitHub REST API with rate limit handling."""

    def __init__(self, token: str, repo: str):
        self.token = token
        self.repo = repo
        self.base_url = f"https://api.github.com/repos/{repo}"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._existing_labels: set[str] | None = None

    def _request(self, method: str, url: str, retries: int = 3, **kwargs) -> dict | list | None:
        """Make API request with retry and rate limit handling."""
        import urllib.request
        import urllib.error

        full_url = url if url.startswith("http") else f"{self.base_url}{url}"

        for attempt in range(retries):
            try:
                data = kwargs.get("json_data")
                if data is not None:
                    body = json.dumps(data).encode("utf-8")
                else:
                    body = None

                req = urllib.request.Request(full_url, data=body, method=method)
                for k, v in self.headers.items():
                    req.add_header(k, v)
                if body:
                    req.add_header("Content-Type", "application/json")

                with urllib.request.urlopen(req, timeout=30) as resp:
                    response_body = resp.read().decode("utf-8")
                    return json.loads(response_body) if response_body.strip() else {}

            except urllib.error.HTTPError as e:
                if e.code == 429:
                    retry_after = int(e.headers.get("Retry-After", 60))
                    print(f"    Rate limited, waiting {retry_after}s...")
                    time.sleep(retry_after)
                    continue
                if e.code == 422:
                    body = e.read().decode("utf-8", errors="replace")
                    print(f"    API 422: {body[:200]}")
                    return None
                if e.code == 403:
                    err_body = e.read().decode("utf-8", errors="replace")[:200]
                    print(f"    API 403: Permission denied. Ensure glycemicgpt-security has 'issues: write' permission.\n    Response: {err_body}")
                    return None
                err_body = e.read().decode("utf-8", errors="replace")[:200]
                print(f"    API error {e.code}: {e.reason}\n    Response: {err_body}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return None
            except Exception as e:
                print(f"    Request error: {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return None
        return None

    def list_automated_issues(self) -> list[dict]:
        """Fetch all issues with 'security' + 'automated' labels (open and closed)."""
        all_issues = []
        for state in ["open", "closed"]:
            page = 1
            while True:
                result = self._request(
                    "GET",
                    f"/issues?labels=security,automated&state={state}&per_page=100&page={page}",
                )
                if not result:
                    break
                all_issues.extend(result)
                if len(result) < 100:
                    break
                page += 1
        return all_issues

    def create_issue(self, title: str, body: str, labels: list[str], assignee: str | None = None) -> dict | None:
        """Create a new issue."""
        data: dict = {"title": title, "body": body, "labels": labels}
        if assignee:
            data["assignees"] = [assignee]
        return self._request("POST", "/issues", json_data=data)

    def add_comment(self, issue_number: int, body: str) -> dict | None:
        """Add a comment to an issue."""
        return self._request("POST", f"/issues/{issue_number}/comments", json_data={"body": body})

    def update_issue(self, issue_number: int, **kwargs) -> dict | None:
        """Update issue fields (state, labels, etc)."""
        return self._request("PATCH", f"/issues/{issue_number}", json_data=kwargs)

    def last_bot_comment_age_days(self, issue_number: int) -> float:
        """Return days since last glycemicgpt-security comment on an issue.

        Returns:
            float >= 0: days since last bot comment
            float('inf'): no bot comment found (safe to comment)
            -1.0: lookup failed (caller should skip commenting)
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=7)
        page = 1
        while True:
            comments = self._request(
                "GET",
                f"/issues/{issue_number}/comments?per_page=50&page={page}&sort=created&direction=desc",
            )
            if comments is None:
                return -1.0
            if not comments:
                break
            for comment in comments:
                if comment.get("user", {}).get("login") == "glycemicgpt-security[bot]":
                    created = comment.get("created_at", "")
                    if created:
                        comment_time = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        return (now - comment_time).total_seconds() / 86400
                # Newest-first: once we pass the 7-day cutoff, stop paging
                created = comment.get("created_at", "")
                if created:
                    comment_time = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    if comment_time < cutoff:
                        return float("inf")
            page += 1
        return float("inf")

    def ensure_labels(self, labels: list[str]) -> None:
        """Create any labels that don't exist yet."""
        if self._existing_labels is None:
            result = self._request("GET", "/labels?per_page=100") or []
            self._existing_labels = {l["name"] for l in result}

        for label in labels:
            if label not in self._existing_labels:
                color = LABEL_COLORS.get(label, "ededed")
                self._request("POST", "/labels", json_data={
                    "name": label,
                    "color": color,
                })
                self._existing_labels.add(label)


# ---------------------------------------------------------------------------
# Issue Content Builders
# ---------------------------------------------------------------------------

def build_issue_title(finding: SecurityFinding) -> str:
    """Build issue title, max ~100 chars."""
    emoji = SEVERITY_EMOJI.get(finding.severity, ":white_circle:")
    title = f"[Security] {emoji} {finding.title}"
    if len(title) > 100:
        title = title[:97] + "..."
    return title


def build_issue_body(
    finding: SecurityFinding,
    run_id: str,
    run_url: str,
    branch: str,
    sha: str,
    pr_number: str | None = None,
) -> str:
    """Build the full issue body markdown."""
    lines = [
        f"## Security Finding: {finding.title}",
        "",
        f"<!-- security-finding:{finding.fingerprint} -->",
    ]
    if pr_number:
        lines.append(f"<!-- source-pr:{pr_number} -->")
    lines.append("")

    # Suppression callout
    if finding.suppressed:
        lines.extend([
            f"> :warning: **Accepted Risk** -- This finding is suppressed in CI.",
            f"> **Reason:** {finding.suppression_reason or 'No reason given.'}",
            "",
        ])

    # Properties table
    emoji = SEVERITY_EMOJI.get(finding.severity, "")
    lines.extend([
        "| Property | Value |",
        "|----------|-------|",
        f"| **Severity** | {emoji} {finding.severity.title()} |",
        f"| **Tool** | {finding.tool} |",
        f"| **Rule** | `{finding.rule_id}` |",
    ])
    if finding.cwe:
        cwe_num = finding.cwe.replace("CWE-", "")
        lines.append(f"| **CWE** | [{finding.cwe}](https://cwe.mitre.org/data/definitions/{cwe_num}.html) |")
    if finding.owasp:
        lines.append(f"| **OWASP** | {', '.join(finding.owasp[:3])} |")
    lines.append("")

    # Description
    if finding.description:
        lines.extend(["### Description", "", finding.description, ""])

    # Locations
    if finding.locations:
        lines.append("### Affected Location(s)")
        lines.append("")
        for loc in finding.locations:
            lines.append(f"- {loc}")
        lines.append("")

    # Remediation
    if finding.remediation:
        lines.extend(["### Remediation", "", finding.remediation, ""])

    # References
    if finding.references:
        lines.append("### References")
        lines.append("")
        for ref in finding.references[:5]:
            lines.append(f"- {ref}")
        lines.append("")

    # Footer
    lines.extend([
        "---",
        f"> Detected by security scan run [#{run_id}]({run_url})",
        f"> Branch: `{branch}` | Commit: `{sha[:7]}`",
        ">",
        "> *Auto-created by [glycemicgpt-security](https://github.com/apps/glycemicgpt-security) security scanner.*",
        "> *If this is a false positive, close the issue with a comment explaining why.*",
    ])

    return "\n".join(lines)


def build_labels(finding: SecurityFinding) -> list[str]:
    """Build label list for the issue."""
    labels = ["security", "automated"]

    if finding.severity in SEVERITY_LABELS:
        labels.append(SEVERITY_LABELS[finding.severity])

    if finding.suppressed:
        labels.append("accepted-risk")

    # Component label
    component = TOOL_COMPONENT.get(finding.tool)
    if component is None and finding.locations:
        # Derive from file path (Semgrep)
        first_loc = finding.locations[0].strip("`")
        component = component_from_path(first_loc)
    if component:
        labels.append(component)

    return labels


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

def dedup_findings(findings: list[SecurityFinding]) -> list[SecurityFinding]:
    """Group findings with the same fingerprint into one finding.

    ZAP can produce multiple alerts with the same pluginid (e.g., 3 CSP
    sub-alerts all with pluginid=10055). These should become one issue
    with combined locations and descriptions.
    """
    by_fp: dict[str, SecurityFinding] = {}
    for f in findings:
        if f.fingerprint in by_fp:
            existing = by_fp[f.fingerprint]
            # Merge: take highest severity, combine locations/descriptions
            sev_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
            if sev_order.get(f.severity, 0) > sev_order.get(existing.severity, 0):
                existing.severity = f.severity
            if f.title not in existing.title:
                existing.title = f"{existing.title}, {f.title}"
                if len(existing.title) > 80:
                    existing.title = existing.title[:77] + "..."
            existing.locations.extend(f.locations)
            if f.description and f.description not in existing.description:
                existing.description += f"\n\n**{f.title}:** {f.description}"
            if f.remediation and f.remediation not in existing.remediation:
                existing.remediation += f"\n\n{f.remediation}"
            existing.references = list(dict.fromkeys(existing.references + f.references))
        else:
            by_fp[f.fingerprint] = f
    return list(by_fp.values())


FINGERPRINT_RE = re.compile(r"<!-- security-finding:(.+?) -->")
SOURCE_PR_RE = re.compile(r"<!-- source-pr:(\d+) -->")


def detect_tools_with_results(sast_dir: str, dast_dir: str) -> set[str]:
    """Detect which security tools produced valid output files.

    A tool that ran and found 0 results still counts as "present" --
    the file exists with valid structure. This is used to prevent
    auto-closing issues from tools that didn't run (e.g., SAST crashed
    but DAST succeeded).
    """
    tools = set()

    # SAST: check for valid Semgrep JSON files
    if os.path.isdir(sast_dir):
        for f in glob.glob(os.path.join(sast_dir, "semgrep-*.json")):
            try:
                data = json.loads(Path(f).read_text())
                if isinstance(data, dict) and "results" in data:
                    tools.add("semgrep")
                    break
            except (json.JSONDecodeError, IOError):
                continue

    # DAST: check for valid ZAP reports
    if os.path.isdir(dast_dir):
        for name, tool in [
            ("zap-report.json", "zap-api"),
            ("zap-web-report.json", "zap-web"),
            ("zap-unauth-api-report.json", "zap-unauth-api"),
            ("zap-unauth-web-report.json", "zap-unauth-web"),
        ]:
            path = os.path.join(dast_dir, name)
            if os.path.isfile(path):
                try:
                    data = json.loads(Path(path).read_text())
                    if isinstance(data, dict) and "site" in data:
                        tools.add(tool)
                except (json.JSONDecodeError, IOError):
                    continue

        # Nuclei: validate JSON is parseable (empty [] is valid, truncated is not)
        for name, tool in [("nuclei-api.json", "nuclei-api"), ("nuclei-web.json", "nuclei-web")]:
            path = os.path.join(dast_dir, name)
            if os.path.isfile(path):
                try:
                    content = Path(path).read_text().strip()
                    json.loads(content) if content else None
                    tools.add(tool)  # Valid JSON (even empty [] or {})
                except (json.JSONDecodeError, IOError):
                    continue
        # Timestamped nuclei files from run-dast.sh: check content for target
        for f in glob.glob(os.path.join(dast_dir, "nuclei-2*.json")):
            try:
                content = Path(f).read_text()
                if ":8001" in content:
                    tools.add("nuclei-api")
                if ":3001" in content:
                    tools.add("nuclei-web")
                if not content.strip() or content.strip() == "[]":
                    # Empty but valid: tool ran, found nothing for both targets
                    tools.add("nuclei-api")
                    tools.add("nuclei-web")
            except IOError:
                continue

    return tools


def extract_fingerprint(body: str) -> str | None:
    """Extract fingerprint from issue body."""
    match = FINGERPRINT_RE.search(body)
    return match.group(1) if match else None


def reconcile_findings(
    findings: list[SecurityFinding],
    client: GitHubIssueClient,
    scan_type: str,
    run_id: str,
    run_url: str,
    branch: str,
    sha: str,
    pr_author: str | None,
    pr_number: str | None,
    dry_run: bool,
    reports_present: bool = True,
    tools_with_results: set[str] | None = None,
    pr_type: str = "feature",
) -> dict:
    """Core orchestration: create, reopen, comment, close issues."""
    stats = {"created": 0, "reopened": 0, "commented": 0, "closed": 0, "skipped": 0, "issues": []}

    if not findings:
        print("  No findings to process")
        if scan_type == "full-suite" and reports_present and not dry_run:
            # Reports were present but had 0 findings -- safe to auto-close
            pass
        else:
            if not reports_present:
                print("  WARNING: No scan reports found -- skipping auto-close to prevent false closures")
            return stats

    # Bulk fetch existing automated issues
    print("  Fetching existing automated issues...")
    existing_issues = client.list_automated_issues() if not dry_run else []
    fingerprint_to_issue = {}
    for issue in existing_issues:
        fp = extract_fingerprint(issue.get("body", ""))
        if fp:
            fingerprint_to_issue[fp] = issue

    print(f"  Found {len(fingerprint_to_issue)} existing automated issues")

    # Ensure labels exist
    all_labels = set()
    for f in findings:
        all_labels.update(build_labels(f))
    if not dry_run:
        client.ensure_labels(list(all_labels))

    # Process each finding
    current_fingerprints = set()
    for finding in findings:
        current_fingerprints.add(finding.fingerprint)
        existing = fingerprint_to_issue.get(finding.fingerprint)

        title = build_issue_title(finding)
        labels = build_labels(finding)
        assignee = pr_author if scan_type == "pr" else None

        if existing is None:
            # New finding -- create issue
            if dry_run:
                print(f"  [DRY RUN] Would create: {title}")
                print(f"    Labels: {labels}")
                print(f"    Fingerprint: {finding.fingerprint}")
                stats["issues"].append({"number": 0, "title": finding.title, "action": "created", "severity": finding.severity, "url": ""})
            else:
                body = build_issue_body(finding, run_id, run_url, branch, sha, pr_number=pr_number)
                result = client.create_issue(title, body, labels, assignee)
                if result:
                    print(f"  Created #{result['number']}: {title}")
                    stats["issues"].append({
                        "number": result["number"],
                        "title": finding.title,
                        "action": "created",
                        "severity": finding.severity,
                        "url": result.get("html_url", ""),
                    })
                else:
                    print(f"  Failed to create: {title}")
            stats["created"] += 1

        elif existing["state"] == "closed":
            # Previously closed -- reopen and refresh content
            if dry_run:
                print(f"  [DRY RUN] Would reopen #{existing['number']}: {title}")
            else:
                # Determine effective source-pr tag.
                # Promotion PRs preserve the existing tag (they don't own findings).
                effective_pr = pr_number
                if pr_type == "promotion":
                    existing_pr_match = SOURCE_PR_RE.search(existing.get("body", ""))
                    effective_pr = existing_pr_match.group(1) if existing_pr_match else None
                elif not effective_pr:
                    existing_pr_match = SOURCE_PR_RE.search(existing.get("body", ""))
                    if existing_pr_match:
                        effective_pr = existing_pr_match.group(1)
                body = build_issue_body(finding, run_id, run_url, branch, sha, pr_number=effective_pr)
                comment = (
                    f"This finding was **re-detected** in security scan "
                    f"run [#{run_id}]({run_url}) on branch `{branch}` "
                    f"(commit `{sha[:7]}`). Reopening with updated details."
                )
                client.add_comment(existing["number"], comment)
                client.update_issue(
                    existing["number"],
                    state="open",
                    title=title,
                    body=body,
                    labels=[l for l in labels],
                )
                print(f"  Reopened #{existing['number']}: {title}")
                stats["issues"].append({
                    "number": existing["number"],
                    "title": finding.title,
                    "action": "reopened",
                    "severity": finding.severity,
                    "url": existing.get("html_url", ""),
                })
            stats["reopened"] += 1

        else:
            # Already open -- refresh content if changed, add "still detected" for full-suite
            if not dry_run:
                # Determine effective source-pr tag.
                # Promotion PRs preserve the existing tag (they don't own findings).
                effective_pr = pr_number
                if pr_type == "promotion":
                    existing_pr_match = SOURCE_PR_RE.search(existing.get("body", ""))
                    effective_pr = existing_pr_match.group(1) if existing_pr_match else None
                elif not effective_pr:
                    existing_pr_match = SOURCE_PR_RE.search(existing.get("body", ""))
                    if existing_pr_match:
                        effective_pr = existing_pr_match.group(1)
                body = build_issue_body(finding, run_id, run_url, branch, sha, pr_number=effective_pr)
                existing_labels = {l["name"] for l in existing.get("labels", [])}

                # Refresh title/body/labels if changed
                needs_update = (
                    set(labels) != existing_labels
                    or existing.get("title", "") != title
                )
                if needs_update:
                    client.update_issue(
                        existing["number"],
                        title=title,
                        body=body,
                        labels=[l for l in labels],
                    )
                    print(f"  Updated #{existing['number']}: {title} (labels/title changed)")
                    stats["commented"] += 1

                # PR scan: update source-pr tag if it changed (prevents orphan cleanup bugs).
                # Skip for promotion PRs -- they don't own findings, so re-tagging would
                # cause false closures when the promotion PR is closed without merging.
                elif scan_type == "pr" and pr_number and pr_type != "promotion":
                    existing_body = existing.get("body", "")
                    existing_pr_match = SOURCE_PR_RE.search(existing_body)
                    existing_pr_num = existing_pr_match.group(1) if existing_pr_match else None
                    if existing_pr_num != str(pr_number):
                        body = build_issue_body(finding, run_id, run_url, branch, sha, pr_number=pr_number)
                        client.update_issue(existing["number"], body=body)
                        print(f"  Updated source-pr on #{existing['number']} from PR #{existing_pr_num} to PR #{pr_number}")
                        stats["commented"] += 1
                    else:
                        stats["skipped"] += 1

                # Full-suite: add throttled "still detected" comment (max once per 7 days)
                elif scan_type == "full-suite":
                    age = client.last_bot_comment_age_days(existing["number"])
                    if age < 0:
                        # Lookup failed -- skip commenting to avoid duplicates
                        print(f"  Skipped #{existing['number']}: comment lookup failed")
                        stats["skipped"] += 1
                    elif age >= 7:
                        comment = (
                            f"Still detected in full security suite "
                            f"run [#{run_id}]({run_url}) on branch `{branch}` "
                            f"(commit `{sha[:7]}`)."
                        )
                        result = client.add_comment(existing["number"], comment)
                        if result:
                            print(f"  Commented #{existing['number']}: still detected")
                            stats["commented"] += 1
                        else:
                            print(f"  Failed to comment #{existing['number']}: API error")
                            stats["skipped"] += 1
                    else:
                        stats["skipped"] += 1
                else:
                    stats["skipped"] += 1
            else:
                stats["skipped"] += 1

    # Auto-close: full-suite closes any resolved finding (guarded by tool check)
    if scan_type == "full-suite" and not dry_run:
        for fp, issue in fingerprint_to_issue.items():
            if issue["state"] != "open" or fp in current_fingerprints:
                continue
            # Only close if the tool that found this issue actually ran
            tool_prefix = fp.split(":")[0]
            if tools_with_results and tool_prefix not in tools_with_results:
                print(f"  Skipped auto-close #{issue['number']}: {tool_prefix} did not produce results this run")
                stats["skipped"] += 1
                continue
            comment = (
                f"This finding was **not detected** in the latest full security suite "
                f"run [#{run_id}]({run_url}) on branch `{branch}` "
                f"(commit `{sha[:7]}`). Auto-closing.\n\n"
                f"If this was closed in error, please reopen this issue."
            )
            client.add_comment(issue["number"], comment)
            client.update_issue(issue["number"], state="closed")
            print(f"  Auto-closed #{issue['number']}: {issue['title']} (no longer detected)")
            stats["closed"] += 1
    elif scan_type == "full-suite" and dry_run:
        for fp, issue in fingerprint_to_issue.items():
            if issue["state"] != "open" or fp in current_fingerprints:
                continue
            tool_prefix = fp.split(":")[0]
            if tools_with_results and tool_prefix not in tools_with_results:
                continue
            print(f"  [DRY RUN] Would auto-close #{issue['number']}: {issue['title']}")
            stats["closed"] += 1

    # Auto-close: PR scans close issues tagged with THIS PR when finding is resolved
    if scan_type == "pr" and pr_number and not dry_run:
        for fp, issue in fingerprint_to_issue.items():
            if issue["state"] != "open" or fp in current_fingerprints:
                continue
            body = issue.get("body", "")
            pr_match = SOURCE_PR_RE.search(body)
            if not pr_match or pr_match.group(1) != str(pr_number):
                continue  # Not tagged with this PR -- hands off
            tool_prefix = fp.split(":")[0]
            if tools_with_results and tool_prefix not in tools_with_results:
                print(f"  Skipped PR auto-close #{issue['number']}: {tool_prefix} did not run")
                stats["skipped"] += 1
                continue
            comment = (
                f"This finding was resolved in PR #{pr_number}. "
                f"Verified by security scan run [#{run_id}]({run_url}). Auto-closing."
            )
            client.add_comment(issue["number"], comment)
            client.update_issue(issue["number"], state="closed")
            print(f"  Resolved #{issue['number']}: {issue['title']} (fixed in PR #{pr_number})")
            stats["closed"] += 1
    elif scan_type == "pr" and pr_number and dry_run:
        for fp, issue in fingerprint_to_issue.items():
            if issue["state"] != "open" or fp in current_fingerprints:
                continue
            body = issue.get("body", "")
            pr_match = SOURCE_PR_RE.search(body)
            if not pr_match or pr_match.group(1) != str(pr_number):
                continue
            tool_prefix = fp.split(":")[0]
            if tools_with_results and tool_prefix not in tools_with_results:
                continue
            print(f"  [DRY RUN] Would auto-close #{issue['number']}: {issue['title']} (resolved in PR #{pr_number})")
            stats["closed"] += 1

    return stats


# ---------------------------------------------------------------------------
# PR Orphan Cleanup
# ---------------------------------------------------------------------------


def cleanup_pr_issues(client: GitHubIssueClient, pr_number: str, pr_type: str = "feature") -> None:
    """Close all open automated issues that originated from a specific PR.

    Called when a PR is closed without merging -- the findings only existed
    on the feature branch and were never merged to main/develop.

    Promotion PRs (develop->main) are skipped: their findings originate from
    develop, not from the promotion branch itself.
    """
    if pr_type == "promotion":
        print(f"  Skipping cleanup for promotion PR #{pr_number} -- "
              f"promotion PRs don't own findings, they originate from develop")
        return

    print(f"  Cleaning up issues from closed PR #{pr_number}...")

    existing_issues = client.list_automated_issues()
    closed_count = 0

    for issue in existing_issues:
        if issue["state"] != "open":
            continue
        body = issue.get("body", "")
        match = SOURCE_PR_RE.search(body)
        if match and match.group(1) == str(pr_number):
            comment = (
                f"Source PR #{pr_number} was closed without merging. "
                f"This finding only existed on the feature branch and was never merged. "
                f"Auto-closing."
            )
            client.add_comment(issue["number"], comment)
            client.update_issue(issue["number"], state="closed")
            print(f"    Closed #{issue['number']}: {issue['title']}")
            closed_count += 1

    print(f"  Cleaned up {closed_count} orphaned issue(s)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Create GitHub Issues from security findings")
    parser.add_argument("--sast-results", default=None, help="Directory with Semgrep JSON files")
    parser.add_argument("--dast-results", default=None, help="Directory with ZAP/Nuclei JSON files")
    parser.add_argument("--scan-type", default=None, choices=["pr", "full-suite"])
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--run-url", default=None)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr-author", default=None)
    parser.add_argument("--pr-number", default=None, help="Source PR number (for tagging issues)")
    parser.add_argument("--branch", default="unknown")
    parser.add_argument("--sha", default="unknown")
    parser.add_argument("--cleanup-pr", default=None, help="Close issues tagged with this PR number (orphan cleanup)")
    parser.add_argument("--pr-type", default="feature", choices=["feature", "promotion"],
                        help="PR type: 'feature' (default) or 'promotion' (develop->main). "
                             "Promotion PRs skip re-tagging and cleanup to avoid false closures.")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without calling API")
    args = parser.parse_args()

    token = os.environ.get("GH_TOKEN", "")
    if not token and not args.dry_run:
        print("No GH_TOKEN set, skipping issue creation")
        return

    # Cleanup mode: close orphaned issues from a closed PR
    if args.cleanup_pr:
        print(f"=== Security Issue Cleanup (PR #{args.cleanup_pr}, type={args.pr_type}) ===")
        if args.dry_run:
            print("  DRY RUN -- no API calls")
            return
        client = GitHubIssueClient(token, args.repo)
        cleanup_pr_issues(client, args.cleanup_pr, pr_type=args.pr_type)
        print("==========================================")
        return

    # Normal mode: validate required args
    missing = []
    for field in ["sast_results", "dast_results", "scan_type", "run_id", "run_url"]:
        if not getattr(args, field):
            missing.append(f"--{field.replace('_', '-')}")
    if missing:
        parser.error(f"The following arguments are required: {', '.join(missing)}")

    pr_number = args.pr_number if args.pr_number else None

    print(f"=== Security Finding Issue Automation ===")
    print(f"  Scan type: {args.scan_type}")
    print(f"  Repo: {args.repo}")
    print(f"  Branch: {args.branch}")
    print(f"  Run: #{args.run_id}")
    if pr_number:
        print(f"  PR: #{pr_number} (type: {args.pr_type})")
    print()

    # Check which tools produced valid results (guards against false auto-close)
    tools_with_results = detect_tools_with_results(args.sast_results, args.dast_results)
    reports_present = bool(tools_with_results)
    print(f"  Tools with results: {sorted(tools_with_results) or 'none'}")

    # Parse all findings
    findings = []

    print("  Parsing SAST results...")
    findings.extend(parse_semgrep_results(args.sast_results))

    print("  Parsing DAST results...")
    findings.extend(parse_zap_results(args.dast_results))
    findings.extend(parse_nuclei_results(args.dast_results))

    # Filter to issuable severities and deduplicate by fingerprint
    findings = [f for f in findings if f.severity in ISSUE_SEVERITIES]
    findings = dedup_findings(findings)

    print(f"  Total findings: {len(findings)}")
    for f in findings:
        status = " [SUPPRESSED]" if f.suppressed else ""
        print(f"    [{f.severity}] {f.tool}: {f.title}{status}")
    print()

    # Reconcile with GitHub
    if args.dry_run:
        print("  DRY RUN -- no API calls will be made")
        print()

    client = GitHubIssueClient(token, args.repo) if not args.dry_run else None  # type: ignore

    stats = reconcile_findings(
        findings=findings,
        client=client,  # type: ignore
        scan_type=args.scan_type,
        run_id=args.run_id,
        run_url=args.run_url,
        branch=args.branch,
        sha=args.sha,
        pr_author=args.pr_author,
        pr_number=pr_number,
        dry_run=args.dry_run,
        reports_present=reports_present,
        tools_with_results=tools_with_results,
        pr_type=args.pr_type,
    )

    # Export issue metadata as step output for PR comment
    issues = stats.get("issues", [])
    if issues:
        issue_numbers = ",".join(f"#{i['number']}" for i in issues)
        write_output("created_issues", issue_numbers)
        write_output("issues_json", json.dumps(issues))
    else:
        write_output("created_issues", "")
        write_output("issues_json", "[]")

    print()
    print(f"  Summary: {stats['created']} created, {stats['reopened']} reopened, "
          f"{stats['commented']} commented, {stats['closed']} closed, {stats['skipped']} skipped")
    print("==========================================")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Never block CI
        print(f"ERROR in create-finding-issues.py: {e}", file=sys.stderr)
        sys.exit(0)
