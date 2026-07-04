# Uses

This is what my dotfiles say I actually run. Not aspirational desk-tour content. The computer equivalent of looking in the junk drawer.

## OS & machines

My systems are managed by a Nix flake that covers both NixOS and nix-darwin. The dotfiles repo is a multi-flake setup: each host has its own flake under `flakes/hosts/`, with shared NixOS, Darwin, Home Manager, and base library flakes underneath.

The active machines include `suremac` as an `aarch64-darwin` MacBook, plus NixOS hosts like `trap`, `thorny`, `cruber`, `tater`, `tom`, and `trainwreck`. Some are desktops, some are servers, and at least one exists because every household eventually grows a machine named like a warning label.

## Version control

I use jj (Jujutsu), colocated with git when necessary. My Home Manager module installs jj and wires up a small Rust helper called `jj-workflow` for things I do constantly: `jj lint`, `jj ship`, `jj sync`, `jj tag-push`, `jj ws`, and, on the work Mac, `jj pr`.

The prompt also uses my `starship-jj` package so the shell shows jj state without pretending git is still in charge.

## Editor

Helix is enabled by default, and `$EDITOR` becomes `hx` when Helix is on. The config uses the upstream Helix flake, Rose Pine Moon, relative line numbers, auto-formatting, LSP support, and formatters for Nix and Python. Neovim is still present with a `vim` alias, mostly as a polite fallback for computers with opinions.

## Terminal, shell, prompt

The shell stack is Zsh, Starship, fzf, ripgrep, direnv with nix-direnv, jq, htop, lazygit, yazi, ranger, and a pile of small shell scripts. Zellij is configured but disabled by default.

On `suremac`, WezTerm is the configured terminal target for the global hotkey. The dotfiles also contain Ghostty, Kitty, Alacritty, and WezTerm modules, because terminal emulators are apparently a biome.

The prompt is Starship with normal git modules disabled and a custom jj module powered by `/starship-jj/`. It also shows active dev environments from direnv, mise, or Nix.

## Build tooling

Nix is the base layer. I use `nix flake check`, `nix develop`, `nh` for ergonomic NixOS/Darwin builds, `nom` for more readable raw Nix builds, deploy-rs for Linux deployments, and Alejandra/Statix/ShellCheck for dotfiles linting.

Rust-heavy development on `suremac` uses a shared `sccache` setup. Cargo is configured with `rustc-wrapper = sccache`, `SCCACHE_DIR=~/.cache/sccache`, and a 50G cache. A launchd agent keeps the sccache server alive with a clean environment, and another launchd job prunes old Docker/OrbStack build junk. Very glamorous. Very useful.

## Small CLIs I run because I built them

Several of my own SourceHut CLIs are installed directly from flake inputs on `suremac`:

- [`linear-cli`](/linear-cli/) — a hardened Rust CLI for Linear.app: keyring-only auth, no telemetry, no self-update.
- [`slack-rs`](/slack/) — a hardened Slack Web API CLI for me and my friends, which is a threat and a promise.
- [`granola-cli`](/granola-cli/) — a Rust CLI for Granola meeting notes, seeded into the OS keyring by Home Manager.
- [`ctx`](/ctx/) — local-first agent history search for past coding-agent sessions.
- [`gander`](/gander/) — a jj review TUI with durable viewed state, comments, and exportable review artifacts.
- [`starship-jj`](/starship-jj/) — the jj prompt module behind my Starship prompt.

Source lives under `https://git.sr.ht/~averagechris/`, and the project cards live at `/tools/` if I remembered to make that page by the time you read this.
