# AGENTS.md

This repo is two things:

1. **The homepage** for https://averagechris.srht.site/ (see README.md for the
   publish model and the root-publish caveat).
2. **The fleet control room**: `fleet.toml` registers my release-tier projects,
   which all share a standard release interface. Maintenance work across those
   repos is orchestrated from here, usually by dispatching one subagent per repo.

## The standard release interface (every fleet repo)

```sh
nix run .#prepare-release -- --version X.Y.Z   # bump version, date CHANGELOG, fix builds manifest
nix run .#release-tag                          # jj tag vX.Y.Z + push + move main
nix build .#release-artifact                   # reproducible tarball + .sha256
nix run .#build-pages [-- --include-existing-downloads]
nix run .#publish-pages                        # hut pages publish -s /<subdir>
nix run .#release -- --version X.Y.Z [--publish-pages] [--submit-linux-build] [--skip-*]
nix run .#ci-fmt / ci-clippy / ci-test         # lint gates (repo extras allowed)
```

Conventions: conventional commits; `CHANGELOG.md` with `## Unreleased`;
`vX.Y.Z` tags; jj-first VCS; release manifest at `builds/release-linux-x86_64.yml`
(runs only on explicit `hut builds submit` — never in `.builds/`);
`.jj-lint.toml` includes at least fmt+clippy+test. Per-repo quirks are recorded
in `fleet.toml` — read them before touching a repo.

Check conformance: `nix run .#fleet-status` (add `--nix` to verify flake apps).

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
- Host quirk: the global env sets `RUSTC_WRAPPER=sccache`, which breaks cc-rs
  builds in fresh workspaces outside `nix develop`. Workaround:
  `RUSTC_WRAPPER='' ...` (gander's ci wrappers already unset it).
- Validation floor before a subagent reports done: `nix flake show`,
  `nix run .#ci-fmt|ci-clippy|ci-test`, and `nix flake check` where defined.

### Recipe: dependency bump + patch release

Per repo subagent: workspace as above → `cargo update` (or targeted bumps) →
run ci gates + `jj lint` → describe as `chore(deps): ...` → report. Then the
human (with my help) reviews each workspace diff, merges (below), and runs
`nix run .#release -- --version X.Y.<n+1> --publish-pages --submit-linux-build`
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
- NEVER publish a tarball built with `--skip-mirror` (guard exists: `dist/PREVIEW_ONLY`)
- `projects.toml` must list every subdirectory ever published to the site
