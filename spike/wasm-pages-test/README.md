# WASM Pages Test Spike

This is a minimal static Leptos CSR island for verifying that a Nix-built WASM
bundle can be served as plain static files on SourceHut Pages.

## Build

```sh
./spike/wasm-pages-test/build.sh
```

The script uses `nix shell` for `cargo`, `rustc`, and
`wasm-bindgen-cli_0_2_117` (matching the `wasm-bindgen = 0.2.117` lockfile
entry), then builds a release `wasm32-unknown-unknown` cdylib and emits
wasm-bindgen web glue into `spike/wasm-pages-test/dist/`.

## Serve locally

```sh
cd spike/wasm-pages-test/dist
python3 -m http.server 8000
```

Open <http://127.0.0.1:8000/>. The page passes when the visible status and page
title include `SPIKE_PASS`.

## What it proves

- A Leptos CSR component mounts into `#island-root` from a same-origin module.
- The WASM bundle can perform a same-origin `fetch("./island-data.json")`.
- The generated wasm-bindgen loader is suitable for static hosting: current
  wasm-bindgen web output catches `WebAssembly.instantiateStreaming` MIME errors
  and falls back to ArrayBuffer instantiation.
- All asset references are relative, so the directory can be served under a
  path prefix such as `/labs/wasm-test/`.

## Bundle sizes

Run the build script to print current sizes. At the time of this spike:

```text
 34,546 bytes  dist/wasm_pages_test.js
209,936 bytes  dist/wasm_pages_test_bg.wasm
```
