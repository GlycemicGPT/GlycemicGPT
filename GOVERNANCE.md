# Project Governance

This document describes the roles, responsibilities, and decision-making process for GlycemicGPT. It's designed to be transparent about how the project is run and how contributors can grow their involvement.

## Medical Context

GlycemicGPT is a diabetes management platform. Code changes can affect how glucose data is displayed, how insulin calculations are suggested, and how safety alerts are delivered. This context shapes our governance: **every role carries responsibility for patient safety**, not just code quality.

## Roles

### Contributor

**Who:** Anyone who participates in the project. No special access required.

**What you can do:**
- Open issues and feature requests
- Submit pull requests (targeting `develop`)
- Participate in discussions
- Review code (comments welcome from anyone)
- Report security vulnerabilities

**How to become one:** Just show up. Open a PR, file an issue, join a discussion.

### Committer

**Who:** Trusted contributors with Write access to the repository.

**What you can do (in addition to Contributor):**
- Push to feature branches (not `develop` or `main` directly)
- Approve pull requests on `develop`
- Triage issues (assign labels, milestones, assignees)
- Be assigned as a code owner for specific components

**What you cannot do:**
- Merge to `main` (promotion PRs require maintainer approval)
- Change governance files (CODEOWNERS, GOVERNANCE.md, CONTRIBUTING.md)
- Modify security infrastructure (security scan workflows, suppression configs)
- Publish releases

**How to become one:**
1. Contribute consistently over **3+ months** (no specific PR count -- quality matters more than quantity)
2. Demonstrate understanding of [medical safety requirements](CONTRIBUTING.md#-safety-first----please-read) in your contributions
3. Follow project conventions without repeated correction
4. Be nominated by a maintainer
5. Maintainer grants Write access via GitHub collaborator settings

There is no formal application process. Maintainers watch for contributors who demonstrate reliability, good judgment, and safety awareness. If you're interested, just keep contributing -- it will be noticed.

### Maintainer

**Who:** Project stewards with Maintain or Admin access.

**What you can do (in addition to Committer):**
- Approve and merge promotion PRs (`develop` to `main`)
- Publish releases
- Modify governance files and security infrastructure
- Grant Committer access to contributors
- Make architectural and safety decisions
- Manage branch protection rules

**Current maintainers:**
- [@jlengelbrecht](https://github.com/jlengelbrecht) (project lead)

**How to become one:**
1. Active committer for **6+ months**
2. Has reviewed PRs and mentored other contributors
3. Understands the full stack (or deep expertise in one area + awareness of others)
4. Demonstrated sound judgment on safety-critical decisions
5. Invited by existing maintainers

Maintainer status is an invitation, not an application. It reflects sustained trust built over time.

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

This is a standard BDFL (Benevolent Dictator for Life) model, common in projects with a single founder. It will evolve if the maintainer team grows.

## Branch Protection

The repository enforces these protections:

### `main` (stable releases)
- All changes must go through a pull request
- 1 required approving review from a code owner (maintainer)
- Stale reviews dismissed on push (must re-approve after changes)
- Rebase merge only (preserves commit history for changelog generation)
- No force push, no deletion
- Bypass: admin role + homebot.0 (for automated release-please version bumps only)

### `develop` (integration branch)
- All changes must go through a pull request
- 1 required approving review from a code owner
- Squash merge only
- 10 required status checks (CI, security scan, linting, etc.)
- No force push, no deletion
- Bypass: admin role + homebot.0 (for automated dependency updates)

### Why maintainer approval is required on `main`

The promotion from `develop` to `main` is a release decision. It means:
- The code has been tested on `develop`
- Dev Docker images and debug APKs have been verified
- No known regressions exist
- The maintainer takes responsibility for what ships

This is not bureaucracy -- it's the checkpoint between "code that works" and "code that's released to people managing their diabetes."

## Code Ownership

Code owners are defined in [`.github/CODEOWNERS`](.github/CODEOWNERS). When a PR touches files owned by a specific person, GitHub automatically requests their review.

Currently, the project maintainer owns all files. As committers are granted component ownership, the CODEOWNERS file will be updated to reflect shared responsibility:

```
# Example of future component ownership:
/apps/api/ @jlengelbrecht @backend-committer
/apps/mobile/ @jlengelbrecht @mobile-committer
```

The maintainer always retains ownership of governance files, security infrastructure, and release configuration.

## Security

Security findings are handled automatically by CI (see [docs/security-testing.md](docs/security-testing.md)). The governance implications:

- **Suppression decisions** (accepting a known risk) require maintainer approval
- **Security infrastructure changes** (scan workflows, evaluator scripts) require maintainer review
- **Vulnerability reports** from external researchers should use the [Security Finding](https://github.com/GlycemicGPT/GlycemicGPT/issues/new?template=security-finding.yml) issue template

## Changes to This Document

This governance document can only be modified by maintainers. Changes require a pull request reviewed by a code owner (enforced via CODEOWNERS). The project lead has final say on governance changes.
