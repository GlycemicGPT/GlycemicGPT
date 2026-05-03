---
title: Security Testing
description: How security testing works in GlycemicGPT CI and how to extend it.
---

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

## Dependency Auto-Merge Coverage

This section is the contract that governs which Renovate dependency updates are eligible for automated merge. A dependency category is auto-merge eligible only when this table proves the relevant security tests fire when that category changes, and the relevant required status checks are wired to fail-block the merge if a regression slips in.

If a category is missing from the table, or any of its rows is marked as a gap, that category stays manual until the gap is closed. **Default-deny**: any dependency category not explicitly classified here as auto-merge-eligible stays manual.

This contract governs Renovate only. Dependabot is not enabled in this repository (no `.github/dependabot.yml`).

### Threat model

Coverage is scoped to what an end-user deploying GlycemicGPT exposes to the internet. The deploy examples (`deploy/examples/cloudflare-tunnel/`, `prod-caddy/`, `public-cloud/`, `external-redis/`) reverse-proxy only the web service. The API is reachable through Next.js rewrites on the docker network.

**The AI sidecar is internal-only.** No `ports:` mapping in any deploy example, no Caddyfile / cloudflared upstream points at it. This is the load-bearing fact behind the sidecar row's "no DAST required" verdict. If a future deploy example exposes the sidecar, that row must be re-evaluated.

The API-to-sidecar boundary is enforced by a shared bearer token (`SIDECAR_API_KEY`, see `sidecar/src/server.ts`). The SSRF tests in `scripts/security/test-research-security.py` are the load-bearing control that prevents a compromised dependency from turning the API into an SSRF gadget that reaches the sidecar via its docker-network address (which falls within RFC1918 and is therefore blocked by the existing SSRF allowlist).

GlycemicGPT also does not run AI models. The `apps/api` Python SDKs (`anthropic`, `openai`) and the sidecar's CLI subprocesses are HTTP/process bridges to models that the user hosts (subscription, BYOAI key, or local LLM). Prompt-injection or jailbreak testing of our code is out of scope -- there is no model in our containers to attack. Bridge-layer concerns (key handling, IDOR on AI endpoints, malformed-input crashes) are covered by the existing IDOR / secrets / fuzz suites.

### Defense-in-depth controls outside the test surface

Two controls in `.github/renovate.json5` complement the in-CI tests and are part of why patch+minor auto-merge is acceptable:

- **`minimumReleaseAge: "3 days"`** (line 24) -- newly published versions wait 3 days before Renovate creates a PR. This is the primary defense against compromised-publish events of the kind that hit `event-stream`, `colors.js`, and `chalk`/`debug`. Vulnerability-flagged updates override to `0 days` (line 55), which is intentional and correct.
- **`internalChecksFilter: "strict"`** (line 25) -- Renovate refuses to surface updates that fail its own pre-PR sanity checks (e.g., missing changelog metadata, parse failures).

This contract assumes the Renovate App itself (`glycemicgpt-renovate`) is uncompromised. The App's repository permissions are the upper bound on what Renovate can do; review them when permissions change. App-level compromise is out of scope for the dep-coverage table -- it would invalidate every row.

### Coverage table

Read this as: "if a Renovate PR changes a dependency in the **Dep Category** column, the **Tests That Fire** column is what runs and must pass before merge."

