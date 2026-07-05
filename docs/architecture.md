# Architecture

This repo is the single Pages publisher for `averagechris.srht.site`. Fleet
projects publish durable inputs on sourcehut: semver tags, tag artifacts, and
selected files from pinned revisions. `build-pages` resolves each fleet repo's
latest semver tag and main SHA, downloads immutable tag artifacts, fetches
`CHANGELOG.md` at the tag, fetches optional docs pages from pinned main, and
records the exact inputs in `/state.json`.

Project release jobs submit an ephemeral refresh manifest equivalent to
`.builds/refresh-pages.yml`, with `TRIGGER_*` env. An hourly thorny timer is the
backstop. `refresh-pages` compares the latest tags and main SHAs to the live
`/state.json`; unchanged fingerprints exit cheaply. When inputs changed, it
rebuilds deterministically from sourcehut, fingerprints again before publishing,
and retries a bounded number of times so concurrent releases converge.

Optional project docs under selected allowlisted `docs/pages/*.html` filenames
(`overview.html`, `examples.html`, `example.html`, `demo.html`,
`changelog.html`, `tour.html`, and `sample-review.html`) are copied from pinned
fleet repo main SHAs and published as same-origin HTML beneath each project
subdirectory. Each copied docs page is capped at 1 MB. This is an intentional
trusted-fleet boundary: release-tier repos are allowed to ship project docs with
their own markup/scripts, but compromising any fleet repo can therefore publish
same-origin content under its project path. Prefer simple, self-contained docs
pages and treat expanding this to less-trusted repos as an architecture change.

Artifact downloads are cached locally under `.cache/artifacts/`. CI jobs pull
from the `averagechris-dotfiles` cachix cache as an extra substituter; thorny's
hourly `fleet-cache-warmer` pushes the site's `fleet-ci-closure` package (the
refresh job's full runtime closure) and each fleet repo's x86_64-linux
`release-artifact` closure at main, so refresh and linux release jobs
substitute instead of building.

## Shared fleet tooling

`nix/fleet-apps.nix` exports `lib.fleet.core` plus language presets. The core
contains the standardized release pieces: semver validation, CHANGELOG stamping,
release manifest artifact-name rewrites, annotated release tags, reproducible
tarballs, sr.ht artifact upload orchestration, and site refresh trigger
manifests. A language preset supplies version stamping, optional verification,
CI gate apps, and build outputs for `mkReleaseTarball`. `lib.mkFleetApps` remains
the Rust preset alias for existing fleet repos.
