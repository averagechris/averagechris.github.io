# How this fleet works

I keep my personal tools boring on purpose. Each release-tier repo is a small Rust/Nix/jj citizen with the same public buttons, so I do not have to remember six different rituals while trying to publish a tarball before coffee becomes archaeology.

The shared interface is a set of Nix flake apps. In any fleet repo, the release path is meant to look like this:

```sh
nix run .#prepare-release -- --version X.Y.Z   # bump version, date CHANGELOG, fix builds manifest
nix run .#release-tag                          # jj tag vX.Y.Z + push + move main
nix build .#release-artifact                   # reproducible tarball + .sha256
nix run .#build-pages [-- --include-existing-downloads]
nix run .#publish-pages                        # hut pages publish -s /<subdir>
nix run .#release -- --version X.Y.Z [--publish-pages] [--submit-linux-build] [--skip-*]
nix run .#ci-fmt / ci-clippy / ci-test         # lint gates; repos may add extras
```

That gives every project the same knobs: prepare a version, tag it, build a reproducible artifact, build the downloads page, publish the downloads page, or run the whole thing. The CI gates are also flake apps, because if a command matters, I want it named and reproducible instead of hiding in somebody's tab history.

The conventions are equally plain: conventional commits, a `CHANGELOG.md` with a `## Unreleased` section, `vX.Y.Z` tags, and jj-first version control. The SourceHut Linux release manifest lives at `builds/release-linux-x86_64.yml`, not under `.builds/`, so it only runs when explicitly submitted:

```sh
hut builds submit builds/release-linux-x86_64.yml
```

Release artifacts are built through Nix and published with checksums. The normal output is a tarball plus a sidecar `.sha256`, and the downloads page also exposes a `manifest.json` with per-artifact hashes. I like binaries that can be downloaded without installing a package manager, but I also like knowing exactly which pile of bytes arrived. Radical platform.

The website has one important SourceHut Pages wrinkle. Each project owns a subdirectory under this site. For example, `gander` publishes to `/gander/`, `ctx` publishes to `/ctx/`, and `linear-cli` publishes to `/linear-cli/`:

```sh
hut pages publish -s /<project> dist/pages.tar.gz
```

Subdirectory publishing preserves the rest of the site. The homepage repo, however, owns the root. A root publish replaces the whole site. Not updates. Replaces. Computers remain a trust exercise with invoices.

So the homepage builder mirrors every already-published project subdirectory before it publishes the root. `projects.toml` must list every subdirectory that should survive a root publish, even if it is not shown on the homepage. The builder pulls the live subdirectory index, `manifest.json`, and linked download artifacts into the root tarball, then publishes that complete copy.

```sh
# add a new project card / mirrored subdirectory
nix run .#add-project -- <path> --description "What it does"

# build the homepage tarball, mirroring existing project downloads first
nix run .#build-pages

# preview without mirroring; guarded so I do not publish it by accident
nix run .#build-pages -- --skip-mirror
nix run .#serve

# publish the root site
nix run .#publish-pages
```

The fleet registry is `fleet.toml`. It records the release-tier repos, their local paths, Pages subdirectories, version files, artifact prefixes, upstream forks when relevant, and repo-specific footguns. Current entries include `linear-cli`, `slack-rs`, `granola-cli`, `ctx`, `starship-jj`, and `gander`. The registry is also what `nix run .#fleet-status` uses to check whether the standard interface is present:

```sh
nix run .#fleet-status
nix run .#fleet-status -- --nix
```

Maintenance is orchestrated from the homepage repo, but not blindly applied from there. For cross-repo chores, I dispatch one agent per repo into an isolated jj workspace, usually under `/Users/chris/projects/.maint`. Agents are not allowed to push, tag, publish Pages, submit builds, or move bookmarks. They leave a described change. A human reviews the diff, merges it, and runs the release from the default workspace.

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
