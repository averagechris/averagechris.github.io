{
  description = "Root homepage for averagechris.srht.site";

  nixConfig = {
    extra-substituters = ["https://averagechris-dotfiles.cachix.org"];
    extra-trusted-public-keys = ["averagechris-dotfiles.cachix.org-1:VwJkl5dG1+xGDY5x884mH/kVwwpgwBAdBKIF3BZiia4="];
  };

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = {
    self,
    nixpkgs,
    flake-utils,
  }:
    {
      lib = import ./nix/fleet-apps.nix {lib = nixpkgs.lib;};
      templates.rust-cli = {
        path = ./templates/rust-cli;
        description = "Minimal Rust CLI wired to averagechris fleet release conventions. Use .#new-project for a named/idempotent scaffold.";
      };
    }
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

        buildPagesScript = pkgs.writeShellApplication {
          name = "build-pages";
          runtimeInputs = [
            python
            pkgs.git
            pkgs.curl
          ];
          text = ''
            ${repoScripts}
            exec python3 scripts/build_pages.py "$@"
          '';
        };

        refreshPagesScript = pkgs.writeShellApplication {
          name = "refresh-pages";
          runtimeInputs = [
            python
            pkgs.hut
            pkgs.git
            pkgs.curl
          ];
          text = ''
            ${repoScripts}
            exec python3 scripts/refresh_pages.py "$@"
          '';
        };

        newProjectScript = pkgs.writeShellApplication {
          name = "new-project";
          runtimeInputs = [
            pkgs.python3
            pkgs.jujutsu
            pkgs.cargo
            pkgs.nix
          ];
          text = ''
            exec python3 ${./scripts/new_project.py} "$@"
          '';
        };

        nixFormatter = pkgs.writeShellApplication {
          name = "alejandra";
          runtimeInputs = [pkgs.alejandra];
          text = ''
            if [[ $# -eq 0 ]]; then
              exec alejandra -q .
            fi

            exec alejandra -q "$@"
          '';
        };

        repoScripts = ''
          export PYTHONUNBUFFERED=1
          export GIT_TERMINAL_PROMPT=0
          repo_root="$(git rev-parse --show-toplevel 2>/dev/null || jj root)"
          cd "$repo_root"
        '';

        # Closure used by .builds/cache-flake.yml. Keep this generic so adding
        # non-website packages/apps/devshells/formatters automatically warms
        # them without having to edit the build manifest. Website publisher
        # outputs stay in fleet-ci-closure / the publish jobs.
        websiteAppNames = [
          "build-pages"
          "publish-pages"
          "refresh-pages"
          "serve"
        ];
        uncachedPackageNames = [
          "flake-output-cache"
          "fleet-ci-closure"
        ];
        # Cache app closures by linking the derivation root of conventional
        # $out/bin/<program> app paths. If a future app uses a nonstandard
        # program layout, give it a package output instead of relying on this.
        appProgramRoot = program: builtins.dirOf (builtins.dirOf program);
        flakeOutputCache = let
          cachePaths = let
            packageOutputs = self.packages.${system} or {};
            appOutputs = self.apps.${system} or {};
            cacheablePackageNames = builtins.filter (name: !(builtins.elem name uncachedPackageNames)) (builtins.attrNames packageOutputs);
            cacheableAppNames = builtins.filter (name: !(builtins.elem name websiteAppNames)) (builtins.attrNames appOutputs);
          in
            (map (name: packageOutputs.${name}) cacheablePackageNames)
            ++ (map (name: appProgramRoot appOutputs.${name}.program) cacheableAppNames)
            ++ [
              self.devShells.${system}.default
              self.formatter.${system}
            ];
        in
          pkgs.runCommand "averagechris-site-flake-output-cache" {} ''
            mkdir -p "$out/nix-support"
            cat > "$out/nix-support/cache-paths" <<'EOF'
            ${builtins.concatStringsSep "\n" (map toString cachePaths)}
            EOF
          '';
      in {
        apps = {
          build-pages = {
            type = "app";
            program = pkgs.lib.getExe buildPagesScript;
          };

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

          refresh-pages = {
            type = "app";
            program = pkgs.lib.getExe refreshPagesScript;
          };

          add-project = mkApp "add-project" ''
            ${repoScripts}
            exec python3 scripts/add_project.py "$@"
          '';

          new-project = {
            type = "app";
            program = pkgs.lib.getExe newProjectScript;
          };

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
            exec python3 scripts/serve_pages_alike.py dist/site "''${1:-8000}"
          '';
        };

        devShells.default = pkgs.mkShell {
          packages = [
            python
            pkgs.alejandra
            pkgs.hut
          ];
        };

        # Everything the hourly refresh CI job needs at runtime. thorny's
        # fleet-cache-warmer builds this and pushes it to cachix so the
        # builds.sr.ht job substitutes instead of building.
        packages.fleet-ci-closure = pkgs.symlinkJoin {
          name = "fleet-ci-closure";
          paths = [
            buildPagesScript
            refreshPagesScript
          ];
        };

        packages.new-project = newProjectScript;
        packages.flake-output-cache = flakeOutputCache;

        formatter = nixFormatter;
      }
    );
}
