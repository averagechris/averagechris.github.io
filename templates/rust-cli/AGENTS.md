# example-cli project guidance

Use `jj` for version-control actions in this repository.

## Development

- Enter the toolchain with `direnv allow` or `nix develop`.
- Nix formatting uses wrapped `alejandra -q`; run `nix fmt` or `nix fmt -- --check .`.
- Prefer local checks: `nix run .#ci-fmt`, `nix run .#ci-clippy`, `nix run .#ci-test`, `nix run .#ci-machete`, `nix run .#ci-sort`, `nix run .#ci-deny`, `nix run .#ci-audit`.

## Release workflow

This repo uses the standard averagechris fleet interface:

```sh
nix run .#prepare-release -- --version X.Y.Z
nix run .#release-tag
nix build .#release-artifact
nix run .#release -- --version X.Y.Z --submit-linux-build
```

`builds/release-linux-x86_64.yml` is explicit-submit only; do not move it to `.builds/`.
