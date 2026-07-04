# sccache, or: Rust ate my Mac in one workday

I had never heard of sccache until the yesterday. My work macbook ran out of disk space in a single afternoon. In the past I just had a script that would go run `cargo clean` in all of my checkouts that I would manually run occasionally. But with agentic coding, I really am working on a bunch of different things all at once with different jj workspaces and therefor compilinig like never before... haha.

So yeah tl;dr; my work macbook basically almost died. I manually deleted some stuff then learned about sccache. It's made a huge difference :D

[sccache](https://github.com/mozilla/sccache)

How it works: you set `RUSTC_WRAPPER=sccache` and cargo runs every rustc call through sccache, which stashes the compiled output in one shared cache (`~/.cache/sccache`, capped at 50G for me). So when five workspaces are all compiling the same dependencies, it actually compiles once and everybody else gets cache hits. It also means `cargo clean` or deleting a `target/` dir is no big deal anymore, because the rebuild mostly comes back from cache.

One gotcha that bit me: by default sccache lazily starts a background server from whatever compile happens to run first, and that server keeps that process's environment forever. Mine got started from inside a nix shell, and after that every C compile failed with `tool 'clang' not found`. So I start the server myself in a launchctl job with a clean environment (see my [dotfiles](https://git.sr.ht/~averagechris/dotfiles)) so a poisoned lazy server can never win the race. If it ever gets weird anyway: `sccache --stop-server`.
