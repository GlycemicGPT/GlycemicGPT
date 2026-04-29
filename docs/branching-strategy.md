# Branching Strategy

## Branch Model

| Branch | Purpose | Protected | Default |
|--------|---------|-----------|---------|
| `main` | Stable releases | Yes | Yes |
| `develop` | Integration / dev testing | Yes | No |

> **GitHub's "X commits behind main" counter on `develop` is non-substantive.** After each promotion, release-please bumps the version on `main` and the `sync-main-to-develop` workflow cherry-picks those commits back to `develop` as *new* commits with new SHAs. GitHub's counter compares SHAs, so the original `main`-side commits register as "missing" on `develop` even though the file content is identical. The two branches stay content-synced (same version, same `CHANGELOG.md`); only the commit graph drifts. Contributors should always target `develop` regardless of what the counter shows -- see [CONTRIBUTING.md](../CONTRIBUTING.md).

## Full Release Cycle

```
1. Create feature branch from develop
2. Open PR targeting develop, CI runs
3. Squash-merge to develop
4. (Automated) Dev Docker images tagged "dev", debug APK published as dev-latest pre-release
5. Repeat 1-4 for more features, test dev builds
6. When ready for stable release: create promotion PR (develop -> main)
7. CI runs on the promotion PR
8. Merge the promotion PR with "Create a merge commit" (maintains branch ancestry)
9. (Automated) release-please creates version bump PR on main
10. (Automated) glycemicgpt-merge auto-merges the version bump PR
11. (Automated) GitHub Release created, signed APK uploaded, Docker images tagged with version + "latest"
12. (Automated) sync-main-to-develop cherry-picks version/changelog changes back to develop
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

**Use "Create a merge commit"** for all promotion PRs. This maintains the ancestry link between develop and main, preventing divergence and merge conflicts on future promotions. The label-based changelog (`changelog-pr.yml`) generates granular entries from PR titles, labels, and contributor credits regardless -- it reads from the PRs merged to develop, not from commits on main.

After the promotion PR merges:
- **changelog-pr.yml** detects the promotion and generates a changelog from PR labels
- glycemicgpt-merge auto-merges the changelog PR
- If release-please detects releasable commits, it creates a version bump PR
- The `sync-main-to-develop` workflow cherry-picks any version changes back to develop
- A GitHub Release is created with signed APKs and versioned Docker images

### Post-merge: automated version sync

After a promotion merge, the changelog workflow generates entries and auto-merges to main. If release-please also creates a version bump (depends on commit types), the `sync-main-to-develop` workflow automatically cherry-picks these commits back to develop via PR. No manual intervention required.

The sync workflow:
1. Detects version bump or changelog commits on main
2. Cherry-picks them onto a branch from develop
3. Creates a PR and auto-merges with glycemicgpt-merge[bot]
4. Develop stays in sync with main's version numbers

Verify the sync completed in the [Actions tab](../../actions/workflows/sync-main-to-develop.yml). If the sync PR has unresolved conflicts (rare), resolve manually.

> **Note:** Develop has deletion protection in its branch ruleset, so it is NOT auto-deleted after promotion merges despite the repo-level "auto-delete head branches" setting.

## Versioning

GlycemicGPT uses [Conventional Commits](https://www.conventionalcommits.org/) with release-please for automated semantic versioning. The commit types in a promotion determine the version bump:

| Commit prefix | Version bump | When to use |
|---------------|-------------|-------------|
| `fix:` | PATCH (0.3.0 -> 0.3.1) | Bug fixes, CI fixes (`fix(ci): ...`), corrections |
| `feat:` | MINOR (0.3.0 -> 0.4.0) | New user-facing features or capabilities |
| `feat!:` / `BREAKING CHANGE:` | MINOR (while pre-1.0; MAJOR after 1.0) | Breaking API or behavior changes |
| `chore:`, `ci:`, `docs:`, `test:`, `style:`, `build:` | Fallback PATCH | Non-user-facing work |

### How it works

1. Developers use conventional commit prefixes on PRs merged to `develop`
2. On promotion (develop -> main), release-please analyzes commits since the last release
3. The highest-priority commit type determines the bump: `feat!:` > `feat:` > `fix:`
4. If no releasable commits exist (only `chore:`/`ci:`/`docs:`/etc.) but deployable code changed, a **fallback patch release** is created automatically
5. If no releasable commits exist AND no deployable code changed (doc-only promotion), **no release is created** -- no version bump, no container builds, no APKs

Promotions with deployable code changes always produce a versioned release. Doc-only promotions (README, GOVERNANCE, CODEOWNERS, docs/) do not create releases, avoiding unnecessary noise for downstream Renovate users.

**Deployable paths:** `apps/api/`, `apps/web/`, `apps/mobile/`, `sidecar/`, `plugins/`, `docker-compose*`, `Dockerfile*`. Changes outside these paths (docs, governance, CI workflows, assets) do not trigger releases.

### Choosing the right commit type

- **`feat:`** -- use only for new user-facing functionality. A CI improvement is NOT a feature.
- **`fix:`** -- use for bug fixes in any area, including CI/infrastructure (`fix(ci): ...`).
- **`chore:`/`ci:`/`docs:`** -- use for non-user-facing changes. These produce a patch release only if deployable code paths are affected.

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
