# Security Testing

How security testing works in the GlycemicGPT CI pipeline, and how to extend it as the platform grows.

## Overview

Security testing has three pillars:

1. **DAST & Auth Pentests** (`security-scan.yml`) -- behavior-based tests that spin up the Docker stack and attack it: auth flow penetration tests, OpenAPI-driven API fuzzing, and nuclei vulnerability scanning.
2. **Dependency Vulnerability Scanning** (`dependency-scan.yml`) -- OSV-Scanner checks all lockfiles against the OSV database for known CVEs. Runs on every dependency change and weekly on a schedule.
3. **Static Analysis** (CodeRabbit) -- automated PR reviews that check for hardcoded secrets, medical safety violations, BLE protocol issues, and code quality. Configured in `.coderabbit.yaml`.

### Medical Device Context

GlycemicGPT handles glucose data, insulin pump telemetry, and AI-driven diabetes insights. Security failures in this context can have health consequences. The CI gates enforce a baseline: every PR must pass security checks before merging.

## CI Security Gates

Checks 1-7 run unconditionally on every push/PR from `ci.yml`. Checks 8-10 use a gate job pattern (described below) that conditionally skips the heavy work when the PR doesn't touch relevant paths, while still reporting a green check so branch protection is satisfied.

| # | Required Check | Workflow | Triggers On |
|---|----------------|----------|-------------|
| 1 | Backend Tests | `ci.yml` | Every push/PR |
| 2 | Backend Lint | `ci.yml` | Every push/PR |
| 3 | Frontend Tests | `ci.yml` | Every push/PR |
| 4 | Frontend Lint | `ci.yml` | Every push/PR |
| 5 | Attribution Check | `ci.yml` | Every push/PR |
| 6 | Sidecar Tests | `ci.yml` | Every push/PR |
| 7 | GitGuardian | External | Every push/PR |
| 8 | Security Scan Gate | `security-scan.yml` | Backend/web/sidecar/security script changes |
| 9 | Android Gate | `android.yml` | Mobile app/plugin changes |
| 10 | Dependency Scan Gate | `dependency-scan.yml` | Dependency file changes + weekly schedule |

Checks 1-7 are the original required checks. Checks 8-10 were added as part of Epic 28 security hardening.

### Gate Job Pattern (Checks 8-10)

Each gate workflow (`security-scan.yml`, `android.yml`, `dependency-scan.yml`) has three jobs:

```text
detect-changes  -->  actual-work (if relevant)  -->  gate (always)
```

- **detect-changes**: Uses `dorny/paths-filter@v3` to check if the PR touches relevant files. Outputs a boolean.
- **actual-work**: Only runs if detect-changes says yes (or `workflow_dispatch`/`schedule`). Does the real work (build, test, scan).
- **gate**: Runs `if: always()`. If detect-changes said no, exits 0 (skip). If detect-changes said yes, checks whether actual-work succeeded.

This means: the gate job always reports a status, even when the scan is skipped. GitHub branch protection sees a green check either way.

## DAST & Auth Penetration Tests

**Workflow:** `.github/workflows/security-scan.yml`
**Triggers:** Backend, web, sidecar, Dockerfiles, compose files, or security script changes.

### What it does

1. **Builds the full Docker stack** (`docker-compose.yml` + `docker-compose.test.yml`) in CI.
2. **Waits for health** -- API and web must respond before tests start.
3. **Auth flow tests** (`scripts/security/test-auth-flows.py`) -- 15 behavior-based tests that verify specific security properties:
   - Registration validation (email format, password strength, duplicate detection)
   - Login security (invalid credentials, account enumeration prevention)
   - Token handling (JWT validation, expired token rejection, session isolation)
   - Authorization (RBAC enforcement, horizontal privilege escalation prevention)
   - Logout (token invalidation, session cleanup)
