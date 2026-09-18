# averagechris.srht.site

Fleet release tooling and the operational registry now live in
[`averagechris/fleet`](https://github.com/averagechris/fleet). This flake pins
that repository and temporarily forwards its `lib` output so existing consumers
of `lib.fleet.core`, `lib.fleet.presets.rust`, and `lib.mkFleetApps` keep working.
The website retains only `fleet-site.toml`, the acquisition fields needed to
render project pages.

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

Games are enrolled manually in checked `site-data/games.toml`. The central
publisher resolves the newest semver tag, verifies and safely extracts its web
artifact, and gives the extracted bundle ownership of `/games/<slug>/`.
`/games/` itself and its navigation entry remain site-owned.

One-time SourceHut setup for a game repository is still manual: create the repo,
allow the release identity to upload git artifacts (`OBJECTS:RW` plus repository
read grants), and allow its release job to submit the refresh build with secrets
(`builds.sr.ht/JOBS:RW`, `SECRETS:RO`, and profile read). The submitted refresh
manifest carries `pages.sr.ht/PAGES:RW`; it must always be submitted with
`--secrets`. No game repository receives direct Pages publication authority.
The standard `release` app uploads the web tarball and checksum before invoking
the reusable `lib.fleet.core.mkRefreshTriggerManifest` fragment, so the refresh
job's tag-and-artifact wait is the synchronization contract.

For fully tag-triggered SourceHut automation, `builds/release-web.yml` in the
game repository must use this ordering:

1. Run `nix run .#ci-web` and
   `nix build .#release-artifact --out-link result-release-artifact`.
2. Copy `result-release-artifact/<slug>-vX.Y.Z-web.tar.gz` and its `.sha256`
   into stable paths in the build user's home. They may also be listed under
   the build manifest's `artifacts` key for job diagnostics, but those
   short-lived build artifacts are not the release source.
3. Derive `tag=v$(node -p 'require("./package.json").version')`, verify that
   the checked-out commit is that tag, and upload both files as durable git tag artifacts with
   `srht git artifact upload -r <repo> --rev "$tag" ...`.
4. Only after both uploads succeed, submit the central refresh manifest with
   `TRIGGER_PROJECT=games/<slug>`, `TRIGGER_TAG=$tag`, and
   `TRIGGER_SHA=$(git rev-parse HEAD)`. The manifest runs
   `nix run .#refresh-pages` from this site repository and must be submitted
   with `srht builds submit --secrets`.

The release manifest needs the git artifact and build submission OAuth grants
listed above. Configure the repository's tag webhook/trigger for `refs/tags/v*`
to submit that manifest. `prepare-release` keeps the versioned artifact names in
the checked-in manifest synchronized with `package.json`; the fixture at
`tests/fixtures/web-game/builds/release-web.yml` demonstrates the field that is
stamped. Projects using the standard `release` app do not need a second
tag-triggered release job—the app performs the same build/upload/refresh order.

Project bootstrap and tracker audits are provided by `averagechris/fleet`.

Pushing to this repo also republishes the site via `.builds/pages.yml`.
`.builds/refresh-pages.yml` can be submitted by an external scheduler to run
`nix run .#refresh-pages`, which fingerprints fleet tags/main SHAs and publishes
only when the durable sources changed.

## Files

- `site-data/site.toml` — site metadata (about, links, domain)
- `site-data/projects.toml` — public project presentation and routing
- `fleet-site.toml` — generated site-facing acquisition projection from `averagechris/fleet`
- `site-data/games.toml` — browser-game registry and immutable web artifact contract
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
