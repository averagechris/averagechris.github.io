# AGENTS.md

This repo is two things:

1. **The single Pages publisher** for https://averagechris.srht.site/ (see
   README.md and docs/architecture.md for the build-from-sourcehut architecture).
2. **The fleet control room**: `fleet.toml` registers my release-tier projects,
   which all share a standard release interface. Maintenance work across those
   repos is orchestrated from here, usually by dispatching one subagent per repo.

## The standard release interface (every fleet repo)

```sh
nix run .#prepare-release -- --version X.Y.Z   # bump version, date CHANGELOG, fix builds manifest
nix run .#release-tag                          # annotated vX.Y.Z tag + push
nix build .#release-artifact                   # reproducible tarball + .sha256
nix run .#release -- --version X.Y.Z [--submit-linux-build] [--skip-*]
nix run .#ci-fmt / ci-clippy / ci-test         # lint gates (repo extras allowed)
```

Conventions: conventional commits; `CHANGELOG.md` with `## Unreleased`;
annotated `vX.Y.Z` tags (required for sr.ht ref artifacts) with attached sr.ht
artifacts; releases trigger this repo's `refresh-pages` build instead of per-repo
Pages publishing; jj-first VCS; release manifest at `builds/release-linux-x86_64.yml`
(runs only on explicit `hut builds submit` — never in `.builds/`);
`.jj-lint.toml` includes at least fmt+clippy+test. Per-repo quirks are recorded
in `fleet.toml` — read them before touching a repo.

Check conformance: `nix run .#fleet-status` (add `--nix` to verify flake apps).
Shared release helpers live under `lib.fleet.core`; Rust repos use
`lib.fleet.presets.rust` via the backward-compatible `lib.mkFleetApps` alias.
The preset accepts `ciExtraInputs` for extra PATH packages in the ci-* apps
(e.g. ctx needs python3 because its CLI tests spawn plugin helpers).

Fleet Nix formatting standard: use Alejandra through a quiet wrapper (`alejandra
-q`, defaulting no-arg `nix fmt` to formatting `.`). New scaffolds should expose
that wrapper as `formatter`; existing projects may still need a future cleanup
pass to replace nixfmt/raw Alejandra formatters.

New project bootstrap is `nix run .#new-project` from the target directory. It
infers the project name from the directory unless `--name` is provided and writes
public `.averagechris-project.toml` metadata, but intentionally does **not**
mutate this site checkout or edit `fleet.toml`/`projects.toml`. Site enrollment
automation is deferred; revisit a workflow driven by todos/workctl so Chris can
review and apply registry updates explicitly. Default homepage tier metadata is
`more`; use `--featured` only to mark card intent. Remote usage should include
`--accept-flake-config` so the averagechris-dotfiles Cachix substituter is used.

## sourcehut CI quirks (hard-won — trust these)

- sr.ht anti-scraper defenses tarpit BOTH python-urllib AND git's default
  user agent from datacenter IPs (silent multi-minute hangs in CI). Any
  fetch or `git ls-remote` against git.sr.ht in CI must send a real UA
  (see `USER_AGENT` in scripts/) and should retry once.
- The nixos/unstable build image has no system python3 or hut; the `build`
  user IS in trusted-users, so `NIX_CONFIG` `extra-substituters` in a
  manifest's environment works without extra ceremony.
- CI pulls from the `averagechris-dotfiles` cachix cache: every new build
  manifest should copy the NIX_CONFIG substituter block from
  `.builds/refresh-pages.yml`. `.builds/cache-flake.yml` builds and pushes this
  repo's generic `.#flake-output-cache` closure for non-website flake outputs;
  thorny's hourly `fleet-cache-warmer` still pushes each fleet repo's
  x86_64-linux `release-artifact` at main (see dotfiles docs/thorny.md).
