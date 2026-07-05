{
  description = "Root homepage for averagechris.srht.site";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = {
    self,
    nixpkgs,
    flake-utils,
  }:
    {lib = import ./nix/fleet-apps.nix {lib = nixpkgs.lib;};}
    // flake-utils.lib.eachDefaultSystem (
      system: let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python3.withPackages (ps: [ps.markdown]);

        mkApp = name: script: {
          type = "app";
          program = pkgs.lib.getExe (
            pkgs.writeShellApplication {
              inherit name;
              runtimeInputs = [
                python
                pkgs.hut
              ];
              text = script;
            }
          );
        };

        mkAppWithInputs = name: runtimeInputs: script: {
          type = "app";
          program = pkgs.lib.getExe (
            pkgs.writeShellApplication {
              inherit name runtimeInputs;
              text = script;
            }
          );
        };

        repoScripts = ''
          export PYTHONUNBUFFERED=1
          export GIT_TERMINAL_PROMPT=0
          repo_root="$(git rev-parse --show-toplevel 2>/dev/null || jj root)"
          cd "$repo_root"
        '';
      in {
        apps = {
          build-pages = mkAppWithInputs "build-pages" [python pkgs.git pkgs.curl] ''
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
            site_config_args=()
            if [[ -f dist/siteconfig.json ]]; then
              site_config_args=(--site-config dist/siteconfig.json)
            fi
            exec hut pages publish "$tarball" --domain "$domain" "''${site_config_args[@]}"
          '';

          refresh-pages = mkAppWithInputs "refresh-pages" [python pkgs.hut pkgs.git pkgs.curl] ''
            ${repoScripts}
            exec python3 scripts/refresh_pages.py "$@"
          '';

          add-project = mkApp "add-project" ''
            ${repoScripts}
            exec python3 scripts/add_project.py "$@"
          '';

          note = mkApp "note" ''
            ${repoScripts}
            exec python3 scripts/note.py "$@"
          '';

          fleet-status = mkApp "fleet-status" ''
            ${repoScripts}
            exec python3 scripts/fleet_status.py "$@"
          '';

          serve = mkApp "serve" ''
            ${repoScripts}
            if [[ ! -d dist/site ]]; then
              printf 'missing dist/site; run: nix run .#build-pages\n' >&2
              exit 1
            fi
            exec python3 -m http.server --directory dist/site "''${1:-8000}"
          '';
        };

        devShells.default = pkgs.mkShell {
          packages = [
            python
            pkgs.hut
          ];
        };

        formatter = pkgs.nixfmt-rfc-style;
      }
    );
}
