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
- 🔒 Safety limits (glucose range, max bolus, max basal) are enforced by the platform via `SafetyLimits` (backend-synced, user-configurable). Plugins must respect these as read-only constraints -- see the [Plugin Architecture Guide](docs/plugin-architecture.md).
- 🚫 **No unsupervised device control** -- see below

### Device Control Plugins

GlycemicGPT is a **monitoring-only platform** in all pre-built releases. It reads data from pumps and CGMs but does not send commands to them. No pre-built APK distributed via GitHub Releases will ever include a plugin capable of insulin delivery.

That said, we recognize that some pumps -- like the Tandem Mobi and Omnipod -- have no physical screen and **require** an app to deliver insulin. A monitoring-only platform cannot fully support these devices. We welcome contributions that help the community use GlycemicGPT with screenless pumps, but there is a hard line between what we ship and what users build for themselves.

**How we handle this -- two contribution tiers:**

| Tier | What | Shipped in releases? | Example |
|------|------|---------------------|---------|
| **Monitoring plugins** | Read data from devices (glucose, pump status, history) | Yes -- compiled by CI, included in APKs | Tandem reader, Dexcom G7 |
| **Reference implementations** | Source code demonstrating pump control patterns | **Never** -- not compiled, not in any build artifact | Tandem Mobi delivery example |

**Monitoring plugins** follow the standard contribution flow: submit a PR with a new Gradle module, it gets reviewed, merged, and shipped in the next release.

**Pump control reference implementations** are different. They live in the repo as source code (under `plugins/reference/`) but are **not** Gradle modules, **not** in `settings.gradle.kts`, and **never** compiled by our CI/CD pipeline. They exist purely as working examples that demonstrate how to build a pump control plugin against the plugin SDK (`:pump-driver-api`).

**If a user wants to use a pump control plugin, they must build it themselves:**

1. Study the reference implementation source code in the repo
2. Create their own project, depending on the published plugin SDK
3. Compile the plugin in their own development environment (Android Studio on their machine)
4. Load the resulting plugin into GlycemicGPT via the app's custom plugin loader

By building and loading a pump control plugin, the user accepts full responsibility as the "manufacturer" of their personal build. This is the same model used by AndroidAPS, Loop, and other open-source diabetes projects. See [MEDICAL-DISCLAIMER.md](MEDICAL-DISCLAIMER.md) for the complete legal framework.

**The platform protects users regardless.** Whether a plugin is shipped or user-built, the platform enforces safety limits that cannot be bypassed:

- Maximum single bolus cap and maximum daily insulin cap
- Glucose range validation (values outside bounds are rejected)
- Maximum basal rate limits
- Explicit user confirmation required for every delivery command
- Biometric authentication (fingerprint or face ID) before any insulin action

AI-powered features (analysis, suggestions, pattern recognition) can integrate with pump control plugins -- the platform's safety layer applies equally to AI-informed and manual workflows. The guardrails are in the platform, not in blanket prohibitions.

**Non-negotiable rules for pump control reference implementations:**

- Must use the platform's `SafetyLimits` -- hardcoded bypass of safety limits will not be merged
- Must require explicit user confirmation for every delivery command
- Must never be wired into the app's build system (no Gradle module, no CI compilation)
- Must include clear documentation that the user assumes manufacturer responsibility

PRs that violate these safety principles will not be merged regardless of code quality.

---

## 📑 Table of Contents

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

## 💡 Ways to Contribute

There are many ways to help, not all of them involve writing code:

