# Branching Strategy

## Branch Model

| Branch | Purpose | Protected | Default |
|--------|---------|-----------|---------|
| `main` | Stable releases | Yes | Yes |
| `develop` | Integration / dev testing | Yes | No |

## Full Release Cycle

```
1. Create feature branch from develop
2. Open PR targeting develop, CI runs
3. Squash-merge to develop
4. (Automated) Dev Docker images tagged "dev", debug APK published as dev-latest pre-release
5. Repeat 1-4 for more features, test dev builds
6. When ready for stable release: create promotion PR (develop -> main)
7. CI runs on the promotion PR
8. Merge with "Rebase and merge" (individual commits land on main)
9. (Automated) release-please creates version bump PR on main
10. (Automated) glycemicgpt-merge auto-merges the version bump PR
11. (Automated) GitHub Release created, signed APK uploaded, Docker images tagged with version + "latest"
12. Sync develop: rebase onto main to pick up version bump
```

## Feature Branch Workflow

1. Create a feature branch from `develop`:
   ```bash
   git checkout develop && git pull
   git checkout -b feat/my-feature
   ```
2. Push and create a PR targeting `develop`.
3. CI runs on the PR. **Squash-merge** when approved.

## Promotion (develop -> main)

A "promotion PR" is a regular pull request that moves tested code from develop to main:

```bash
gh pr create --base main --head develop \
  --title "chore: promote develop to main" \
  --body-file .github/PROMOTION_PR_TEMPLATE.md
```

**Use "Squash and merge"** for all promotion PRs. This produces a single clean commit on main per promotion. Our label-based changelog (`changelog-pr.yml`) generates granular entries from PR titles, labels, and contributor credits regardless -- it reads from the PRs merged to develop, not from commits on main.

After the promotion PR merges:
- **changelog-pr.yml** detects the promotion and generates a changelog from PR labels
- glycemicgpt-merge auto-merges the changelog PR
- If release-please detects releasable commits, it creates a version bump PR
- The `sync-main-to-develop` workflow cherry-picks any version changes back to develop
- A GitHub Release is created with signed APKs and versioned Docker images

### Post-merge: automated version sync

After a promotion merge, release-please creates a version bump commit on main (e.g., `chore: release 0.1.101`). The `sync-main-to-develop` workflow automatically cherry-picks this commit back to develop via PR and auto-merges it. No manual intervention required.

The sync workflow:
1. Detects version bump or changelog commits on main
2. Cherry-picks them onto a branch from develop
3. Creates a PR and auto-merges with glycemicgpt-merge[bot]
4. Develop stays in sync with main's version numbers

Verify the sync completed in the [Actions tab](../../actions/workflows/sync-main-to-develop.yml). If the sync PR has unresolved conflicts (rare), resolve manually.

> **Note:** Develop has deletion protection in its branch ruleset, so it is NOT auto-deleted after promotion merges despite the repo-level "auto-delete head branches" setting.

## Release Channels

### Stable (main)

- **Docker images:** Tagged `latest` and semver (`1.2.3`, `1.2`)
- **Mobile APKs:** Signed release APKs uploaded to GitHub Releases
- **Update check:** Release builds fetch `/releases/latest`

### Dev (develop)

- **Docker images:** Tagged `dev` (overwritten on each push to develop)
- **Mobile APKs:** Debug APKs uploaded to a rolling `dev-latest` pre-release
- **Update check:** Debug builds fetch `/releases/tags/dev-latest`

The `/releases/latest` API endpoint automatically excludes pre-releases, so `dev-latest` never interferes with stable update checks.

## What Stays the Same

- **release-please** config and workflow: no changes, still watches main
- **CHANGELOG.md** format: label-based, generated from PRs merged to develop (not individual commits on main)
- **release.yml**: still triggers on main push, builds signed APKs
- **CI**: all workflows run on both branches, PRs can target either

## Renovate

Dependency update PRs target `develop` via the `baseBranches` config. They flow to main through the promotion process.