| Dep Category | Manager / Manifest | Trigger Path Filter | Tests That Fire | Auto-Merge Verdict |
|---|---|---|---|---|
| Python crypto / JWT (`python-jose[cryptography]`, `bcrypt`) | uv / `apps/api/uv.lock` | `apps/api/**` -> api=true | Semgrep `p/python` + `p/secrets`; auth pentests (`test-auth-flows.py`: wrong-key, alg-confusion, expired-token, timing enum); OSV-Scanner | SAFE (patch+minor) |
| Python web framework (`fastapi`, `starlette`, `pydantic`, `uvicorn`, `python-multipart`, `slowapi`) | uv / `apps/api/uv.lock` | `apps/api/**` | Semgrep; full DAST (CSRF, CORS, cookie flags, rate-limit XFF bypass `test-auth-flows.py`); IDOR (`test-data-isolation.py`); fuzzer (SQLi/XSS/path-traversal/JSON-shaped oversized/type-confusion, both auth & unauth -- multipart-specific oversized payloads are not asserted); ZAP API + Unauth API; nuclei API; OSV | SAFE (patch+minor) |
| Python ORM/DB (`sqlalchemy`, `alembic`, `asyncpg`, `redis`, `pgvector`) | uv / `apps/api/uv.lock` | `apps/api/**` | Semgrep `p/python` SQLi rules; fuzzer SQLi payloads; ZAP API SQLi active scan; IDOR cross-user reads; OSV | SAFE (patch+minor) |
| Python HTTP clients (`httpx`, `beautifulsoup4`) | uv / `apps/api/uv.lock` | `apps/api/**` | `test-research-security.py` SSRF (localhost, RFC1918 -- which includes the docker network where the sidecar lives, IMDS 169.254.169.254, IPv6 loopback, GCP metadata hostname `metadata.google.internal`); OSV | SAFE (patch+minor) |
| Python AI SDKs (`anthropic`, `openai`) | uv / `apps/api/uv.lock` | `apps/api/**` | Semgrep `p/secrets` (key leakage); fuzzer hits `/api/ai/*`; IDOR on AI endpoints; OSV. AI SDKs are HTTP clients to user-chosen LLMs -- prompt-injection testing is not applicable (see Threat model above). | SAFE (patch+minor) |
| Python data-source SDKs (`pydexcom`, `tconnectsync`, `apscheduler`, `fastembed`) | uv / `apps/api/uv.lock` | `apps/api/**` | Semgrep; OSV; fuzzer if they expose endpoints | SAFE (patch+minor) |
| Python parsing (`pillow`, `lxml`, `pyyaml`) | uv / `apps/api/uv.lock` | `apps/api/**` | `fuzz-api.py` type-confusion + oversized payloads; OSV | SAFE (patch+minor) |
| Web framework (`next`, `react`, `react-dom`) | npm / `apps/web/package-lock.json` | `apps/web/**` -> web=true | Semgrep `p/typescript` + `p/owasp-top-ten`; ZAP Web baseline + Unauth Web (CSP, headers, redirect leakage); nuclei Web; OSV | SAFE (patch+minor) |
| Web UI (`@tanstack/react-query`, `framer-motion`, `lucide-react`, `recharts`, `tailwind-merge`, `clsx`, `class-variance-authority`) | npm / `apps/web/package-lock.json` | `apps/web/**` | Semgrep TS; ZAP Web passive; OSV | SAFE (patch+minor) |
| Web markdown renderers (`react-markdown`, `remark-gfm`) | npm / `apps/web/package-lock.json` | `apps/web/**` | Semgrep TS XSS rules; ZAP Web XSS active scan; OSV | SAFE (patch); manual on minor |
| Web build/dev (`eslint*`, `jest`, `@testing-library/*`, `postcss`, `tailwindcss`, `autoprefixer`, `typescript`, `@types/*`) | npm / `apps/web/package-lock.json` | `apps/web/**` (devDep) | Same as web framework. devDeps don't ship to runtime. | SAFE (patch+minor) |
| Sidecar runtime (`express`) | npm / `sidecar/package-lock.json` | `sidecar/**` -> sidecar=true | Semgrep TS; OSV. Sidecar is internal-only (see Threat model); no internet exposure means no DAST is required at the sidecar boundary. AI traffic transits via API endpoints which are DAST-covered. | SAFE (patch+minor) |
| Sidecar build/test (`tsx`, `typescript`, `vitest`, `@types/*`) | npm / `sidecar/package-lock.json` | `sidecar/**` (devDep) | Semgrep TS; OSV | SAFE (patch+minor) |
| Mobile crypto (`bouncycastle`, `sqlcipher-android`, `androidx.security:security-crypto`) | gradle / `libs.versions.toml` | `apps/mobile/**` or `plugins/**` -> mobile=true | Semgrep `p/kotlin` + `p/secrets`; Android Gate (lint, unit tests); OSV recursive. **Gap**: no behavioral assertion on SQLCipher round-trip or `EncryptedSharedPreferences` contract; unit tests cover the wrappers but not the cipher itself. A silent cipher regression in a sqlcipher-android patch (e.g., key-derivation-iteration or HMAC change) would not be caught. | Always manual until a SQLCipher round-trip + EncryptedSharedPreferences contract test lands |
| Mobile HTTP (`okhttp`, `retrofit`, `moshi`) | gradle | `apps/mobile/**` or `plugins/**` | Semgrep Kotlin; Android Gate; OSV | SAFE (patch+minor) |
| Mobile UI / Compose / Hilt / Room / Wear OS / work | gradle | `apps/mobile/**` or `plugins/**` | Semgrep Kotlin; Android Gate (build, lint, unit tests on `:app`, `:pump-driver-api`, `:tandem-pump-driver`, `:wear-device`, `:watchface`); OSV | SAFE (patch+minor) |
| Docker base images (`python`, `node`, `alpine`) | docker / Dockerfiles | `**/Dockerfile*` -> infra=true -> `run_all=true` | Everything: full SAST + full DAST (auth, IDOR, fuzzer, ZAP, nuclei, both unauth scans); OSV | SAFE (digest + patch) |
| Docker service images (`pgvector/pgvector`, `redis`) | docker / docker-compose / Dockerfiles | `**/Dockerfile*` or `docker-compose*.yml` -> infra=true -> `run_all=true` | Everything: full SAST + full DAST; OSV | SAFE (digest + patch) |
| docker-compose / infra config | docker-compose / `docker-compose*.yml` | `docker-compose*.yml` -> infra=true | Same as above (run_all) | SAFE (digest + patch) |
| GitHub Actions (`actions/checkout`, `dorny/paths-filter`, `docker/*`, etc.) | github-actions / `.github/workflows/*.yml` | See **GitHub Actions Supply-Chain Hygiene** below | SHA-pin freezes audited code; `zizmor` static analysis (advisory mode today); Renovate vulnerability alerts cover known-compromised actions | SAFE (patch+minor) once `Workflow Lint Gate` is tightened from advisory to required status check (tracked in #542). Until then: manual. |
| Vendored Swagger / Redoc (SHA-pinned in `apps/api/Dockerfile`) | regex / Dockerfile | `**/Dockerfile*` -> infra=true -> run_all | Full DAST + ZAP Web (catches CSP/XSS regressions in served Swagger HTML) | SAFE (patch). Renovate already requires hash refresh in same PR. |
| Kustomize / K8s manifests (`k8s/base/*.yaml`) | n/a -- not Renovate-managed | n/a | n/a | Always manual |
| `scripts/security/requirements.txt` (security tooling itself) | manual -- not Renovate | `scripts/security/**` or `.github/workflows/security-scan*` -> security=true -> run_all | Full SAST + DAST + OSV | n/a (manual) |

### GitHub Actions Supply-Chain Hygiene

GitHub Actions are pinned by string (`uses: actions/checkout@v4`) and the strings reference mutable tags. A maintainer (or anyone who compromises a maintainer's account) can re-point a tag to a different commit; the next workflow run executes whatever code the tag now points to, with access to every secret exposed to that workflow. This is not theoretical: `tj-actions/changed-files` and `reviewdog` were both compromised this way during 2025, leaking secrets from thousands of repositories.

For GlycemicGPT specifically, the blast radius is high. The `glycemicgpt-merge` and `glycemicgpt-release` private keys are exposed to CI; both apps are bypass actors on `develop` and `main` branch protection. A compromised workflow could push directly to either branch, build poisoned release artifacts, and ship them to GHCR with valid pipeline signatures. In a medical-data context that is a serious supply-chain risk.

Two controls close this gap. Both must be operational before GitHub Actions enter the auto-merge tier.

1. **SHA-pin third-party actions.** All third-party actions in `.github/workflows/**` are pinned by commit SHA (e.g., `uses: dorny/paths-filter@d1c1ffe0248fe513906c8e24db8ea791d46f8590 # v3.0.3`). The `helpers:pinGitHubActionDigests` Renovate preset is enabled in `.github/renovate.json5` so SHAs stay current automatically while preserving the trailing `# vX.Y.Z` comment for human readability. First-party `actions/*` (GitHub-owned, stronger account security) are still tag-pinned today; Renovate's preset will produce a follow-up conversion PR moving them to SHAs as well. **Status: landed in PR #541.**
2. **`zizmor` workflow static analysis.** `.github/workflows/workflow-lint.yml` runs zizmor on PRs that touch `.github/workflows/**` and catches command-injection-via-input, excessive `permissions:` grants, dangerous `pull_request_target` patterns, cache poisoning, missing `persist-credentials: false`, and unpinned action references. **Status: landed in PR #541 in advisory mode** (does not fail builds; surfaces findings as run-log output and downloadable SARIF). Tightening to a required status check, with findings flowing through `create-finding-issues.py` like SAST/DAST findings do today, is tracked in #542.

A third control was originally planned -- OSV-Scanner over workflow files -- but was withdrawn after verifying that OSV-Scanner v2.3.3 has no GitHub Actions extractor (the path filter would have triggered the scan but extracted nothing). CVE alerting on actions remains via Renovate / Dependabot vulnerability alerts, which is a separate pipeline from OSV-Scanner and operates correctly.

GitHub Actions bumps stay manual until the `Workflow Lint Gate` is tightened from advisory to required (#542). At that point the row above moves to **SAFE (patch+minor)**.

### Auto-merge eligibility tiers

| Tier | Definition | Examples |
|---|---|---|
| **A -- always auto-merge** | Digest pins and lockfile maintenance. Behavior change is bounded by what already passed the full required-check suite. | Docker base image digest; `lockFileMaintenance` |
| **B -- auto-merge patch+minor** | Categories marked SAFE in the coverage table above. | All Python, web framework + UI + build, sidecar runtime + dev, mobile, GitHub Actions (after hygiene controls land), vendored docs |
| **C -- manual on minor** | Categories where minor bumps warrant human eyes. Patches still auto-merge. | Web markdown renderers (`react-markdown`, `remark-gfm`) |
| **D -- always manual** | Major bumps, categories with documented coverage gaps, K8s manifests, and any category not represented in the coverage table above. | All `major` updates; mobile crypto (until SQLCipher round-trip test lands); K8s/Kustomize files; new ecosystems |

### How this contract is enforced

The intended enforcement design is:

1. Renovate's package rules in `.github/renovate.json5` add (or do not add) the `automerge` label to each PR based on the dep category and update type.
2. A workflow (`.github/workflows/auto-merge-renovate.yml`) reads the label, mints a `glycemicgpt-merge` token, and calls `gh pr merge --auto --squash` for labeled PRs.
3. The `--auto` flag queues the merge but does not bypass required status checks -- if any of the gates in the **Tests That Fire** column fail, the merge does not fire.
4. `glycemicgpt-merge` is in the bypass-actor list for develop and main branch protection, so the merge can land despite CODEOWNERS without a human approval -- but only after every required check passes.

This is default-deny: a PR without the `automerge` label sits until a human reviews it.

### Rollout status

**As of this section landing, the enforcement mechanism above is not yet active.** The current `.github/renovate.json5` package rule (lines 99-105) sets `automerge: true` for `patch` and `minor` updates against `matchPackageNames: ["*"]` with no label gate. The `auto-merge-renovate.yml` workflow does not exist yet. Until both land:

- Renovate marks every patch+minor PR for auto-merge -- but the existing CODEOWNERS gate on develop blocks the actual merge, so PRs effectively wait for human approval today.
- This contract describes the **target** state, not current behavior. Read the table to understand which categories are intended to be auto-merge eligible; do not assume merges are gated by the table yet.

The enforcement work lands in a follow-up PR (Phase 1 of the Renovate auto-merge plan). At that point this section becomes the operational contract.

### When to update this section

Update the coverage table whenever any of the following occur:

- A new Renovate-managed ecosystem is added (e.g., new lockfile, new manager). Add a corresponding row to the coverage table BEFORE enabling auto-merge for that category.
- A new auth pattern is added (OAuth provider, API key flow, webhook signing). Update the relevant row's **Tests That Fire** column to reference the new test in `scripts/security/test-auth-flows.py`.
- A required status check is added or removed from develop's branch protection. Audit each row to confirm its **Tests That Fire** still resolves to a required check.
- A deploy example begins exposing a previously-internal service (e.g., the sidecar). Re-evaluate that service's row under the threat model.
- A `packageRule` or `groupName` is added or changed in `.github/renovate.json5`. New groups change which deps are bundled into a single PR, which changes which tests fire on which PRs -- audit affected rows.
- A new entry is added to `osv-scanner.toml` `IgnoredVulns`. An active suppression on a package in any auto-merge-eligible row weakens that row's coverage; weigh whether the row should be downgraded to manual until the suppression is reviewed.
- Quarterly review: re-walk the table to catch drift.

`lockFileMaintenance` PRs (run weekly Monday mornings via Renovate) bump every transitive dep simultaneously across `apps/api/uv.lock`, `apps/web/package-lock.json`, and `sidecar/package-lock.json`. They are auto-merge eligible (Tier A) because they touch the path filters of the rows they affect, so the same tests fire as for any other change to those manifests. The OSV-Scanner cron (`dependency-scan.yml`, Monday 6am UTC) runs alongside; verify these stay aligned if either schedule moves.

The table is the contract. If it does not match reality, fix the table or fix reality -- never let them diverge silently.

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
4. Add a row to the **Dependency Auto-Merge Coverage** table above describing what tests fire when the new dep category changes. Until the row exists, Renovate updates for the new ecosystem stay manual (default-deny).

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