4. **API fuzzer** (`scripts/security/fuzz-api.py`) -- self-adapting fuzzer that reads `/openapi.json` at runtime. It discovers all endpoints automatically and sends malformed/adversarial inputs. No manual updates needed when endpoints are added.
5. **DAST scanner** (`scripts/security/run-dast.sh`) -- runs nuclei with web vulnerability templates against the live stack. Skips gracefully if nuclei is not installed (local dev).

### Test results

Scan results are uploaded as a GitHub Actions artifact (`security-scan-results`) with 30-day retention.

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

The scanner uses [Google OSV-Scanner](https://google.github.io/osv-scanner/) with explicit lockfile paths for Python/Node and recursive scanning for Gradle (reads the version catalog directly).

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

### Weekly scheduled scan

The Monday 6am UTC scan catches newly disclosed CVEs against existing dependencies, even when no code has changed. It bypasses the path filter and always runs the full scan.

## Adding Security Tests for New Integrations

### New API endpoints

**Auto-covered.** The API fuzzer reads `/openapi.json` at runtime and discovers all endpoints. New FastAPI routes with proper type hints are automatically fuzzed. No manual changes needed.

### New auth patterns (OAuth, API keys, webhooks)

**Manual.** Add tests to `scripts/security/test-auth-flows.py`. Examples:

- **Nightscout integration** (API key auth): test that invalid API keys are rejected, keys are not leaked in responses, and revoked keys stop working.
- **Omnipod plugin** (if it adds cloud auth): test token lifecycle, refresh flow, and session isolation.
- **Webhook receivers**: test signature validation, replay protection, and that unsigned payloads are rejected.

Each test should:
- Use a unique email/identity (no shared state between tests)
- Clean up sessions after itself
- Make specific assertions about security properties (not just "status 200")

### New dependencies

**Manual.** If you add a new ecosystem or lockfile:

1. Add the lockfile path to the `scan` step in `.github/workflows/dependency-scan.yml`.
2. Add the lockfile path to the `detect-changes` filter in the same workflow.
3. Verify the scan runs on the next PR.

### New plugins

**Auto-covered** in most cases:

- **Android Gate**: Plugin code under `plugins/pump-driver-api/**` and `plugins/shipped/**` triggers the Android build/test/lint pipeline.
- **API fuzzer**: If a plugin adds backend API endpoints, they're auto-discovered via `/openapi.json`.
- **Dependency scan**: If the plugin adds dependencies to the Gradle version catalog, the recursive scan picks them up.

Only manual action needed: if a plugin introduces a new auth pattern (see above).

## Mobile Security

The Android app has these security measures, verified through different mechanisms:

| Measure | Verification |
|---------|-------------|
| SQLCipher database encryption | Unit tests + CodeRabbit review |
| EncryptedSharedPreferences for tokens | Unit tests + CodeRabbit review |
| Certificate pinning (OkHttp) | Unit tests |
| No sensitive data in logs | CodeRabbit BLE Protocol Safety check |
| Dependency vulnerabilities | OSV-Scanner (recursive Gradle scan) |
| Code quality / safety | CodeRabbit Medical Safety Review check |

No DAST scanning for mobile -- there's no web UI to attack. BLE protocol fuzzing would require hardware and is out of scope for CI.

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

# Run fuzzer
API_URL=http://localhost:8001 python scripts/security/fuzz-api.py

# Run DAST (requires nuclei installed)
API_URL=http://localhost:8001 WEB_URL=http://localhost:3001 ./scripts/security/run-dast.sh

# Tear down
COMPOSE_PROJECT_NAME=glycemicgpt-test docker compose -f docker-compose.yml -f docker-compose.test.yml down -v
```

### Dependency scan only

```bash
# Install OSV-Scanner (same version as CI)
go install github.com/google/osv-scanner/v2/cmd/osv-scanner@v2.3.3

# Scan all lockfiles
osv-scanner scan \
  --lockfile=apps/api/uv.lock \
  --lockfile=apps/web/package-lock.json \
  --lockfile=sidecar/package-lock.json \
  --lockfile=scripts/security/requirements.txt \
  --recursive \
  --config=osv-scanner.toml .
```
