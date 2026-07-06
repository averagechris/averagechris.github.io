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

## Generated fleet renderer contract

`scripts/build_pages.py` is split into acquisition, rendering, and assembly
phases. Acquisition writes `generated/fleet.json`, a derived, renderer-agnostic
JSON file for the HTML renderer. Renderers should read this file after it has
round-tripped through JSON rather than sharing Python-only objects.

Top-level fields:

- `published`: object keyed by project path. Values are booleans: `true` when a
  downloads page should be rendered, `false` when a release-enabled project has
  no semver release yet.
- `meta`: object keyed by project path. Values summarize the latest renderable
  release for homepage/tool cards: `version`, `platforms`, and `artifacts`.
  Each meta artifact has `name`, renderer-facing `url`, `sha256`, and `label`.
- `project_pages`: object keyed by project path. Values are sorted lists of
  fetched docs page filenames copied under that project path.
- `projects`: object keyed by project path with the complete fleet facts needed
  for a project downloads page and refresh fingerprinting:
  - `project`: project metadata copied from `fleet.toml` plus the public
    description from `site-data/projects.toml` (`name`, `pages_subdir`,
    `srht_repo`, `artifact_prefix`, optional `binaries`, and related fleet
    settings needed by the downloads page renderer).
  - `tag`: latest semver tag.
  - `tag_sha`: annotated tag object SHA from sourcehut.
  - `main_sha`: pinned `main` SHA used for docs acquisition.
  - `docs`: sorted copied docs page filenames.
  - `hosted_versions`: newest versions whose artifacts/checksums were copied
    into the published site.
  - `versions`: all semver tags discovered for the repo, newest first.
  - `changelog`: object keyed by semver tag with Markdown changelog excerpts.
  - `artifacts`: all discovered artifacts with `name`, `version`, `platform`,
    human `label`, `sha256`, `hosted`, `url`, and `sha_url`. Hosted artifacts
    use the same published URLs recorded in `state.json`; older non-hosted
    artifacts point at sourcehut tag artifact URLs.
- `release_dates`: object keyed as `project-path/version` with ISO release dates
  learned from local fleet checkouts or read from `release-dates.toml`.
- `state`: exact assembly payload written to published `/state.json`, including
  volatile `generated_at` and `trigger` metadata. Renderers should not need this
  except for parity checks; assembly owns it.

`generated/fleet.json` is derived output and is ignored by version control. It
intentionally keeps site-domain-dependent strings only where current published
state and download manifests already require exact URLs; renderers receive the
domain/base URL separately for new links.

## Shared fleet tooling

`nix/fleet-apps.nix` exports `lib.fleet.core` plus language presets. The core
contains the standardized release pieces: semver validation, CHANGELOG stamping,
release manifest artifact-name rewrites, annotated release tags, reproducible
tarballs, sr.ht artifact upload orchestration, and site refresh trigger
manifests. A language preset supplies version stamping, optional verification,
CI gate apps, and build outputs for `mkReleaseTarball`. `lib.mkFleetApps` remains
the Rust preset alias for existing fleet repos.
