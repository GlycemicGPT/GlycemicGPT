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
| `chore:`, `ci:`, `docs:`, etc. | Fallback PATCH | Non-user-facing (auto patch) |

If all commits are non-releasable types (`chore:`, `ci:`, `docs:`, `test:`, `style:`, `build:`),
the release workflow automatically creates a patch release. Every promotion produces a versioned
release -- no manual intervention required.

### Post-merge steps

1. Release-please analyzes commits and either:
   - Creates a version bump PR (if `feat:`/`fix:` commits exist) -- glycemicgpt-merge auto-merges it
   - Does nothing (if only `chore:`/`ci:`/`docs:` commits) -- the fallback job creates a patch release automatically
2. Verify stable container images are published with new version tag
3. Verify signed release APK is uploaded to the GitHub release
4. Version sync happens automatically -- the `sync-main-to-develop` workflow
   cherry-picks the version bump back to develop via PR. Verify it completed
   in the [Actions tab](../../actions/workflows/sync-main-to-develop.yml).
