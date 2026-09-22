I keep my personal tools boring on purpose. Each release-tier repo is a small Rust/Nix/jj citizen with the same public buttons, so I do not have to remember six different rituals while trying to publish a tarball before coffee becomes archaeology.

The shared interface is a set of Nix flake apps. In any fleet repo, the release path is meant to look like this:

```sh
nix run .#release -- --version X.Y.Z [--submit-linux-build]
nix run .#release -- --version X.Y.Z --check # readiness only
nix run .#ci-fmt / ci-clippy / ci-test         # lint gates; repos may add extras
```

`prepare-release`, `release-tag`, and `release-artifact` remain lower-level
building blocks; routine releases use the single `release` command above.

That gives every project the same knobs: prepare a version, tag it, build a reproducible artifact, or run the whole release path. The release app publishes release assets through the repository's configured provider and submits a root-site refresh instead of publishing Pages from each repo. The CI gates are also flake apps, because if a command matters, I want it named and reproducible instead of hiding in somebody's tab history.

The conventions are equally plain: conventional commits, a `CHANGELOG.md` with a `## Unreleased` section, `vX.Y.Z` tags, and jj-first version control. The SourceHut Linux release manifest lives at `builds/release-linux-x86_64.yml`, not under `.builds/`, so it only runs when explicitly submitted:

```sh
hut builds submit builds/release-linux-x86_64.yml
```

Release artifacts are built through Nix and published with checksums. The normal output is a tarball plus a sidecar `.sha256`, and the downloads page also exposes a `manifest.json` with per-artifact hashes. I like binaries that can be downloaded without installing a package manager, but I also like knowing exactly which pile of bytes arrived. Radical platform.

The website has one important Pages wrinkle: this repo is the only publisher for `averagechris.github.io`. A root publish replaces the whole site. Not updates. Replaces. Computers remain a trust exercise with invoices.

So fleet repos publish durable inputs instead of Pages: annotated semver tags, provider release assets, `CHANGELOG.md`, and selected allowlisted optional `docs/pages/*.html` files from pinned main SHAs. The homepage builder resolves those inputs, hosts recent artifacts under each project subdirectory, renders downloads/changelog pages, copies optional project docs, writes `manifest.json`, and publishes one complete site artifact. The old SourceHut publisher remains available only for rollback.

```sh
# add a new project card / downloads subdirectory
nix run .#add-project -- <path> --description "What it does"

# build the homepage tarball from fleet tags/artifacts/docs
nix run .#build-pages

nix run .#serve

# publish the root site
nix run .#publish-pages
```

The operational registry lives in [averagechris/fleet](https://github.com/averagechris/fleet). It records the release-tier repos, local paths, version files, artifact prefixes, upstream forks, and repo-specific footguns. This website checks in only a generated acquisition projection. The owner repo also provides `fleet-status`:

```sh
nix run github:averagechris/fleet#fleet-status
nix run github:averagechris/fleet#fleet-status -- --nix
```

Maintenance is orchestrated from the fleet owner repo, but not blindly applied from there. For cross-repo chores, I dispatch one agent per repo into an isolated jj workspace, usually under `/Users/chris/projects/.maint`. Agents are not allowed to push, tag, publish Pages, submit builds, or move bookmarks. They leave a described change. A human reviews the diff, merges it, and runs the release from the default workspace.

```sh
cd <repo>
jj workspace add -r "trunk()" --name maint /Users/chris/projects/.maint/<name>
cd /Users/chris/projects/.maint/<name>

nix flake show
nix run .#ci-fmt
nix run .#ci-clippy
nix run .#ci-test
nix flake check
```

That is the whole scheme: common commands, explicit checks, checksummed artifacts, jj history, SourceHut Pages subdirectories, and a root publisher that knows it is carrying everyone else's furniture.
