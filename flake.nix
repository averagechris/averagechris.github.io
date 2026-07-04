{
  description = "Root homepage for averagechris.srht.site";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python3.withPackages (ps: [ ps.markdown ]);

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
          repo_root="$(git rev-parse --show-toplevel 2>/dev/null || jj root)"
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
            site_config_args=()
            if [[ -f dist/siteconfig.json ]]; then
              site_config_args=(--site-config dist/siteconfig.json)
            fi
            exec hut pages publish "$tarball" --domain "$domain" "''${site_config_args[@]}"
          '';

          refresh-pages = mkAppWithInputs "refresh-pages" [ python pkgs.hut pkgs.curl pkgs.diffutils ] ''
            ${repoScripts}
            domain="averagechris.srht.site"
            while [[ $# -gt 0 ]]; do
              case "$1" in
                --domain) domain="$2"; shift 2 ;;
                -h|--help) printf 'usage: refresh-pages [--domain DOMAIN]\n'; exit 0 ;;
                *) printf 'unknown argument: %s\n' "$1" >&2; exit 1 ;;
              esac
            done

            check_out="dist/refresh-check"
            live_out="dist/refresh-live"
            rm -rf "$check_out" "$live_out"
            mkdir -p "$live_out/tools"

            python3 scripts/build_pages.py --skip-mirror --out "$check_out" --domain "$domain"
            curl -fsSLo "$live_out/index.html" "https://$domain/index.html"
            curl -fsSLo "$live_out/tools/index.html" "https://$domain/tools/index.html"

            changed=0
            for path in index.html tools/index.html; do
              if ! cmp -s "$check_out/site/$path" "$live_out/$path"; then
                printf '%s is stale\n' "$path"
                changed=1
              fi
            done

            if [[ "$changed" -eq 0 ]]; then
              printf 'homepage project metadata is already current; nothing to publish\n'
              exit 0
            fi

            python3 scripts/build_pages.py --domain "$domain"
            site_config_args=()
            if [[ -f dist/siteconfig.json ]]; then
              site_config_args=(--site-config dist/siteconfig.json)
            fi
            hut pages publish dist/pages.tar.gz --domain "$domain" "''${site_config_args[@]}"
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
              printf 'missing dist/site; run: nix run .#build-pages -- --skip-mirror\n' >&2
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
