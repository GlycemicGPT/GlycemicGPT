# Project Governance

This document describes the roles, responsibilities, decision-making process, and compensation model for GlycemicGPT. It's designed to be transparent about how the project is run and how contributors can grow their involvement.

## Medical Context

GlycemicGPT is a diabetes management platform. Code changes can affect how glucose data is displayed, how insulin calculations are suggested, and how safety alerts are delivered. This context shapes our governance: **every role carries responsibility for patient safety**, not just code quality.

## Roles

GlycemicGPT has four roles with increasing levels of access and responsibility. Each role maps to a specific GitHub permission level enforced through org teams and CODEOWNERS.

### Permissions

| Permission | Contributor | Committer | Maintainer | Project Lead |
|------------|:-----------:|:---------:|:----------:|:------------:|
| Open issues and PRs | Yes | Yes | Yes | Yes |
| Participate in discussions | Yes | Yes | Yes | Yes |
| Review code (comments) | Yes | Yes | Yes | Yes |
| Report security vulnerabilities | Yes | Yes | Yes | Yes |
| Push to feature branches | - | Yes | Yes | Yes |
| Approve PRs on develop | - | Yes | Yes | Yes |
| Triage issues (labels, milestones) | - | Yes | Yes | Yes |
| Merge PRs to develop | - | - | Yes | Yes |
| Approve promotion PRs (main) | - | - | Yes | Yes |
| Merge promotion PRs (main) | - | - | - | Yes |
| Publish releases | - | - | Yes | Yes |
| Change governance files | - | - | - | Yes |
| Change security infrastructure | - | - | - | Yes |
| Change branch protection | - | - | - | Yes |
| Manage org settings and teams | - | - | - | Yes |
| Nominate committers | - | - | Yes | Yes |
| Approve committer nominations | - | - | - | Yes |
| Nominate maintainers | - | - | Yes | Yes |
| Approve maintainer nominations | - | - | - | Yes |

### Contributor

**Who:** Anyone who participates in the project. No special access required.

**GitHub access:** None needed -- fork and PR workflow.

**How to become one:** Just show up. Open a PR, file an issue, join a discussion.

### Committer

**Who:** Trusted contributors with Write access to the repository.

