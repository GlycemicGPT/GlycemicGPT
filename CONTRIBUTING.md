# 🤝 Contributing to GlycemicGPT

Thanks for your interest in contributing to GlycemicGPT! Whether you're fixing a typo, squashing a bug, or building a whole new feature -- we appreciate you. 💙

This guide covers everything you need to know to get started.

---

## ⚠️ Safety First -- Please Read

**GlycemicGPT interacts with real diabetes management data. Incorrect data display or bad suggestions can directly impact health decisions.**

Before writing any code, please understand these non-negotiable rules:

- 🏷️ **All** AI-generated outputs must be clearly labeled as **suggestions, not medical advice**
- 💉 Insulin dosing recommendations must **always** include safety disclaimers
- 🧪 Test thoroughly -- a wrong number on a glucose chart is not just a UI bug, it's a safety issue
- 🔒 Safety limits (glucose range, max bolus, max basal) are enforced by the platform via `SafetyLimits` (backend-synced, user-configurable). These limits validate incoming pump and CGM history values; when a reading falls outside the limits, plugins must discard it (do not return, emit, or persist it) and log the rejection with the violated limit -- see the [Plugin Architecture Guide](docs/dev/plugin-architecture.mdx).
- 🚫 **No device control** -- GlycemicGPT is a monitoring and analysis platform

### Device Data Drivers

GlycemicGPT is a monitoring and analysis platform. The plugin SDK exists for one purpose: **community-built device data drivers that read from new hardware**. Pumps, CGMs, BGMs, and other diabetes devices all have proprietary protocols, and a plugin SDK is the only realistic way to support the long tail of devices the community uses. Plugins read glucose values, insulin-on-board, basal rates, bolus history, and pump status. They do not control devices.

**The project does not provide, distribute, document, or solicit plugins that expose any therapeutic write or control surface -- no bolus dosing, no basal rate changes, no pump-setting modifications.** This applies to every official build (Docker images, APKs, App Store / Play Store releases) and to every contribution merged into this repository. Pull requests that introduce therapeutic write primitives will not be merged. Non-therapeutic device-management operations that already exist in the SDK (CGM calibration, BLE pair/unpair, connect/disconnect) are session and lifecycle operations -- not therapy -- and remain permitted.

**Forks are not endorsed.** Forks of this project that add device control capabilities operate outside the GlycemicGPT project. The maintainers do not review them, recommend them, accept liability for them, or accept contributions to this repository whose intent is to enable them. Users who choose to run such forks become the manufacturer of their own personal medical device, consistent with the legal posture of Loop, AndroidAPS, and other DIY diabetes projects -- see [MEDICAL-DISCLAIMER.md](MEDICAL-DISCLAIMER.md).

**Platform safety enforcement.** The plugin SDK has no insulin delivery primitives -- there is no API on any capability interface for issuing a bolus, modifying basal rates, or otherwise writing therapeutic state to a pump. The AI layer has no architectural path to such a write surface. Device-management commands that *do* exist in the SDK (CGM calibration, BLE pair/unpair, connect/disconnect) are session/lifecycle operations, not therapy. Runtime-loaded plugins are sandboxed via `RestrictedPluginContext`, which is the current architectural restriction. The plugin registry will additionally be hardened to refuse loading any plugin declaring a capability outside the official enum; see [ROADMAP.md](ROADMAP.md) §Phase 1. Safety constraints (glucose range, max bolus, max basal) are platform-defined and backend-synced; plugins use them to drop implausible readings and cannot bypass them.

**Contributing a data driver:**

