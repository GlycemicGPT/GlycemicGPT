# Third-Party Licenses

The GlycemicGPT web frontend redistributes the following third-party assets.
This file exists to credit the upstream authors and document the licenses
under which those assets are bundled with the project.

NPM runtime dependencies are covered by their respective licenses listed in
`package.json` lockfile metadata and are not re-listed here.

## Fonts

### Inter

- Project: https://github.com/rsms/inter
- Upstream release: https://rsms.me/inter/ (v4.1, 2024-11-16)
- License: SIL Open Font License 1.1 (`SIL OFL 1.1`)
- Copyright: Copyright (c) 2016 The Inter Project Authors

The Inter Variable font (`InterVariable.woff2`) is committed at
`apps/web/src/app/fonts/InterVariable.woff2` and is loaded via
`next/font/local` from `apps/web/src/app/layout.tsx`. The font is
redistributed unmodified from the upstream rsms/inter release.

A copy of the SIL OFL 1.1 license text is at
`apps/web/src/app/fonts/LICENSE.txt`.

This font was previously loaded via `next/font/google`, which made a
build-time HTTP request to `fonts.googleapis.com` on every Docker build.
That dependency was eliminated after the v0.8.0 web container release
build failed when Google Fonts was momentarily unreachable from a
GitHub Actions runner. See commit history on
`apps/web/src/app/layout.tsx` for the migration.
