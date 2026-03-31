## Promotion: develop -> main

> **IMPORTANT:** Merge this PR with **"Rebase and merge"**, NOT "Squash and merge".
> Rebase merge preserves individual commits so release-please generates a granular CHANGELOG.

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
5. Sync develop with the version bump:
   ```bash
   git fetch origin && git checkout develop && git rebase origin/main
   # Temporarily disable non_fast_forward rule on develop ruleset, then:
   git push origin develop --force-with-lease
   # Re-enable the rule immediately after
   ```
