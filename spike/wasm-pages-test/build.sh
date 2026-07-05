#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

rm -rf dist
mkdir -p dist

nix shell --inputs-from ../.. \
  nixpkgs#cargo \
  nixpkgs#rustc \
  nixpkgs#lld \
  nixpkgs#wasm-bindgen-cli_0_2_117 \
  --command bash -euo pipefail -c '
    cargo build --locked --release --target wasm32-unknown-unknown
    wasm-bindgen \
      --target web \
      --out-dir dist \
      --out-name wasm_pages_test \
      target/wasm32-unknown-unknown/release/wasm_pages_test.wasm
  '

cp index.html island-data.json dist/

printf 'Built static WASM test in %s/dist\n' "$(pwd)"
wc -c dist/wasm_pages_test.js dist/wasm_pages_test_bg.wasm
