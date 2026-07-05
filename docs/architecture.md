# Architecture

This repo is the single Pages publisher for `averagechris.srht.site`. Fleet
projects publish durable inputs on sourcehut: semver tags, tag artifacts, and
selected files from pinned revisions. `build-pages` resolves each fleet repo's
latest semver tag and main SHA, downloads immutable tag artifacts, fetches
`CHANGELOG.md` at the tag, fetches optional docs pages from pinned main, and
records the exact inputs in `/state.json`.

Project release jobs submit `.builds/refresh-pages.yml` with `TRIGGER_*` env.
An hourly thorny timer is the backstop. `refresh-pages` compares the latest tags
and main SHAs to the live `/state.json`; unchanged fingerprints exit cheaply.
When inputs changed, it rebuilds deterministically from sourcehut, fingerprints
again before publishing, and retries a bounded number of times so concurrent
releases converge.

Artifact downloads are cached locally under `.cache/artifacts/`. The refresh job
is substitution-only today; a binary cache for Rust release builds may be added
later.

## Shared fleet tooling

`nix/fleet-apps.nix` exports `lib.fleet.core` plus language presets. The core
contains the standardized release pieces: semver validation, CHANGELOG stamping,
release manifest artifact-name rewrites, annotated release tags, reproducible
tarballs, sr.ht artifact upload orchestration, and site refresh trigger
manifests. A language preset supplies version stamping, optional verification,
CI gate apps, and build outputs for `mkReleaseTarball`. `lib.mkFleetApps` remains
the Rust preset alias for existing fleet repos.
