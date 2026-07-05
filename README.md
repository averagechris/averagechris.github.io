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
jobs and by an hourly check. See [docs/architecture.md](docs/architecture.md)
for repo-internal implementation details.

## Usage

```sh
# add a new project card
nix run .#add-project -- my-project --description "What it does"

# create and manage notes
nix run .#note -- new "Title"
nix run .#note -- distill
nix run .#note -- publish <draft>

# build from fleet tags/artifacts, generate index.html, pack dist/pages.tar.gz
nix run .#build-pages

nix run .#serve            # http://localhost:8000

# publish to https://averagechris.srht.site/
nix run .#publish-pages
```

Pushing to this repo also republishes the site via `.builds/pages.yml`.
`.builds/refresh-pages.yml` can be submitted by an external scheduler to run
`nix run .#refresh-pages`, which fingerprints fleet tags/main SHAs and publishes
only when the durable sources changed.

## Files

- `projects.toml` — site metadata (about, links) and the project registry
- `content/` — root-owned Markdown pages rendered to `/<slug>/`
- `content/notes/` — published Markdown notes rendered to `/notes/<slug>/`
- `content/notes/_drafts/` — unpublished note drafts; never rendered
- `release-dates.toml` — cache of release tag dates used by CI builds
- `scripts/build_pages.py` — build fleet pages + generate homepage/tools + tar
- `scripts/refresh_pages.py` — race-safe fingerprint check and publish wrapper
- `scripts/add_project.py` — append a project entry to `projects.toml`
- `scripts/note.py` — create, distill, list, and publish notes