- 🐛 **Report bugs** -- Use the [Bug Report](https://github.com/jlengelbrecht/GlycemicGPT/issues/new?template=bug_report.yml) or [Mobile App Issue](https://github.com/jlengelbrecht/GlycemicGPT/issues/new?template=mobile_report.yml) template
- ✨ **Request features** -- Use the [Feature Request](https://github.com/jlengelbrecht/GlycemicGPT/issues/new?template=feature_request.yml) template
- 📝 **Improve documentation** -- Typos, unclear instructions, missing guides
- 🧪 **Write tests** -- More coverage is always welcome
- 🔍 **Review PRs** -- Fresh eyes catch things automated checks can't
- 💬 **Answer questions** -- Help others in [Discussions](https://github.com/jlengelbrecht/GlycemicGPT/discussions)

Before opening an issue, please search [existing issues](https://github.com/jlengelbrecht/GlycemicGPT/issues?q=is%3Aissue) to avoid duplicates. For general questions and support, use [Discussions](https://github.com/jlengelbrecht/GlycemicGPT/discussions/categories/q-a) instead of creating an issue.

---

## 🔍 Finding Something to Work On

Not sure where to start? Browse [open issues](https://github.com/jlengelbrecht/GlycemicGPT/issues) and look for these labels:

- 🏷️ **`good first issue`** -- Small, well-scoped tasks ideal for new contributors
- 🏷️ **`help wanted`** -- We'd love community help on these
- 🏷️ **`bug`** -- Known bugs waiting for a fix

> **Tip:** Not every label will have open issues at all times. If none are tagged yet, browse the full [issue list](https://github.com/jlengelbrecht/GlycemicGPT/issues) or check the [Ideas discussion board](https://github.com/jlengelbrecht/GlycemicGPT/discussions/categories/ideas) for inspiration.

If you'd like to work on something, comment on the issue to let others know. For larger changes, please open an issue or start a [discussion](https://github.com/jlengelbrecht/GlycemicGPT/discussions) first to discuss the approach before investing time in a PR.

---

## 🛠️ Development Setup

### Prerequisites

You only need the tools for the component(s) you're working on:

| Component | You Need |
|-----------|----------|
| 🌐 Web UI | Docker + Docker Compose |
| 🐍 Backend API | Docker + Docker Compose (or Python 3.12+ with [UV](https://docs.astral.sh/uv/)) |
| 🤖 AI Sidecar | Docker + Docker Compose (or Node.js 20+) |
| 📱 Mobile App | JDK 17, Android SDK (API 34) |
| ⌚ Wear OS | JDK 17, Android SDK (API 34), Wear OS system image |
| 📝 Docs only | Just a text editor! |

### 🚀 Quick Start (Web/API -- recommended for most contributors)

The fastest way to get a working dev environment:

```bash
# 1. Fork and clone
git clone https://github.com/<your-username>/GlycemicGPT.git
cd GlycemicGPT

# 2. Add upstream remote
git remote add upstream https://github.com/jlengelbrecht/GlycemicGPT.git

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
feature branch --> squash merge --> develop --> rebase merge --> main
                                      |                           |
                                  dev builds                  stable releases
                                  debug APKs                  signed APKs
                                  Docker :dev                 Docker :latest
```

### Rules

- **`develop`** is the integration branch. **All contributor PRs target `develop`.**
- **`main`** is the stable release branch. Do **not** target PRs to `main`.
- Feature branches are created from `develop` and squash-merged back.

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
| Frontend Tests | Jest tests + Next.js build (`npm test` and `npm run build`) |
| Frontend Lint | ESLint |
| Sidecar Tests | Vitest for AI proxy |
| Attribution Check | No prohibited attribution lines |
| GitGuardian Security Checks | Secret/credential scanning |

Additionally, PRs that modify `apps/mobile/**` will run Android Build & Test (unit tests, lint, debug APK build).

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

We have a CI check (**Attribution Check**) that automatically catches common AI attribution patterns and will fail your PR if any are found. The git commit-msg hook (installed during [Quick Start](#quick-start-webapi----recommended-for-most-contributors)) also strips these locally before they reach the repo.

Why? Because attribution to a tool that can't be held accountable for code quality is meaningless noise. The _contributor_ is the author. Own it.

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
│       └── wear/               # Wear OS module
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

The mobile app uses a capability-based plugin architecture. New device support (pumps, CGMs, BGMs) is added as plugin modules. See the [Plugin Architecture Guide](docs/plugin-architecture.md) for:

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

- 🙏 **General questions & help** -- Post in [Q&A Discussions](https://github.com/jlengelbrecht/GlycemicGPT/discussions/categories/q-a)
- 💡 **Feature ideas & brainstorming** -- Post in [Ideas Discussions](https://github.com/jlengelbrecht/GlycemicGPT/discussions/categories/ideas)
- 🐛 **Bug reports** -- Open an [Issue](https://github.com/jlengelbrecht/GlycemicGPT/issues/new/choose) using the appropriate template
- 🙌 **Show off your setup** -- Post in [Show and Tell](https://github.com/jlengelbrecht/GlycemicGPT/discussions/categories/show-and-tell)

Please **do not** open Issues for general questions -- use Discussions instead. Issues are for actionable bugs and feature requests.

We try to respond to PRs, issues, and discussions within a few days. If your PR sits without feedback for more than a week, feel free to leave a comment pinging the maintainers.
