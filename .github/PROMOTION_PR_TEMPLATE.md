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

### Post-merge steps

1. Wait for release-please to create a version bump PR on main
2. glycemicgpt-merge auto-merges it (or merge manually)
3. Verify stable container images are published with new version tag
4. Verify signed release APK is uploaded to the GitHub release
5. Version sync happens automatically -- the `sync-main-to-develop` workflow
   cherry-picks the version bump back to develop via PR. Verify it completed
   in the [Actions tab](../../actions/workflows/sync-main-to-develop.yml).
