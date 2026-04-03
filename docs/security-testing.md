# Security Testing

How security testing works in the GlycemicGPT CI pipeline, and how to extend it as the platform grows.

## Overview

Security testing has five pillars:

1. **SAST** (`security-scan.yml`, `security-full-suite.yml`) -- Semgrep static analysis on Python, TypeScript, and Kotlin source code. Catches hardcoded secrets, injection patterns, and OWASP Top 10 at the code level.
2. **DAST & Auth Pentests** (`security-scan.yml`, `security-full-suite.yml`) -- behavior-based tests that spin up the Docker stack and attack it: auth flow penetration tests, IDOR prevention, SSRF blocking, OpenAPI-driven API fuzzing, nuclei vulnerability scanning, and OWASP ZAP active injection scanning.
3. **Dependency Vulnerability Scanning** (`dependency-scan.yml`) -- OSV-Scanner checks all lockfiles against the OSV database for known CVEs. Runs on every dependency change and weekly on a schedule.
4. **Static Analysis** (CodeRabbit) -- automated PR reviews that check for hardcoded secrets, medical safety violations, BLE protocol issues, and code quality. Configured in `.coderabbit.yaml`.
5. **Full Suite Pentests** (`security-full-suite.yml`) -- comprehensive security scan of the entire platform. Runs on merges to main/develop and manual dispatch. Status badge in README.

### Medical Device Context

GlycemicGPT handles glucose data, insulin pump telemetry, and AI-driven diabetes insights. Security failures in this context can have health consequences. The CI gates enforce a baseline: every PR must pass security checks before merging.

## Two-Workflow Architecture

### PR-Scoped Smart Testing (`security-scan.yml`)

Runs on every PR and push to main/develop. Uses **granular change detection** to only test what actually changed:

| Component | Paths Monitored | What Runs |
|-----------|----------------|-----------|
| API | `apps/api/**` | Semgrep Python, auth tests, IDOR, SSRF, fuzzer, nuclei API, ZAP API, ZAP Unauth API |
| Web | `apps/web/**` | Semgrep TypeScript, nuclei Web, ZAP Web baseline, ZAP Unauth Web |
| Sidecar | `sidecar/**` | Semgrep TypeScript |
| Mobile | `apps/mobile/**`, `plugins/**` | Semgrep Kotlin |
| Infra | `docker-compose*.yml`, `**/Dockerfile*` | Everything (config changes affect all services) |
| Security | `scripts/security/**`, `.github/workflows/security-scan*` | Everything |

Key optimization: **mobile-only PRs skip the Docker stack entirely** (~2 min vs ~25 min).

### Full Suite Pentests (`security-full-suite.yml`)

Runs everything regardless of what changed. Triggered by:
- Push to main or develop
- Manual dispatch

The **concurrency group** (`cancel-in-progress: false`) prevents runner clobbering during rapid merges. At most 1 running + 1 queued run exist at any time. When multiple PRs merge quickly, the queued run tests the latest HEAD (which includes all merged changes). Every merge is eventually covered.

## CI Security Gates

Checks 1-7 run unconditionally on every push/PR from `ci.yml`. Checks 8-10 use a gate job pattern that conditionally skips the heavy work when the PR doesn't touch relevant paths, while still reporting a green check so branch protection is satisfied.

| # | Required Check | Workflow | Triggers On |
|---|----------------|----------|-------------|
| 1 | Backend Tests | `ci.yml` | Every push/PR |
| 2 | Backend Lint | `ci.yml` | Every push/PR |
| 3 | Frontend Tests | `ci.yml` | Every push/PR |
| 4 | Frontend Lint | `ci.yml` | Every push/PR |
| 5 | Attribution Check | `ci.yml` | Every push/PR |
| 6 | Sidecar Tests | `ci.yml` | Every push/PR |
| 7 | GitGuardian | External | Every push/PR |
| 8 | Security Scan Gate | `security-scan.yml` | Component-specific (see table above) |
| 9 | Android Gate | `android.yml` | Mobile app/plugin changes |
| 10 | Dependency Scan Gate | `dependency-scan.yml` | Dependency file changes + weekly schedule |

Additionally, the **Security Full Suite** badge on the README reflects the pass/fail status of comprehensive pentests on main.

### Gate Job Pattern (Checks 8-10)

```text
detect-changes  -->  sast (if code changed)     -->  gate (always)
                -->  dast (if Docker needed)     -->
```

