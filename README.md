# averagechris.srht.site

## Shared release tooling

Fleet projects consume `lib.mkFleetApps` (an alias for the Rust preset at
`lib.fleet.presets.rust`) from this flake to expose the standard
`prepare-release`, `release-tag`, `release`, `ci-fmt`, `ci-clippy`, `ci-test`,
and `release-artifact` interface without copying release scripts. The shared
release flow is built from composable `lib.fleet.core` helpers, creates
annotated tags, uploads release tarballs as sr.ht tag artifacts, and submits a
SourceHut build that runs this site's `refresh-pages` publisher.

This flake is also the approved fleet channel for the `srht` CLI. It re-exports
the release-pinned input unchanged as `packages.${system}.srht` and
`apps.${system}.srht`; it is not rebuilt against this site's nixpkgs. Consumer
flakes pass the package into a preset:

```nix
fleet.lib.fleet.presets.rust {
  inherit pkgs self;
  pname = "example";
  srhtPackage = fleet.packages.${system}.srht;
}
```

Static release manifests invoke the same approved package with
`nix run --inputs-from . fleet#srht -- ...`. Projects update only their `fleet`
input; this site's lock owns the srht revision. The channel pin advances only
with `.#flake-output-cache` warming its x86_64-linux closure in Cachix—it is an
approved channel, not an unpinned “latest”.

Browser-game repositories use ecosystem-neutral `lib.fleet.presets.webGame`.
It reads and stamps `version` in `package.json`, accepts the caller's own CI
derivations, and emits one platform-neutral `<name>-vX.Y.Z-web.tar.gz` plus
`.sha256`. Pass the derivation whose root is the finished static site as
`webPackage`; there are no Cargo, Rust, Node, pnpm, or Vite assumptions inside
the preset. `--submit-linux-build` is intentionally rejected.

Palabra's flake-parts `perSystem` interface is:

```nix
let
  game = fleet.lib.fleet.presets.webGame {
    inherit pkgs self;
    pname = "palabra";
    subdir = "games/palabra";
    srhtRepo = "palabra";
    # Palabra owns these pnpm/Vite derivations. The preset only consumes them.
    webPackage = config.packages.web; # dist copied to $out; index.html at root
    ciFmt = config.packages.ci-fmt;
    ciTest = config.packages.ci-test;
    ciCheck = config.packages.ci-typecheck;
  };
in {
  packages = game.packages;
  apps = game.apps;
}
```

This exposes derivation `packages.release-artifact` and apps `prepare-release`,
`release-tag`, `release`, `ci-fmt`, `ci-test`, `ci-check`, `ci-web`, and
`static-checks`. Omit any caller CI derivation that Palabra does not need.

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
