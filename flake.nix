{
  description = "Root homepage for averagechris.srht.site";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};

        mkApp = name: script: {
          type = "app";
          program = pkgs.lib.getExe (pkgs.writeShellApplication {
            inherit name;
            runtimeInputs = [ pkgs.python3 pkgs.hut ];
            text = script;
          });
        };

        repoScripts = ''
          repo_root="$(git rev-parse --show-toplevel)"
          cd "$repo_root"
        '';
      in
      {
        apps = {
          build-pages = mkApp "build-pages" ''
            ${repoScripts}
            exec python3 scripts/build_pages.py "$@"
          '';

          publish-pages = mkApp "publish-pages" ''
            ${repoScripts}
            domain="averagechris.srht.site"
            while [[ $# -gt 0 ]]; do
              case "$1" in
                --domain) domain="$2"; shift 2 ;;
                -h|--help) printf 'usage: publish-pages [--domain DOMAIN]\n'; exit 0 ;;
                *) printf 'unknown argument: %s\n' "$1" >&2; exit 1 ;;
              esac
            done
            tarball="dist/pages.tar.gz"
            if [[ ! -f "$tarball" ]]; then
              printf 'missing %s; run: nix run .#build-pages\n' "$tarball" >&2
              exit 1
            fi
            if [[ -f dist/PREVIEW_ONLY ]]; then
              printf 'dist/pages.tar.gz was built with --skip-mirror; publishing it would wipe project pages.\n' >&2
              printf 'rebuild with: nix run .#build-pages\n' >&2
              exit 1
            fi
            exec hut pages publish "$tarball" --domain "$domain"
          '';

          add-project = mkApp "add-project" ''
            ${repoScripts}
            exec python3 scripts/add_project.py "$@"
          '';

          serve = mkApp "serve" ''
            ${repoScripts}
            if [[ ! -d dist/site ]]; then
              printf 'missing dist/site; run: nix run .#build-pages -- --skip-mirror\n' >&2
              exit 1
            fi
            exec python3 -m http.server --directory dist/site "''${1:-8000}"
          '';
        };

        devShells.default = pkgs.mkShell {
          packages = [ pkgs.python3 pkgs.hut ];
        };

        formatter = pkgs.nixfmt-rfc-style;
      });
}