1. Pick a device that isn't already supported (see the [Plugin Architecture Guide](docs/dev/plugin-architecture.mdx) for the capability matrix)
2. Open an issue describing the device, the protocol you intend to use, and the data you'll surface
3. Submit a PR with a new Gradle module under `plugins/shipped/<device-name>/` (these modules are compiled into official builds), declaring only capabilities from the official read-only enum. For device data drivers the relevant capabilities are typically `GLUCOSE_SOURCE`, `INSULIN_SOURCE`, `PUMP_STATUS`, `BGM_SOURCE`, `CALIBRATION_TARGET`, and/or `BOLUS_CATEGORY_PROVIDER`. The `DATA_SYNC` capability is reserved for future external-sync integrations (Nightscout, Tidepool); its interface is not yet defined and it is not currently implementable
4. Include unit tests, especially for parsing and `SafetyLimits` validation of incoming values
5. Existing plugins (`:tandem-pump-driver`, under `plugins/shipped/tandem/`) serve as the reference implementation. Runtime-loaded plugins (under `plugins/example/`) are a separate, advanced contribution path -- they are not compiled into official builds and run with `RestrictedPluginContext`

---

## 📑 Table of Contents

- [Project Roles](#project-roles)
- [Ways to Contribute](#ways-to-contribute)
- [Finding Something to Work On](#finding-something-to-work-on)
- [Development Setup](#development-setup)
- [Branching & Workflow](#branching--workflow)
- [Commit Messages](#commit-messages)
- [Before You Submit](#before-you-submit)
- [Pull Request Process](#pull-request-process)
- [Code Style](#code-style)
- [AI-Assisted Development & Attribution Policy](#ai-assisted-development--attribution-policy)
- [Project Structure](#project-structure)
- [Plugin Development](#plugin-development)
- [Release Channels](#release-channels)
- [License](#license)
- [Questions?](#questions)

---

## 👥 Project Roles

GlycemicGPT has three roles: **Contributor**, **Committer**, and **Maintainer**. Most people start as contributors -- just open a PR, file an issue, or join a discussion.

If you contribute consistently and demonstrate good judgment (especially around medical safety), you may be invited to become a committer with Write access. Committers can approve PRs, triage issues, and own specific components.

Maintainers are project stewards responsible for releases, security, and architectural decisions. It's an invitation-only role that comes after sustained involvement as a committer.

For the full details -- including how decisions are made, what each role can and can't do, and how branch protection works -- see [GOVERNANCE.md](GOVERNANCE.md).

---

## 💡 Ways to Contribute

There are many ways to help, not all of them involve writing code:

- 🐛 **Report bugs** -- Use the [Bug Report](https://github.com/GlycemicGPT/GlycemicGPT/issues/new?template=bug_report.yml) or [Mobile App Issue](https://github.com/GlycemicGPT/GlycemicGPT/issues/new?template=mobile_report.yml) template
- ✨ **Request features** -- Use the [Feature Request](https://github.com/GlycemicGPT/GlycemicGPT/issues/new?template=feature_request.yml) template
- 📝 **Improve documentation** -- Typos, unclear instructions, missing guides
- 🧪 **Write tests** -- More coverage is always welcome
- 🔍 **Review PRs** -- Fresh eyes catch things automated checks can't
- 💬 **Answer questions** -- Help others in [Discussions](https://github.com/GlycemicGPT/GlycemicGPT/discussions)

Before opening an issue, please search [existing issues](https://github.com/GlycemicGPT/GlycemicGPT/issues?q=is%3Aissue) to avoid duplicates. For general questions and support, use [Discussions](https://github.com/GlycemicGPT/GlycemicGPT/discussions/categories/q-a) instead of creating an issue.

---

## 🔍 Finding Something to Work On

Not sure where to start? Browse [open issues](https://github.com/GlycemicGPT/GlycemicGPT/issues) and look for these labels:

- 🏷️ **`good first issue`** -- Small, well-scoped tasks ideal for new contributors
- 🏷️ **`help wanted`** -- We'd love community help on these
- 🏷️ **`bug`** -- Known bugs waiting for a fix

> **Tip:** Not every label will have open issues at all times. If none are tagged yet, browse the full [issue list](https://github.com/GlycemicGPT/GlycemicGPT/issues) or check the [Ideas discussion board](https://github.com/GlycemicGPT/GlycemicGPT/discussions/categories/ideas) for inspiration.

If you'd like to work on something, comment on the issue to let others know. For larger changes, please open an issue or start a [discussion](https://github.com/GlycemicGPT/GlycemicGPT/discussions) first to discuss the approach before investing time in a PR.

---

## 🛠️ Development Setup

### Prerequisites

You only need the tools for the component(s) you're working on:

| Component | You Need |
|-----------|----------|
| 🌐 Web UI | Docker + Docker Compose |
| 🐍 Backend API | Docker + Docker Compose (or Python 3.12+ with [UV](https://docs.astral.sh/uv/)) |
| 🤖 AI Sidecar | Docker + Docker Compose (or Node.js 20+) |
| 📱 Mobile App | JDK 17, Android SDK Platform 35 (targetSdk 35, minSdk 30) |
| ⌚ Wear OS | JDK 17, Android SDK Platform 36, Wear OS system image. Requires phone + watch emulators paired via ADB. |
| 📝 Docs only | Just a text editor! |

### 🚀 Quick Start (Web/API -- recommended for most contributors)

The fastest way to get a working dev environment:

```bash
# 1. Fork and clone
git clone https://github.com/<your-username>/GlycemicGPT.git
cd GlycemicGPT

# 2. Add upstream remote
git remote add upstream https://github.com/GlycemicGPT/GlycemicGPT.git

# 3. Install the git commit-msg hook (strips prohibited attribution lines)
#    If scripts/hooks/commit-msg doesn't exist, skip this step -- CI enforces it too
cp scripts/hooks/commit-msg .git/hooks/commit-msg
chmod +x .git/hooks/commit-msg

# 4. Copy environment file (defaults work for local dev)
cp .env.example .env

# 5. Start all services
docker compose up --build -d

# 6. Verify everything is running
curl localhost:8000/health   # API -- should return {"status": "healthy"}
curl localhost:3456/health   # AI sidecar -- should return {"status": "ok"}
# Web UI is at http://localhost:3000
```

### Services

| Service | Port | Description |
|---------|------|-------------|
| Web UI | 3000 | Next.js 15 frontend |
| API | 8000 | FastAPI backend |
| AI Sidecar | 3456 | AI provider proxy |
| PostgreSQL | 5432 | Database |
| Redis | 6379 | Cache / SSE broker |

### 📱 Mobile App Setup (Android)

Only needed if you're working on the phone or Wear OS apps:

```bash
cd apps/mobile

# Build debug APKs (phone + Wear OS)
./gradlew assembleDebug

# Run unit tests
./gradlew testDebugUnitTest

# Run lint
./gradlew lintDebug
```

### 🐍 Backend Setup (without Docker)

If you prefer running the API directly:

> **Note:** Backend tests require a running PostgreSQL instance. The easiest way is to start just the database container: `docker compose up db -d`. Tests use the connection settings from your `.env` file.

```bash
cd apps/api
uv sync              # Install dependencies
uv run pytest        # Run tests (requires PostgreSQL -- see note above)
uv run ruff check .  # Lint
uv run ruff format --check .  # Format check
```

### 🖥️ Frontend Setup (without Docker)

If you prefer running the frontend directly:

```bash
cd apps/web
npm install    # Install dependencies
npm test       # Run tests
npm run lint   # Lint
npm run dev    # Start dev server (http://localhost:3000)
```

> **Note:** Running `npm run dev` alone only tests frontend rendering. For full integration testing (API calls, auth, SSE), use Docker Compose.

### 🤖 Sidecar Setup (without Docker)

```bash
cd sidecar
npm install    # Install dependencies
npm test       # Run tests
```

---

## 🌿 Branching & Workflow

We use a **develop/main** branching model:

```
feature branch --> squash merge --> develop --> merge --> main
                                      |                     |
                                  dev builds           stable releases
                                  debug APKs           signed APKs
                                  Docker :dev          Docker :latest
```

### Rules

- **`develop`** is the integration branch. **All contributor PRs target `develop`.**
- **`main`** is the stable release branch. Do **not** target PRs to `main`.
- Feature branches are created from `develop` and squash-merged back.

> **Note on the GitHub branch counter:** GitHub's branch comparison may show `develop` as a number of commits *behind* `main`. This is a cosmetic SHA-graph artifact, not a content drift -- after a release-please version bump or automated changelog update on `main`, the `sync-main-to-develop` workflow cherry-picks those commits back to `develop` as new commits with new SHAs. GitHub compares SHAs, so the original `main`-side commits register as missing on `develop` even though the file content (version number, `CHANGELOG.md`) is identical. See [docs/dev/branching-strategy.mdx](docs/dev/branching-strategy.mdx) for the full release cycle.

### Creating a Feature Branch

```bash
git checkout develop && git pull
git checkout -b feat/my-feature
# ... make changes ...
git push -u origin feat/my-feature
# Create PR targeting develop
```

### Branch Naming

Use a descriptive prefix:

| Prefix | Usage |
|--------|-------|
| `feat/` | New features |
| `fix/` | Bug fixes |
| `docs/` | Documentation |
| `refactor/` | Code restructuring |
| `ci/` | CI/CD changes |

---

## 📝 Commit Messages

We use [Conventional Commits](https://www.conventionalcommits.org/). This drives our automated CHANGELOG generation via [release-please](https://github.com/googleapis/release-please).

| Prefix | Usage | CHANGELOG |
|--------|-------|-----------|
| `feat:` | New features | Visible |
| `fix:` | Bug fixes | Visible |
| `perf:` | Performance improvements | Visible |
| `docs:` | Documentation only | Visible |
| `refactor:` | Code restructuring | Visible |
| `ci:` | CI/CD changes | Visible |
| `chore:` | Maintenance, deps | Hidden |
| `test:` | Adding/updating tests | Hidden |

Prefixes marked "Hidden" won't appear in the CHANGELOG but are still good practice.

**Examples:**
```
feat: add glucose trend chart to mobile dashboard
fix: prevent token refresh race condition on concurrent 401s
docs: add contributing guide and issue templates
refactor: extract BLE packet parser into separate module
chore(deps): update dependency next to v15.5.12
```

---

## ✅ Before You Submit

**Run these checks locally before pushing.** CI will catch failures, but it's faster to catch them yourself.

### Pre-Push Checklist

Run the checks for whichever component(s) you changed:

**Backend (API):** (requires PostgreSQL -- run `docker compose up db -d` if not already running)
```bash
cd apps/api
uv run pytest                  # Unit tests
uv run ruff check .            # Linter
uv run ruff format --check .   # Formatter
```

**Frontend (Web):**
```bash
cd apps/web
npm test       # Unit tests
npm run lint   # Linter
npm run build  # Build check (catches TypeScript errors)
```

**Mobile (Android):**
```bash
cd apps/mobile
./gradlew testDebugUnitTest  # Unit tests (phone + Wear OS)
./gradlew lintDebug          # Lint (phone + Wear OS)
./gradlew assembleDebug      # Build check
```

**AI Sidecar:**
```bash
cd sidecar
npm test  # Unit tests
```

**Docker Integration (if you changed Docker/compose files or cross-service behavior):**
```bash
docker compose up --build -d
curl localhost:8000/health       # Should return {"status": "healthy"}
curl localhost:3456/health       # Should return {"status": "ok"}
docker compose down
```

### Pre-Review with CodeRabbit CLI (Optional but Recommended)

This project uses [CodeRabbit](https://www.coderabbit.ai) for automated AI code review on every PR. You can catch the same issues locally **before** pushing by using the CodeRabbit CLI with a free account. This saves time -- you'll fix problems before the PR review instead of after.

**One-time setup:**

1. Sign up free at [app.coderabbit.ai](https://app.coderabbit.ai) via your GitHub account (no credit card required -- open-source repos get free reviews)
2. Install the CLI:
   ```bash
   curl -fsSL https://cli.coderabbit.ai/install.sh | sh
   ```
3. Authenticate:
   ```bash
   coderabbit auth login
   ```

**Before pushing, review your changes:**

```bash
# Review uncommitted changes (staged + unstaged)
coderabbit review --plain --type uncommitted

# Review your committed changes against develop
coderabbit review --plain --type committed --base develop
```

The CLI auto-detects the project's `.coderabbit.yaml` configuration, so your local reviews use the same rules (medical safety checks, security scanning, path-specific review focus) as the automated PR reviews. Your CLI instance is independent -- it doesn't connect to our CodeRabbit account -- but it uses the same analysis engine.

> **Rate limits:** Free accounts get 2 CLI reviews per hour. Open-source (public) repos get free reviews forever.

### Final Checks

- [ ] All tests pass for the component(s) you changed
- [ ] Linting passes with no new warnings
- [ ] No hardcoded secrets, API keys, tokens, or credentials in your code
- [ ] New functionality has tests
- [ ] Commit messages follow [Conventional Commits](#commit-messages) format
- [ ] Your branch is up to date with `develop`

---

## 🔀 Pull Request Process

### Creating Your PR

1. Push your feature branch to your fork
2. Open a PR **targeting `develop`** (not `main`)
3. Fill out the PR template completely
4. Link related issues using `Fixes #123` or `Relates to #123`

### What Happens Next

1. **CI runs automatically** -- all required checks must pass (see below)
2. **CodeRabbit review** -- an AI-powered code review runs automatically on every PR, checking for bugs, security issues, medical safety concerns, and code quality. It posts comments directly on your PR with findings and suggestions. This is the same engine you can run locally with the [CodeRabbit CLI](#pre-review-with-coderabbit-cli-optional-but-recommended).
3. **Code owner review** -- a maintainer will review your PR
4. **Feedback** -- you may be asked to make changes; push new commits to the same branch
5. **Merge** -- once approved and CI passes, a maintainer will squash-merge your PR

### Required CI Checks

Every PR must pass these checks before it can be merged:

| Check | What It Validates |
|-------|-------------------|
| Backend Tests | Python unit tests with PostgreSQL |
| Backend Lint | Ruff linter + formatter |
| Frontend Tests | Jest tests + Next.js build |
| Frontend Lint | ESLint |
| Sidecar Tests | Vitest for AI proxy |
| Attribution Check | No prohibited attribution lines |
| GitGuardian | Secret/credential scanning |
| Security Scan Gate | SAST + DAST security testing (see below) |

Additionally, PRs that modify `apps/mobile/**` will trigger the **Android Gate** (unit tests, lint, debug APK build).

### 🔒 Security Scan (Smart Targeting)

This is a medical platform. We take security seriously. The Security Scan Gate runs **targeted security tests based on what your PR actually changes** -- it won't waste 25 minutes scanning the API if you only changed a Kotlin file.

| If you changed... | What runs |
|-------------------|-----------|
| `apps/api/` | Semgrep Python, auth pentests, IDOR, SSRF, API fuzzer, nuclei API, ZAP API active scan |
| `apps/web/` | Semgrep TypeScript, nuclei Web, ZAP Web scan |
| `sidecar/` | Semgrep TypeScript |
| `apps/mobile/` or `plugins/` | Semgrep Kotlin |
| `docker-compose*`, `Dockerfile*` | Everything (infra changes affect all services) |
| `scripts/security/` | Everything |
| Docs, config, or other non-code files | Nothing -- security gate reports green instantly |

Mobile-only PRs skip the Docker stack entirely (~2 min instead of ~25 min). For the full breakdown of what each test suite does, see [docs/dev/security-testing.mdx](docs/dev/security-testing.mdx).

### 🚨 What If the Security Scan Finds Something?

Don't panic. Here's what happens automatically:

1. **glycemicgpt-security posts a comment** on your PR showing exactly what failed and why
2. **GitHub Issues are created** for each finding, assigned to you, with severity labels and remediation guidance
3. **You fix the issue** in your PR -- push a new commit with the fix
4. **CI runs again** -- if the finding is resolved, the issue **auto-closes** with a "resolved in PR #X" comment
5. **You're done** -- green CI, closed issues, ready for review

The whole cycle happens within your PR. You don't need to manually close issues or wait for a maintainer.

**If your code caused the finding:** Fix it. The scan won't pass until you do. Common things it catches:
- Semgrep flagging hardcoded secrets, injection patterns, or insecure crypto
- ZAP finding SQL injection, XSS, or missing security headers
- IDOR tests detecting cross-user data leaks

**If the finding is pre-existing (not your fault):** Sometimes the scan catches something in code you didn't write. You have two options:
1. **Fix it anyway** (preferred -- we appreciate it even if you didn't cause it)
2. **Add a documented exception** -- see below

**If you close your PR without fixing:** Issues linked solely to your PR are automatically cleaned up. If another PR independently detected the same finding, the issue stays open and is tracked against that PR instead.

### 🛡️ Security Exceptions

Sometimes a finding is a known limitation, an accepted risk, or a false positive. That's fine -- but you can't just ignore it. We have a formal process.

**Semgrep (code-level findings):** Add `# nosemgrep: rule-id` as a comment on the flagged line. Must be a real code comment, not inside a string.

**ZAP (runtime findings):** Add an entry to `scripts/security/zap-suppressions.json`:
```json
{
  "pluginId": "10055",
  "scan": "web",
  "reason": "Next.js requires unsafe-inline for hydration. Fix tracked in #123."
}
```

**OSV-Scanner (dependency vulnerabilities):** Add an entry to `osv-scanner.toml`:
```toml
[[IgnoredVulns]]
id = "GHSA-xxxx-yyyy-zzzz"
reason = "Not exploitable -- only affects feature X which we don't use"
```

**The rules (non-negotiable):**
- Every exception **must** include a reason. No reason = no merge.
- Reference the issue that will fix the underlying problem (e.g., `Fix tracked in #123`).
- Suppressed findings still show up in CI logs -- they're visible, just non-blocking.
- Maintainers review all exceptions quarterly. Stale ones get removed.
- If you're not sure whether something is a real finding or a false positive, ask in the PR -- that's what code review is for.

> **Note:** There is a separate [Promotion PR Template](.github/PROMOTION_PR_TEMPLATE.md) used only for develop-to-main releases. Regular contributors don't need to worry about this.

---

## 🎨 Code Style

### 🐍 Python (Backend -- `apps/api/`)

- Formatter: **Ruff** (`ruff format`)
- Linter: **Ruff** (`ruff check`)
- Type hints required for function signatures
- FastAPI patterns: use `Depends()` for dependency injection

### 🟦 TypeScript (Frontend -- `apps/web/`)

- Formatter/Linter: **ESLint** + **Prettier**
- Next.js 15 App Router conventions
- React Server Components by default; `"use client"` only when needed
- Tailwind CSS for styling; shadcn/ui for components

### 🟣 Kotlin (Mobile -- `apps/mobile/`)

- Standard Kotlin conventions
- Jetpack Compose for UI
- Hilt for dependency injection
- Room for local database
- Coroutines + Flow for async operations

### 🤖 TypeScript (Sidecar -- `sidecar/`)

- Express.js REST patterns
- Vitest for testing
- Multi-provider AI proxy (routes requests to Claude, OpenAI, Ollama, etc.)
- Follows same TypeScript conventions as frontend

---

## 🤖 AI-Assisted Development & Attribution Policy

Let's be real -- the code owners didn't write every line of this project by hand, and we don't expect you to either. **Using AI tools (Claude, Copilot, ChatGPT, Cursor, etc.) to help write code is completely fine.** We'd be hypocrites if we said otherwise.

That said, there's a difference between using AI as a tool and blindly pasting whatever it spits out. We don't want vibe-coded junk. **You are responsible for the code you submit**, regardless of who (or what) helped write it.

### What We Expect

- **Understand your code.** If you can't explain what a function does and why, don't submit it.
- **Match existing patterns.** AI tools love to invent their own conventions. Make sure AI-generated code follows _our_ code style, architecture, and naming patterns -- not whatever the model hallucinated.
- **Test it.** AI-generated code is especially prone to subtle bugs. Run the tests. Add new ones if needed.
- **Review it yourself.** Do a self-review of every AI-generated line before pushing. Treat AI output like a junior developer's first draft -- helpful starting point, needs a careful eye.

### No AI Attribution in Code

This one is non-negotiable. Our repo must be **clean of AI attribution lines**. That means:

- **No** `Co-Authored-By: Claude`, `Generated by ChatGPT`, or similar lines in commits
- **No** `// Generated by AI` or `// Copilot suggestion` comments in code
- **No** AI tool branding, promotional links, or attribution banners in PR descriptions

We have a CI check (**Attribution Check**) that scans three layers: commit message trailers, code comments in changed files, and PR descriptions. It covers all major AI tools (Claude, Copilot, ChatGPT, Cursor, Gemini, Codeium, CodeWhisperer, Tabnine, Devin, Aider, and others) and will fail your PR if any attribution is found. The git commit-msg hook (installed during [Quick Start](#quick-start-webapi----recommended-for-most-contributors)) also strips these locally before they reach the repo.

Why? Because attribution to a tool that can't be held accountable for code quality is meaningless noise. The _contributor_ is the author. Own it.

### Attribution Check Severity Levels

The CI attribution check classifies findings by severity and takes action automatically:

| Severity | What triggers it | Action taken |
|----------|-----------------|--------------|
| **CRITICAL** | Non-whitelisted bot detected as commit co-author (`[bot]` suffix or `noreply@` email) | PR **automatically closed** with comment explaining why |
| **HIGH** | AI tool name in commit trailers (e.g., `Co-Authored-By: Claude`) or AI branding in PR description | PR **blocked** -- comment with rebase/edit instructions |
| **MEDIUM** | AI attribution comments in code files (e.g., `// Generated by Claude`) | PR **blocked** -- comment with removal instructions |

When a PR is clean, the attribution check posts a positive confirmation.

### Bot Whitelist

The following bots are whitelisted and will **not** trigger attribution findings:

- **GitHub system:** `github-actions[bot]`, `dependabot[bot]`
- **GlycemicGPT project:** `glycemicgpt-ci[bot]`, `glycemicgpt-security[bot]`, `glycemicgpt-release[bot]`, `glycemicgpt-merge[bot]`, `glycemicgpt-renovate[bot]`
- **Third-party integrations:** `coderabbitai[bot]`, `gitguardian[bot]`
- **Legacy:** `homebot-0[bot]`

If your PR is flagged for a legitimate bot that isn't an AI coding tool, open an issue to request whitelisting. Include the bot name and its purpose.

### CodeRabbit -- AI Code Review

We use [CodeRabbit](https://www.coderabbit.ai) for automated AI code review on all PRs. It's configured via [`.coderabbit.yaml`](.coderabbit.yaml) with project-specific rules including medical safety checks, security scanning, and path-specific review guidelines.

CodeRabbit runs automatically when you open a PR -- no setup needed on your end. It posts a summary and inline comments with findings. If you want to catch these issues before your PR, you can install the CLI locally for free. See [Pre-Review with CodeRabbit CLI](#pre-review-with-coderabbit-cli-optional-but-recommended) in the "Before You Submit" section.

---

## 📁 Project Structure

```
GlycemicGPT/
├── apps/
│   ├── api/            # FastAPI backend (Python)
│   │   ├── src/        # Source code
│   │   └── tests/      # pytest tests
│   ├── web/            # Next.js 15 frontend (TypeScript)
│   │   ├── src/        # Source code (App Router)
│   │   └── __tests__/  # Jest tests
│   └── mobile/         # Android app (Kotlin)
│       ├── app/                 # Platform app module
│       └── wear-device/         # Wear OS device module (runs on watch)
├── plugins/            # Plugin ecosystem
│   ├── pump-driver-api/       # Plugin SDK (interfaces & domain models)
│   ├── shipped/               # Built-in plugins (compiled into APK)
│   │   └── tandem/            # Tandem plugin (t:slim X2 + Mobi)
│   └── example/               # Example runtime plugins (NOT compiled into APK)
├── sidecar/            # AI provider proxy (TypeScript/Express)
│   ├── src/            # Source code
│   └── tests/          # Vitest tests
├── docker-compose.yml  # Full stack orchestration
├── .github/
│   ├── workflows/      # CI/CD pipelines
│   ├── CODEOWNERS      # Code ownership for PR reviews
│   └── ISSUE_TEMPLATE/ # Issue templates
└── docs/               # Project documentation
```

### Plugin Development

The mobile app uses a capability-based plugin architecture. New device support (pumps, CGMs, BGMs) is added as plugin modules. See the [Plugin Architecture Guide](docs/dev/plugin-architecture.mdx) for:

- How to create a new plugin module
- Capability interfaces and mutual-exclusion rules
- Declarative UI descriptors for settings and dashboard cards
- Event bus for cross-plugin communication
- Hilt DI registration pattern
- The Tandem plugin as a reference implementation

---

## 📦 Release Channels

| Channel | Branch | Docker Tag | APK Type |
|---------|--------|------------|----------|
| **Stable** | `main` | `latest`, semver | Signed release APK |
| **Dev** | `develop` | `dev` | Debug APK (shared keystore) |

Stable releases are created automatically by release-please when code is promoted from `develop` to `main`. Your contribution will ship in the next stable release after the promotion PR is merged.

**Debug APK signing:** Dev-channel debug APKs are signed with a shared debug keystore stored as a GitHub Actions secret. This ensures that every CI-built debug APK has the same signing key, allowing the app's auto-update mechanism to install new dev builds over previous ones without "package conflicts" errors. Local `./gradlew assembleDebug` builds use your machine's default `~/.android/debug.keystore` and will have a different signature -- you'll need to uninstall the CI-built APK before installing a local build (and vice versa).

<details>
<summary>Keystore rotation (maintainers only)</summary>

If the debug keystore needs to be regenerated (e.g., secret deleted, key compromised), use these exact parameters to keep the Gradle signing config (alias name, secret names) consistent. A new keystore produces new key material, so existing dev-channel installs will require an uninstall/reinstall.

```bash
# Prompt for password (never hits shell history or process list)
read -rsp "Keystore password: " KSPASS && echo

keytool -genkeypair \
  -alias debug-key \
  -keyalg RSA -keysize 2048 \
  -validity 36500 \
  -keystore debug-keystore.jks \
  -storepass:env KSPASS \
  -keypass:env KSPASS \
  -dname "CN=GlycemicGPT Debug, OU=Development, O=GlycemicGPT, L=Austin, ST=Texas, C=US"

# Set GitHub secrets (gh prompts for values securely):
base64 debug-keystore.jks | tr -d '\n' | gh secret set DEBUG_KEYSTORE_BASE64
gh secret set DEBUG_KEYSTORE_PASSWORD    # enter password at prompt
gh secret set DEBUG_KEY_ALIAS            # enter: debug-key
gh secret set DEBUG_KEY_PASSWORD         # enter password at prompt

# Remove the local keystore file -- do not commit it
rm debug-keystore.jks
```

The alias must remain `debug-key`.
</details>

---

## 📜 License

GlycemicGPT is licensed under the [GNU General Public License v3.0](LICENSE). By contributing, you agree that your contributions will be licensed under the same license.

---

## 💬 Questions?

- 🙏 **General questions & help** -- Post in [Q&A Discussions](https://github.com/GlycemicGPT/GlycemicGPT/discussions/categories/q-a)
- 💡 **Feature ideas & brainstorming** -- Post in [Ideas Discussions](https://github.com/GlycemicGPT/GlycemicGPT/discussions/categories/ideas)
- 🐛 **Bug reports** -- Open an [Issue](https://github.com/GlycemicGPT/GlycemicGPT/issues/new/choose) using the appropriate template
- 🙌 **Show off your setup** -- Post in [Show and Tell](https://github.com/GlycemicGPT/GlycemicGPT/discussions/categories/show-and-tell)

Please **do not** open Issues for general questions -- use Discussions instead. Issues are for actionable bugs and feature requests.

We try to respond to PRs, issues, and discussions within a few days. If your PR sits without feedback for more than a week, feel free to leave a comment pinging the maintainers.
