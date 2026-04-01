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

GlycemicGPT is funded through [GitHub Sponsors](https://github.com/sponsors/GlycemicGPT) and [Open Collective](https://opencollective.com/glycemicgpt).

- **GitHub Sponsors**: Direct sponsorship of the project lead and the project
- **Open Collective**: Transparent project fund for shared expenses

All Open Collective transactions are public by default.

### What the fund covers

1. **Infrastructure**: hosting, domain (glycemicgpt.org), CI costs, signing certificates
2. **Org seats**: $4/month per committer/maintainer seat on the GitHub Teams plan
3. **Maintainer stipends**: when the fund supports it, active maintainers may receive monthly stipends
4. **Bounties**: specific issues may carry bounties funded from Open Collective (future)

### Who gets paid

| Role | Org seat | Stipend eligible | How |
|------|:--------:|:----------------:|-----|
| **Project lead** | N/A (owner) | Yes | GitHub Sponsors (personal) |
| **Maintainer** | Paid from fund | Yes | Open Collective stipend |
| **Committer** | Paid from fund | No | Volunteer role |
| **Contributor** | N/A | No | Bounties on specific issues (future) |

The project lead receives personal sponsorship via GitHub Sponsors. This is standard practice for open source maintainers and is documented here transparently.

Maintainer stipend amounts are decided by the project lead based on fund balance and contribution level. Stipend decisions are documented in the maintainers Discussion thread.

### Transparency

- All Open Collective income and expenses are public
- Stipend decisions are documented in Discussions
- Annual financial summary posted to Discussions

## Branch Protection

The repository enforces these protections via org-level rulesets that apply to all repositories:

### `main` (stable releases)
- All changes must go through a pull request
- 1 required approving review from a code owner
- Stale reviews dismissed on push (must re-approve after changes)
- Rebase merge only (preserves commit history for changelog generation)
- No force push, no deletion
- Bypass: org admins + glycemicgpt-merge (for release-please version bumps and changelog PRs)

### `develop` (integration branch)
- All changes must go through a pull request
- 1 required approving review from a code owner
- Squash merge only
- 10 required status checks (CI, security scan, linting, etc.)
- No force push, no deletion
- Bypass: org admins + glycemicgpt-renovate (for automated dependency updates)

### Why project lead approval is required on `main`

The promotion from `develop` to `main` is a release decision. It means:
- The code has been tested on `develop`
- Dev Docker images and debug APKs have been verified
- No known regressions exist
- The project lead takes responsibility for what ships

This is not bureaucracy -- it's the checkpoint between "code that works" and "code that's released to people managing their diabetes."

## Code Ownership

Code owners are defined in [`.github/CODEOWNERS`](.github/CODEOWNERS). When a PR touches files owned by a specific team or person, GitHub automatically requests their review.

The `@GlycemicGPT/maintainers` team owns all files by default. Governance files, security infrastructure, and release configuration are owned by the project lead individually -- this ensures these critical files cannot be changed without the project lead's explicit approval, even if the maintainers team grows.

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

Security findings are handled automatically by CI (see [docs/security-testing.md](docs/security-testing.md)). The governance implications:

- **Suppression decisions** (accepting a known risk) require project lead approval
- **Security infrastructure changes** (scan workflows, evaluator scripts) require project lead review (enforced via CODEOWNERS)
- **Vulnerability reports** from external researchers should follow the [Security Policy](https://github.com/GlycemicGPT/.github/blob/main/SECURITY.md)

## Changes to This Document

This governance document can only be modified by the project lead. Changes require a pull request reviewed by the project lead (enforced via CODEOWNERS). This ensures governance cannot be changed without the founder's explicit approval.