- Fetching raw CI logs (hut can't): token lives on suremac at
  `~/Library/Application Support/hut/config`; then
  `curl -H "Authorization: Bearer $tok" https://builds.sr.ht/query/log/<job>/<task>/log`.
  The public log URLs are behind a go-away bot wall.

## Dispatching maintenance subagents

When asked to do maintenance across repos ("bump deps and cut a patch release
for x, y, z", "port worthwhile upstream changes", ...), dispatch one build
subagent per repo, in parallel. Every subagent prompt MUST include these
safety rules:

- Work in a jj workspace, never the default working copy (the owner may have
  active work, especially in gander):
  ```
  cd <repo>
  jj workspace add -r "trunk()" --name maint /Users/chris/projects/.maint/<name>
  cd /Users/chris/projects/.maint/<name>
  ```
  slack-rs quirk: `trunk()` can resolve to `main@upstream`; verify the parent
  is the local `main` bookmark.
- NEVER: `jj git push`, `jj tag`, `hut pages publish`, `hut builds submit`,
  or moving bookmarks. Subagents leave a described commit; the human reviews,
  merges, and releases.
- Pass along relevant quirks from `fleet.toml` and the repo's own AGENTS.md
  policies (e.g. linear-cli/slack-rs/ctx fork exclusions).
- Host quirk: `RUSTC_WRAPPER=sccache` is set globally and MUST stay working
  (shared compile cache keeps the disk from filling with per-project target
  artifacts). Never "fix" build failures by unsetting it. If C-dep builds fail
  with `sccache: ... Compiler not supported: "error: tool 'clang' not found"`,
  the sccache server daemon was started from a poisoned environment — run
  `sccache --stop-server` and retry (the supervised `sccache-server` launchd
  agent from dotfiles restarts a healthy one). `fleet-status` checks this.
- Validation floor before a subagent reports done: `nix flake show`,
  `nix run .#ci-fmt|ci-clippy|ci-test`, and `nix flake check` where defined.

### Recipe: dependency bump + patch release

Per repo subagent: workspace as above → `cargo update` (or targeted bumps) →
run ci gates + `jj lint` → describe as `chore(deps): ...` → report. Then the
human (with my help) reviews each workspace diff, merges (below), and runs
`nix run .#release -- --version X.Y.<n+1> --submit-linux-build`
from each repo's default workspace.

### Recipe: upstream fork review

For fork repos (see `upstream` in fleet.toml): `nix run .#fetch-upstream` →
review commits after the cutoff recorded in the repo's AGENTS.md → propose a
port list to the human (respecting the repo's permanent exclusions) → port
approved commits in a maint workspace → update the cutoff note in AGENTS.md.

### Merging a maint workspace

```sh
cd <repo>
jj log -r 'bookmarks(main)::'        # review; the maint change is a child of main
jj diff -r <change-id>
jj bookmark move main --to <change-id>
jj git push -b main
jj workspace forget maint && rm -rf /Users/chris/projects/.maint/<name>
```

If main moved since the workspace was created, `jj rebase -s <change-id> -d main` first.

## Homepage maintenance

- Add a project: `nix run .#add-project -- <path> --description "..." [--no-downloads] [--tier more]`
- Republish: push to this repo (CI does it) or `nix run .#build-pages && nix run .#publish-pages`
- Fleet project pages are rendered here from git.sr.ht tags, tag artifacts, and docs fetched from pinned main SHAs.
- Per-repo `build-pages`/`publish-pages` apps may still exist during migration, but this repo is the sole Pages publisher.

### Recipe: distill TIL notes

Run `nix run .#note -- distill`, then inspect each generated session stub with
`ctx show session <id>`. Replace the stub's checkbox line with 1–5 one-line
bullet facts that are TIL-worthy: plain, specific, and useful. Keep the
`ctx show session` reference line, delete stubs that yielded nothing
interesting, and leave the draft in `content/notes/_drafts/` for Chris to
review and publish. Agents never publish notes.
