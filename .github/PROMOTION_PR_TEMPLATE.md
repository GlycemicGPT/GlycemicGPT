## Promotion: develop -> main

> **Merge with "Create a merge commit".** This maintains the ancestry link between
> develop and main, preventing divergence on future promotions.

### Pre-merge checklist

- [ ] CI passes on develop
- [ ] Dev Docker images smoke-tested (`ghcr.io/.../glycemicgpt-*:dev`)
- [ ] Dev APK tested on device (from `dev-latest` release)
- [ ] No known regressions

### Notable changes since last promotion

<!-- List significant changes included in this promotion -->

-

### Versioning

Commit types in this promotion determine the version bump:

| Type | Bump | Example |
|------|------|---------|
| `fix:` | PATCH (0.3.0 -> 0.3.1) | Bug fix, CI fix (`fix(ci): ...`) |
| `feat:` | MINOR (0.3.0 -> 0.4.0) | New user-facing feature |
| `feat!:` / `BREAKING CHANGE:` | MINOR (while pre-1.0; MAJOR after 1.0) | Breaking API change |
| `chore:`, `ci:`, `docs:`, etc. | Fallback PATCH (if deployable code changed) | Non-user-facing |

If all commits are non-releasable types but **deployable code paths changed** (`apps/api/`, `apps/web/`,
`apps/mobile/`, `sidecar/`, `plugins/`, `docker-compose*`, `Dockerfile*`), a fallback patch release
is created automatically.
If only docs/governance/CI files changed, **no release is created** -- no version bump, no container
builds, no APKs. This avoids unnecessary noise for downstream users.

### Post-merge steps

1. Release-please analyzes commits and one of three outcomes occurs:
   - **Code + releasable commits**: Release-please creates a version bump PR -- glycemicgpt-merge auto-merges it
   - **Code + non-releasable commits only**: The fallback job detects deployable changes and creates a patch release automatically
   - **Docs/governance only (no deployable code)**: No release is created -- no version bump, no container builds, no APKs
2. If a release was created: verify stable container images are published with new version tag
3. If a release was created: verify signed release APK is uploaded to the GitHub release
4. Version sync happens automatically (only when a release is created) -- the `sync-main-to-develop`
   workflow cherry-picks the version bump back to develop via PR. Verify it completed
   in the [Actions tab](../../actions/workflows/sync-main-to-develop.yml).
