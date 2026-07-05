# example-cli

This static template is valid for `nix flake init -t ...#rust-cli`, but it
cannot rename files or merge with an existing directory. Prefer the smart
scaffold command when starting real projects:

```sh
nix run --accept-flake-config git+https://git.sr.ht/~averagechris/averagechris.srht.site#new-project -- --description "A SourceHut CLI"
```

After using the raw template, replace `example-cli` in `Cargo.toml`,
`flake.nix`, and `src/main.rs`, then run:

```sh
cargo generate-lockfile
nix --accept-flake-config flake lock
```
