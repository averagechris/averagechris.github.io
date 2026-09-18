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

Browser games follow the same single-publisher rule. `site-data/games.toml` is
the canonical, checked registry; it currently registers Palabra. A game release
attaches exactly `<artifact_prefix>-vX.Y.Z-web.tar.gz` and a sibling
`.sha256` to its semver tag. The newest semver release is selected. The archive
may contain files directly or one top-level directory and may contain arbitrary
nested static assets. After checksum verification, the publisher strips the
optional top-level directory and gives the bundle ownership of
`/games/<slug>/`, including `index.html`. Zola owns only `/games/`.

Game extraction is a security boundary: absolute/traversing paths, duplicate
paths, links, devices and other special members are rejected; file count and
expanded byte limits are enforced; the configured entrypoint must be a regular
file. Extraction happens in a temporary directory before route-tree
replacement. Cached inputs are namespaced by repository, tag, and artifact,
and a corrupt cache entry is discarded rather than published. Same-origin game
JavaScript/WASM is trusted executable content, so game repositories must be as
trusted as this publisher and static output must never contain secrets.

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

`averagechris_site.build` (with `scripts/build_pages.py` retained as a thin
compatibility wrapper) is split into acquisition, Zola rendering, and assembly
phases. Acquisition writes `generated/fleet.json`, a derived, renderer-agnostic
JSON file for Zola materialization. Zola reads this file after it has
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
  - `project`: acquisition metadata copied from `fleet-site.toml` plus the public
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
- `games`: listed canonical game records augmented with `published`, `version`,
  `play_url`, and one `kind = web_game` artifact record. Unreleased games remain
  visible on the index as release-pending but have no play URL.
- `release_dates`: object keyed as `project-path/version` with ISO release dates
  read from the website-owned `release-dates.toml` cache.
- `release-artifacts.toml`: committed cache of immutable artifact sha256s and known-absent older artifacts, refreshed by `build-pages`.
- `state`: exact assembly payload written to published `/state.json`, including
  volatile `generated_at` and `trigger` metadata. Renderers should not need this
  except for parity checks; assembly owns it.

`state.games.<slug>` records `tag`, annotated `tag_sha`, pinned `main_sha`, and
the verified web artifact (`name`, `version`, `sha256`, source URLs). Refresh
fingerprints namespace these as `games/<slug>`. The before fingerprint is also
written to `FLEET_REFS_JSON`; acquisition consumes those exact tag/main refs for
both tools and games, then refresh fingerprints again before publication. A
missing or malformed pin is fatal rather than silently falling back to mutable
remote refs. A release-triggered refresh waits for the requested tag and at least one complete
artifact/checksum pair, avoiding the tag-to-artifact visibility race.
Tag object SHAs are part of both fingerprints, so even an unexpected tag
retarget cannot pass the stability check. A newest game tag without its checksum
is treated as a transient hard failure, never as permission to remove the prior
playable route. Main-branch publishing uses `refresh-pages --force`: site-code
changes always rebuild, while the same before/after release-input check prevents
a concurrent release from being overwritten by stale output.
Artifact names and parsed checksum digests are fingerprinted together, so a
same-name checksum change cannot be mistaken for stable input. Triggered builds
also require the annotated tag to peel to `TRIGGER_SHA` before accepting its
artifact pair.

`generated/fleet.json` is derived output and is ignored by version control. It
intentionally keeps site-domain-dependent strings only where current published
state and download manifests already require exact URLs; renderers receive the
domain/base URL separately for new links.

## Rendered-output regression validation

Before changing site rendering, build a known-good Zola baseline and the
candidate Zola output into separate directories and compare them with
`PYTHONPATH=scripts python3 -m averagechris_site.compare OLD_TREE NEW_TREE --ignore-volatile`
(or the thin `scripts/compare_site_trees.py` compatibility wrapper).
The harness checks URL inventory, structural HTML signals (titles, metadata,
headings, links, and visible content mass), and byte equality for non-HTML files
such as downloads, `.sha256` files, images, and JSON.

Use this as the local validation gate after pages-alike server QA. Missing HTML
pages, downloads, SHA files, HTML structural drift, or non-HTML byte mismatches
are blockers unless the URL/content change is intentional and documented.

Zola is the sole renderer. The build runs the normal acquisition phase first, so
docs, downloads, manifests, `state.json`, and `siteconfig.json` remain owned by
acquisition/assembly. The Zola renderer then materializes a temporary Zola tree from canonical
`site-data/` plus `generated/fleet.json`, copies `renderers/zola/templates`,
runs `zola build`, and merges only the generated HTML into `dist/site` without
clobbering acquired non-HTML files. Zola front matter is derived throwaway
input; the durable source of truth stays in `site-data/` and
`generated/fleet.json`.

## Shared fleet tooling

Shared release tooling lives in `averagechris/fleet`. This flake pins that repo
and temporarily forwards its `lib` output. The core
contains the standardized release pieces: semver validation, CHANGELOG stamping,
release manifest artifact-name rewrites, annotated release tags, reproducible
tarballs, sr.ht artifact upload orchestration, and site refresh trigger
manifests. A language preset supplies version stamping, optional verification,
CI gate apps, and build outputs for `mkReleaseTarball`. `lib.mkFleetApps` remains
the Rust preset alias for existing fleet repos.
The generic release app has a non-mutating `--check` preflight and requires a
Git-backed jj checkout. Prepared-tree validation and local artifact/checksum
verification happen before an atomic, leased publication of `main` and the
annotated tag. Artifact uploads are filename-idempotent. Rust presets preserve
fmt/clippy/test and accept extra app names through `releaseValidationApps`.
After publication the helper imports direct Git refs into jj, moves `main`, and
creates an empty child before fallible network work. Exact-match reruns resume
post-publication work automatically. Refresh and Linux jobs use stable tags;
active/successful jobs are reused while terminal-failed jobs may be retried.
`lib.fleet.presets.webGame` is independent of the Rust preset, whose behavior
and compatibility alias remain unchanged. The web preset defaults to
`package.json`, reads/stamps its JSON `version`, accepts optional `ciFmt`,
`ciTest`, and `ciCheck` derivations, adds `ci-web`, and packages a finished
static derivation into a platform-neutral deterministic tar/gzip
(sorted paths, normalized ownership/mode/time, gzip timestamp disabled) with a
matching SHA-256 file. Its standard `release` helper uploads the pair and
submits the central refresh, but does not permit a redundant Linux release job.

The reusable tag-trigger contract is `core.mkRefreshTriggerManifest`. It is a
shell fragment used after artifact and checksum upload, with `tag` and `commit`
in scope. It writes an ephemeral SourceHut manifest carrying `TRIGGER_SOURCE`,
`TRIGGER_PROJECT`, `TRIGGER_TAG`, and `TRIGGER_SHA`, checks out only this central
publisher, runs `nix run .#refresh-pages`, and submits with `--secrets`. Custom
tag-triggered release CI must first build `.#release-artifact`, upload both its
tarball and checksum to the checked-out semver tag, then preserve that refresh
environment and ordering rather than publishing Pages directly. The complete
manifest contract and required OAuth grants are documented in the README.