**GitHub team:** [`@GlycemicGPT/committers`](https://github.com/orgs/GlycemicGPT/teams/committers) (Write permission)

**What you cannot do:**
- Merge to `develop` or `main` (branch protection requires maintainer approval)
- Change governance files (CODEOWNERS, GOVERNANCE.md, CONTRIBUTING.md, LICENSE)
- Modify security infrastructure (security scan workflows, suppression configs)
- Publish releases
- Modify org settings, teams, or branch protection

### Maintainer

**Who:** Project stewards with Maintain access. Responsible for the day-to-day health of the project.

**GitHub team:** [`@GlycemicGPT/maintainers`](https://github.com/orgs/GlycemicGPT/teams/maintainers) (Maintain permission)

**What you cannot do:**
- Merge promotion PRs to `main` (project lead only)
- Change governance files (project lead only via CODEOWNERS)
- Change security infrastructure (project lead only via CODEOWNERS)
- Change branch protection rules or org settings
- Promote or demote maintainers (project lead only)

**Current maintainers:**
- [@jlengelbrecht](https://github.com/jlengelbrecht) (project lead)

### Project Lead

**Who:** The founder and final decision-maker. Org Owner on GitHub with full admin access.

**Current project lead:** [@jlengelbrecht](https://github.com/jlengelbrecht)

This is a standard BDFL (Benevolent Dictator for Life) model, common in projects with a single founder. The project lead retains authority over governance, security, branch protection, org settings, and maintainer promotions. This ensures the project's medical safety standards cannot be changed without the founder's explicit approval.

## Becoming a Committer

1. Contribute consistently over **3+ months** (no specific PR count -- quality matters more than quantity)
2. Demonstrate understanding of [medical safety requirements](CONTRIBUTING.md#-safety-first----please-read) in your contributions
3. Follow project conventions without repeated correction
4. Any maintainer nominates you in a [Discussion](https://github.com/GlycemicGPT/GlycemicGPT/discussions) thread
5. **1-week consensus period** -- the nomination passes if no existing maintainer objects
6. The project lead retains veto power over any nomination
7. On approval: added to `@GlycemicGPT/committers` team, org seat funded from project fund

There is no formal application process. Maintainers watch for contributors who demonstrate reliability, good judgment, and safety awareness. If you're interested, just keep contributing -- it will be noticed.

## Becoming a Maintainer

1. Active committer for **6+ months**
2. Has reviewed PRs and mentored other contributors
3. Understands the full stack (or deep expertise in one area + awareness of others)
4. Demonstrated sound judgment on safety-critical decisions
5. Any maintainer nominates in a Discussion thread
6. 1-week consensus period among existing maintainers
7. **Project lead must explicitly approve** (not just absence of objections)
8. On approval: moved from `@GlycemicGPT/committers` to `@GlycemicGPT/maintainers` team, eligible for stipend

Maintainer status reflects sustained trust built over time. For a medical platform, this trust includes demonstrated understanding of patient safety implications, not just technical skill.

## Inactivity

- **6 months** with no contributions (PRs, reviews, issues, discussions) = moved to **emeritus** status
- Emeritus members are removed from their GitHub team but acknowledged in this document
- Returning from emeritus: request reinstatement in a Discussion. If the member left in good standing, no full re-nomination is needed -- a maintainer confirms and restores team access

### Emeritus

*No emeritus members yet.*

## Decision-Making

### Day-to-day decisions

Maintainers make routine decisions: merging PRs, triaging issues, choosing implementation approaches. These don't need formal process.

### Architecture and safety decisions

Major changes that affect the platform's architecture or safety properties should be discussed before implementation:

1. Open a [Discussion](https://github.com/GlycemicGPT/GlycemicGPT/discussions) in the Ideas category describing the proposal
2. Tag relevant maintainers and committers
3. Allow at least 7 days for feedback on safety-critical proposals
4. Document the decision in the PR that implements it

Examples of what qualifies:
- New pump or CGM device support
- Changes to insulin calculation logic or safety limits
- New AI provider integrations that affect medical advice
- Authentication or authorization model changes
- Plugin architecture changes that affect the safety boundary

### Disputes

If contributors disagree on an approach:
1. Discuss in the PR or a linked Discussion
2. If no consensus, maintainers decide
3. If maintainers disagree, the project lead ([@jlengelbrecht](https://github.com/jlengelbrecht)) has final say

## Compensation

### How funding works

GlycemicGPT is funded through a single channel: [Open Collective](https://opencollective.com/glycemicgpt), fiscally hosted by Open Source Collective. All project income, expenses, and balances are public by default.

Routing every dollar -- including any compensation paid to the project lead, maintainers, or committers -- through one transparent ledger is a deliberate choice in support of full financial transparency. The project does not solicit funds through any other channel.

<p align="center">
  <a href="https://opencollective.com/glycemicgpt"><img src="https://opencollective.com/glycemicgpt/contribute/button@2x.png?color=blue" alt="Contribute to GlycemicGPT on Open Collective" width="300"></a>
</p>

### What the fund covers

1. **Infrastructure**: hosting, domain (glycemicgpt.org), CI costs, signing certificates
2. **Org seats**: per-seat cost for each committer/maintainer on the GitHub Teams plan
3. **Maintainer stipends**: when the fund supports it, active maintainers may receive monthly stipends
4. **Bounties**: specific issues may carry bounties funded from Open Collective (future)

### Who gets paid

| Role | Org seat | Stipend eligible | How |
|------|:--------:|:----------------:|-----|
| **Project lead** | N/A (owner) | Yes | Open Collective stipend |
| **Maintainer** | Paid from fund | Yes | Open Collective stipend |
| **Committer** | Paid from fund | No | Volunteer role |
| **Contributor** | N/A | No | Bounties on specific issues (future) |

The project lead is stipend-eligible from the Open Collective fund on the same basis as any other maintainer. Routing all compensation -- regardless of role -- through Open Collective keeps every payout on the public ledger.

Maintainer stipend amounts are decided by the project lead based on fund balance and contribution level. Stipend decisions are documented in the maintainers Discussion thread.

### Transparency

- All Open Collective income and expenses are public
- Stipend decisions are documented in Discussions
- Annual financial summary posted to Discussions
- Open Source Collective deducts a 10% host fee from each donation; the remaining 90% goes to the project fund. This fee is documented on OSC's [hosted collectives page](https://opencollective.com/opensource) and applied automatically by the platform.

### In-kind support

GlycemicGPT also receives in-kind support from open-source-friendly vendors (donated software, services, or infrastructure). These relationships are governed by [SPONSORS.md](SPONSORS.md), which is the canonical record of all sponsor and fiscal-host relationships and includes a disclosure of how sponsor influence is bounded.

#### 1Password for Open Source (team password management)

- **Scope:** the project's 1Password Teams account is used for shared project credentials only -- the operational accounts required to run the project, the dev-stack test account, and future CI/deploy secrets when applicable. Personal credentials, end-user accounts, and non-project items do not belong here.
- **Out of scope:** medical patient data of any kind, end-user passwords, personally identifying information about contributors beyond what's needed to grant access.
- **Who gets access:**
  - **Project lead:** full access, vault admin.
  - **Maintainers** (per the [Roles](#roles) hierarchy): access to operational vaults relevant to their responsibilities. Scoped per need; no blanket access.
  - **Committers:** access only on request, scoped to specific items needed for the work they're doing. Default is no access.
  - **External contributors:** time-bounded access to a specifically scoped vault (e.g., a "Contributor Dev Stack" vault) for credentials needed to spin up the local environment, when the alternative would be DM'ing plaintext credentials. Revoked when their PR merges or work concludes.
- **Granting access:** requests go to the project lead. Access decisions are logged in a Discussions thread (audit trail) and respect the per-need scoping above.
- **Loss of access:** triggered by role change (committer → emeritus, maintainer stepping down) or completion of bounded work (external contributor). The project lead is responsible for the off-boarding sweep.
- **Why this matters:** before the 1Password account, project credentials were shared over Discord DMs and inline in dev docs. The 1Password account exists to fix that. The point is **shared, audit-able, revocable** credential handling -- not a single "team admin password" that everyone gets a copy of.

A separate operational adoption sequence (vault setup, dev-stack credential migration, CI integration) is tracked by the project lead outside this governance doc; this section only sets the policy.

## Branch Protection

The repository enforces these protections via org-level rulesets that apply to all repositories:

### `main` (stable releases)
- All changes must go through a pull request
- 1 required approving review from a code owner
- Stale reviews dismissed on push (must re-approve after changes)
- Merge commit for promotions, squash for hotfixes (merge commit maintains branch ancestry)
- No force push, no deletion
- Bypass: org admins + glycemicgpt-merge (for release-please version bumps and changelog PRs)

### `develop` (integration branch)
- All changes must go through a pull request
- 1 required approving review from a code owner
- Squash merge only
- 10 required status checks (CI, security scan, linting, etc.)
- No force push, no deletion
- Bypass: org admins + glycemicgpt-merge (for automated sync PRs). glycemicgpt-renovate bypass pending manual ruleset update.

### Why project lead approval is required on `main`

The promotion from `develop` to `main` is a release decision. It means:
- The code has been tested on `develop`
- Dev Docker images and debug APKs have been verified
- No known regressions exist
- The project lead takes responsibility for what ships

This is not bureaucracy -- it's the checkpoint between "code that works" and "code that's released to people managing their diabetes."

## Code Ownership

Code owners are defined in [`.github/CODEOWNERS`](.github/CODEOWNERS). When a PR touches files owned by a specific team or person, GitHub automatically requests their review.

The `@GlycemicGPT/maintainers` team owns all files by default. Governance files, security infrastructure, and release configuration list the project lead individually alongside the maintainers team. The project lead's individual listing ensures they are always explicitly requested as a reviewer on external PRs. The team co-listing ensures review is still requested when the project lead authors the PR -- GitHub skips review requests for sole code owners who are also the PR author, so the team serves as a fallback to maintain audit trail.

> **Note:** CODEOWNERS controls who is *requested* for review, not who *must* approve. The requirement that the project lead personally reviews governance, security, and release changes is enforced by process (this document), not by GitHub's code owner mechanism. Any code owner approval satisfies the branch protection check.

As the project grows, component-specific committer teams will be added:

```
# Future component ownership example:
/apps/api/ @GlycemicGPT/maintainers @GlycemicGPT/backend-committers
/apps/mobile/ @GlycemicGPT/maintainers @GlycemicGPT/mobile-committers
```

## Automation

All automated actions use named GlycemicGPT bot identities where possible. Each bot has least-privilege permissions scoped to its function. Bot credentials are stored as org-level secrets.

| Bot | Purpose | What it does |
|-----|---------|-------------|
| **glycemicgpt-security** | Security scanning | Posts security scan PR comments, creates/closes/reopens finding issues, throttled "still detected" comments |
| **glycemicgpt-release** | Release management | Creates release-please version bump PRs, creates changelog PRs, uploads signed release APKs |
| **glycemicgpt-merge** | Automated merging | Approves and merges automated PRs (release-please, changelog). Only bot with admin bypass on main. |
| **glycemicgpt-renovate** | Dependency management | Creates and merges dependency update PRs on develop. Automerges patches/minors after CI passes. |
| **glycemicgpt-ci** | CI/CD operations | Creates dev pre-releases, labels PRs based on file changes and conventions |

### Container image publishing

Container images pushed to GHCR (`ghcr.io/glycemicgpt/*`) use the built-in `GITHUB_TOKEN` instead of a custom bot token. This is a [GitHub platform limitation](https://github.com/orgs/community/discussions/26920): GHCR does not accept GitHub App installation tokens for read or write operations. The `packages: write` permission on custom apps is not honored by GHCR's authentication layer. This limitation has been open since 2020 with no published timeline for resolution. `GITHUB_TOKEN` is the only supported authentication method for GHCR within GitHub Actions.

## Security

Security findings are handled automatically by CI (see [docs/dev/security-testing.md](docs/dev/security-testing.md)). The governance implications:

- **Suppression decisions** (accepting a known risk) require project lead approval
- **Security infrastructure changes** (scan workflows, evaluator scripts) require project lead review (enforced via CODEOWNERS)
- **Vulnerability reports** from external researchers should follow the [Security Policy](https://github.com/GlycemicGPT/.github/blob/main/SECURITY.md)
- **Platform-level (GitHub-native) alerts** -- Dependabot alerts and Secret Scanning surface findings in the repo's Security tab. The project lead reviews open alerts weekly; real findings convert to tracked issues and follow the same triage flow as CI findings. See [CONTRIBUTING.md § Platform-level security scanning](CONTRIBUTING.md#platform-level-security-scanning-github-native) for the contributor-facing view.

## Changes to This Document

This governance document can only be modified by the project lead. Changes require a pull request reviewed by the project lead (enforced via CODEOWNERS). This ensures governance cannot be changed without the founder's explicit approval.
