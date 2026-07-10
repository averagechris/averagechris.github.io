# averagechris.srht.site

## Shared release tooling

Fleet projects consume `lib.mkFleetApps` (an alias for the Rust preset at
`lib.fleet.presets.rust`) from this flake to expose the standard
`prepare-release`, `release-tag`, `release`, `ci-fmt`, `ci-clippy`, `ci-test`,
and `release-artifact` interface without copying release scripts. The shared
release flow is built from composable `lib.fleet.core` helpers, creates
annotated tags, uploads release tarballs as sr.ht tag artifacts, and submits a
SourceHut build that runs this site's `refresh-pages` publisher.

The root homepage for <https://averagechris.srht.site/>: an about-me plus a
directory of my projects, each linking to its downloads page at
`https://averagechris.srht.site/<project>/`.

## Architecture

This repo is the single publisher for the whole site. Fleet project releases
provide durable sourcehut tags, tag artifacts, and repo files. `build-pages`
renders the root homepage plus project pages from those sources, and
`refresh-pages` publishes the result. Refreshes are triggered by project release
jobs and by an hourly check. Zola (`renderers/zola/`) is the sole renderer,
materialized from canonical `site-data/` plus `generated/fleet.json`. See
[docs/architecture.md](docs/architecture.md) for repo-internal implementation
details and [docs/site-rendering-plan.md](docs/site-rendering-plan.md) for
milestone status.

## Usage

```sh
# bootstrap a new Rust CLI/fleet project from that project directory
nix run --accept-flake-config git+https://git.sr.ht/~averagechris/averagechris.srht.site#new-project -- --description "A SourceHut CLI"

# or from this checkout, target an explicit project directory
nix run .#new-project -- --dir ../srht --description "A SourceHut CLI"

# add a new project card
nix run .#add-project -- my-project --description "What it does"

# create and manage notes
nix run .#note -- new "Title"
nix run .#note -- distill
nix run .#note -- publish <draft>

# build from fleet tags/artifacts with Zola and pack dist/pages.tar.gz
nix run .#build-pages

nix run .#serve            # pages-alike local server (live Pages CSP/MIME/404) on http://localhost:8000

# publish to https://averagechris.srht.site/
nix run .#publish-pages
```

`new-project` writes public `.averagechris-project.toml` metadata but does not
edit this site's `fleet.toml` or `site-data/projects.toml`; site enrollment is a manual
follow-up for now. It also documents the shared SourceHut tracker
<https://todo.sr.ht/~averagechris/projects>, follows the `repo:<name>` issue
label convention in generated README/AGENTS/project metadata/docs, and
idempotently creates that label with `srht todo labels create` when needed.

To audit existing fleet repos against the tracker convention without mutating
SourceHut, run:

```sh
nix run .#fleet-tracker-audit
```

Pushing to this repo also republishes the site via `.builds/pages.yml`.
`.builds/refresh-pages.yml` can be submitted by an external scheduler to run
`nix run .#refresh-pages`, which fingerprints fleet tags/main SHAs and publishes
only when the durable sources changed.

## Files

- `site-data/site.toml` — site metadata (about, links, domain)
- `site-data/projects.toml` — project registry; fleet release mechanics stay in `fleet.toml`
- `site-data/pages/` — root-owned page TOML sidecars + Markdown/HTML bodies rendered to `/<slug>/`
- `site-data/notes/` — published note TOML sidecars + bodies rendered to `/notes/<slug>/`
- `site-data/notes/_drafts/` — unpublished note drafts; the checked loader refuses to publish them
- `release-dates.toml` — cache of release tag dates used by CI builds
- `scripts/averagechris_site/` — internal Python package for site data,
  fleet acquisition, building, Zola materialization, and tree comparison
- `python3 -m averagechris_site.build` (or compatibility wrapper
  `scripts/build_pages.py`) — build fleet pages + generate homepage/tools + tar
- `scripts/refresh_pages.py` — race-safe fingerprint check and publish wrapper
- `python3 -m averagechris_site.data` (or compatibility wrapper
  `scripts/site_data.py`) — validate canonical `site-data/` (`PYTHONPATH=scripts python3 -m averagechris_site.data --check`)
- `scripts/add_project.py` — append a project entry to `site-data/projects.toml`
- `scripts/note.py` — create, distill, list, and publish notes