- **detect-changes**: Uses `dorny/paths-filter@v3` with 6 granular component filters. Computes derived flags (`needs_sast`, `needs_docker`, `run_all`).
- **sast**: Runs Semgrep on changed components. No Docker stack needed. Runs in parallel with DAST.
- **dast**: Builds Docker stack and runs targeted DAST tests based on which components changed.
- **gate**: Runs `if: always()`. Evaluates both SAST and DAST results. Posts unified PR comment via glycemicgpt-security.

## SAST (Static Analysis Security Testing)

**Tool:** [Semgrep](https://semgrep.dev/) with language-specific rulesets.

| Language | Rulesets | Scanned Paths |
|----------|----------|---------------|
| Python | `p/python`, `p/owasp-top-ten`, `p/secrets` | `apps/api/`, `scripts/security/` |
| TypeScript | `p/typescript`, `p/owasp-top-ten`, `p/secrets` | `apps/web/`, `sidecar/` |
| Kotlin | `p/kotlin`, `p/android`, `p/secrets` | `apps/mobile/`, `plugins/` |

In the full suite workflow, SARIF results are uploaded to the GitHub Security tab for centralized vulnerability tracking.

## DAST & Auth Penetration Tests

### Test Suites

1. **Auth flow tests** (`test-auth-flows.py`) -- 15 behavior-based tests covering registration, login, token handling, RBAC, and logout.
2. **Data isolation tests** (`test-data-isolation.py`) -- OpenAPI-driven. Auto-discovers ALL endpoints. Tests unauthenticated access (401), CSRF enforcement (403), and cross-user data isolation (IDOR).
3. **Research security tests** (`test-research-security.py`) -- SSRF prevention, rate limiting, source limits, input validation, CSRF enforcement on research endpoints.
4. **API fuzzer** (`fuzz-api.py`) -- OpenAPI-driven. Runs two passes: authenticated (with session) and unauthenticated (attacker perspective). Sends SQL injection, XSS, path traversal, type confusion, and oversized payloads to all discovered endpoints. Asserts no 500 errors in either pass.
5. **Nuclei DAST** -- Known vulnerability templates against API and Web surfaces.
6. **ZAP API active scan** (`zap-api-plan.yaml`) -- Authenticated, OpenAPI-driven injection testing (SQLi, XSS, SSTI, CRLF, path traversal). Auto-discovers all endpoints.
7. **ZAP Web scan** (`zap-web-plan.yaml`) -- Pre-seeds all known page URLs + standard spider + passive/active scanning on the web frontend. Tests security headers, cookie flags, CSP, and injection through the proxy path.
8. **ZAP Unauthenticated API pentest** (`zap-unauth-api-plan.yaml`) -- Full attacker-perspective scan of the **entire API surface** without credentials. Discovers all endpoints from `/openapi.json` and probes every one -- public and authenticated alike. Tests injection, info disclosure in error responses, security headers, Host header injection, and what leaks when authenticated endpoints return 401/403. Runs on every PR regardless of which component changed.
9. **ZAP Unauthenticated Web pentest** (`zap-unauth-web-plan.yaml`) -- Full attacker-perspective scan of the **entire web application** without credentials. Probes all pages including protected `/dashboard/*` routes to test redirect behavior, auth enforcement, and info leakage. Includes error handling probes (invalid invitation tokens, nonexistent pages). Runs on every PR regardless of which component changed.

### Auto-discovery

Tests 2, 4, 6, and 8 read `/openapi.json` from the live API to discover endpoints. **New API routes are automatically tested without any test code changes.**

Test 7 pre-seeds all known page URLs from the Next.js app structure and uses the standard spider to discover additional linked pages. (AJAX Spider with headless Firefox was evaluated but risks OOM on standard GitHub runners with 7GB RAM.)

Tests 8 and 9 simulate a real external attacker. They run without session cookies or CSRF tokens, probe the **entire** application surface (not just public endpoints), and run on **every PR** regardless of which component changed. An attacker doesn't care which files you modified -- they probe everything. Protected endpoints are intentionally tested to verify auth enforcement and catch info leakage in error responses. Findings are tracked as separate issues from the authenticated scans (distinct fingerprints: `zap-unauth-api:*` and `zap-unauth-web:*`).

### Evaluation scripts

Results are evaluated by standalone Python scripts (not inline shell):
- `scripts/security/evaluate-sast.py` -- reads Semgrep JSON per language, counts ERROR-severity findings, handles scanner crashes and corrupt JSON
- `scripts/security/evaluate-zap.py` -- reads ZAP traditional-json reports, counts Medium+ alerts, supports suppressions

### ZAP authentication

The authenticated ZAP plans (`zap-api-plan.yaml`, `zap-web-plan.yaml`) use `${ZAP_SESSION}` and `${ZAP_CSRF}` placeholders. ZAP's Automation Framework does **not** expand environment variables, so CI uses `envsubst` to bake actual cookie values into resolved copies before passing them to ZAP. The resolved files (`*.resolved.yaml`) are gitignored and exist only during the CI run.

The unauthenticated ZAP plans (`zap-unauth-api-plan.yaml`, `zap-unauth-web-plan.yaml`) have no placeholders and are used directly (no `envsubst` needed). They omit the `replacer` and `script` jobs, so ZAP sends no session cookies.

### Suppressions

Two suppression mechanisms exist:

| File | Tool | Format |
|------|------|--------|
| `osv-scanner.toml` | OSV-Scanner | TOML `[[IgnoredVulns]]` with `id` and `reason` |
| `scripts/security/zap-suppressions.json` | ZAP evaluator | JSON with `pluginId`, `scan`, and `reason` |

Every suppression **must** include a reason and should reference the issue that will fix the underlying problem (e.g., `Fix tracked in #123`). Suppressed findings are still logged in CI output (visible, not hidden) but don't fail the build. Review suppressions quarterly.

### Test results

Scan results are uploaded as GitHub Actions artifacts with 30-day retention:
- `sast-results` -- Semgrep JSON output
- `dast-results` -- ZAP reports, nuclei JSON, custom test output

### Issue automation

Security findings are automatically tracked as GitHub Issues via glycemicgpt-security. The full lifecycle:

| Event | What happens |
|-------|-------------|
| PR scan finds a vulnerability | Issue created, assigned to PR author, tagged with PR number |
| Contributor pushes a fix | Next scan auto-closes the issue ("resolved in PR #X") |
| PR merged, finding still present | Full suite keeps the issue open |
| PR merged, finding resolved | Full suite auto-closes the issue |
| Feature PR closed without merging | Cleanup job closes issues tagged with that PR |
| Promotion PR closed without merging | Cleanup skipped (findings originate from develop, not the promotion branch) |
| Finding reappears after fix reverted | Full suite reopens the closed issue |
| Full suite runs, finding still present | "Still detected" comment added (throttled to once per 7 days) |

**Tool-aware guards:** Auto-close only applies to findings from tools that actually produced results in the current run. If SAST crashes but DAST succeeds, only DAST-sourced issues are eligible for closure.

**Deduplication:** Each finding gets a deterministic fingerprint stored as an HTML comment in the issue body. Before creating, the script checks all existing automated issues to prevent duplicates.

**Suppressed findings** still get issues created, but labeled `accepted-risk` with the suppression reason. This creates a paper trail -- every known risk has a visible issue.

**Script:** `scripts/security/create-finding-issues.py` -- runs in the gate/summary job of both workflows. Supports `--dry-run` for local testing.

## Dependency Vulnerability Scanning

**Workflow:** `.github/workflows/dependency-scan.yml`
**Triggers:** Dependency file changes + weekly Monday 6am UTC schedule + manual dispatch.

### Covered manifests

| Ecosystem | Lockfile | Auto-updated by |
|-----------|----------|-----------------|
| Python (API) | `apps/api/uv.lock` | Renovate |
| Node.js (Web) | `apps/web/package-lock.json` | Renovate |
| Node.js (Sidecar) | `sidecar/package-lock.json` | Renovate |
| Python (Security) | `scripts/security/requirements.txt` | Manual |
| Android (Gradle) | `apps/mobile/gradle/libs.versions.toml` | Renovate (via recursive scan) |

The scanner uses [Google OSV-Scanner](https://google.github.io/osv-scanner/) with explicit lockfile paths for Python/Node and recursive scanning for Gradle.

### Handling findings

| Severity | Action | Timeline |
|----------|--------|----------|
| Critical / High | Block merge, fix immediately | Same PR or hotfix |
| Medium | Create issue, fix in current sprint | 1-2 weeks |
| Low | Triage -- fix if easy, suppress if not exploitable | Best effort |

### Suppressing false positives

Add entries to `osv-scanner.toml` in the repo root:

```toml
[[IgnoredVulns]]
id = "GHSA-xxxx-yyyy-zzzz"
reason = "Not exploitable -- only affects feature X which we don't use"
```

Every suppression must include a reason. Review suppressions quarterly.

## Adding Security Tests for New Integrations

### New API endpoints

**Auto-covered.** The API fuzzer, IDOR tests, and ZAP scan all read `/openapi.json` at runtime. New FastAPI routes with proper type hints are automatically tested. No manual changes needed.

### New web pages

**Auto-covered (full suite).** The ZAP web scan pre-seeds known URLs and uses AJAX Spider to discover new routes. If you add a new page to `apps/web/src/app/`, add its URL to `scripts/security/zap-web-plan.yaml` in the requestor section for guaranteed coverage.

### New auth patterns (OAuth, API keys, webhooks)

**Manual.** Add tests to `scripts/security/test-auth-flows.py`.

### New dependencies

**Manual.** If you add a new ecosystem or lockfile:

1. Add the lockfile path to the `scan` step in `.github/workflows/dependency-scan.yml`.
2. Add the lockfile path to the `detect-changes` filter in the same workflow.
3. Verify the scan runs on the next PR.

### New plugins

**Auto-covered** in most cases:

- **Android Gate**: Plugin code under `plugins/**` triggers the Android build/test/lint pipeline.
- **API fuzzer + ZAP**: If a plugin adds backend API endpoints, they're auto-discovered via `/openapi.json`.
- **SAST**: Kotlin plugin code is scanned by Semgrep with `p/kotlin` and `p/android` rulesets.
- **Dependency scan**: If the plugin adds dependencies to the Gradle version catalog, the recursive scan picks them up.

Only manual action needed: if a plugin introduces a new auth pattern (see above).

## Mobile Security

The Android app has these security measures, verified through different mechanisms:

| Measure | Verification |
|---------|-------------|
| SQLCipher database encryption | Unit tests + CodeRabbit review |
| EncryptedSharedPreferences for tokens | Unit tests + CodeRabbit review |
| HTTPS enforcement (network_security_config) | Android Lint + CodeRabbit review |
| No sensitive data in logs | CodeRabbit BLE Protocol Safety check |
| Dependency vulnerabilities | OSV-Scanner (recursive Gradle scan) |
| Code quality / safety | CodeRabbit Medical Safety Review check |
| Hardcoded secrets, insecure patterns | Semgrep SAST (`p/kotlin`, `p/android`, `p/secrets`) |

No DAST scanning for mobile -- BLE protocol fuzzing would require hardware and is out of scope for CI.

## Running Locally

### Full DAST suite

```bash
# Start the test stack
COMPOSE_PROJECT_NAME=glycemicgpt-test docker compose -f docker-compose.yml -f docker-compose.test.yml up --build -d

# Wait for health
curl -sf http://localhost:8001/health
curl -sf http://localhost:3001

# Run auth tests
TEST_SECRET_KEY=$(COMPOSE_PROJECT_NAME=glycemicgpt-test docker compose -f docker-compose.yml -f docker-compose.test.yml exec -T api printenv SECRET_KEY) \
  API_URL=http://localhost:8001 WEB_URL=http://localhost:3001 \
  python scripts/security/test-auth-flows.py

# Run IDOR tests
API_URL=http://localhost:8001 TEST_PASSWORD=your-test-password \
  python scripts/security/test-data-isolation.py

# Run fuzzer
API_URL=http://localhost:8001 python scripts/security/fuzz-api.py

# Run DAST (requires nuclei installed)
API_URL=http://localhost:8001 WEB_URL=http://localhost:3001 ./scripts/security/run-dast.sh

# Tear down
COMPOSE_PROJECT_NAME=glycemicgpt-test docker compose -f docker-compose.yml -f docker-compose.test.yml down -v
```

### SAST only (no Docker needed)

```bash
pip install semgrep
semgrep scan --config p/python --config p/owasp-top-ten --config p/secrets apps/api/ scripts/security/
semgrep scan --config p/typescript --config p/owasp-top-ten --config p/secrets apps/web/ sidecar/
semgrep scan --config p/kotlin --config p/android --config p/secrets apps/mobile/ plugins/
```

### Dependency scan only

```bash
go install github.com/google/osv-scanner/v2/cmd/osv-scanner@v2.3.3
osv-scanner scan \
  --lockfile=apps/api/uv.lock \
  --lockfile=apps/web/package-lock.json \
  --lockfile=sidecar/package-lock.json \
  --lockfile=scripts/security/requirements.txt \
  --recursive \
  --config=osv-scanner.toml .
```
