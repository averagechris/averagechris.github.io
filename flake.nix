{
  description = "Root homepage for averagechris.srht.site";

  nixConfig = {
    extra-substituters = ["https://averagechris-dotfiles.cachix.org"];
    extra-trusted-public-keys = ["averagechris-dotfiles.cachix.org-1:VwJkl5dG1+xGDY5x884mH/kVwwpgwBAdBKIF3BZiia4="];
  };

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    # Compatibility forwarding and the approved transitional srht channel.
    fleet.url = "github:averagechris/fleet";
  };

  outputs = {
    self,
    nixpkgs,
    flake-utils,
    fleet,
  }:
    {
      # Temporary compatibility layer for consumers of the site's old lib output.
      lib = fleet.lib;
    }
    // flake-utils.lib.eachDefaultSystem (
      system: let
        pkgs = nixpkgs.legacyPackages.${system};
        srhtPackage = fleet.packages.${system}.srht;
        python = pkgs.python3;
        mkApp = name: script: {
          type = "app";
          program = pkgs.lib.getExe (
            pkgs.writeShellApplication {
              inherit name;
              runtimeInputs = [
                python
                srhtPackage
              ];
              text = script;
            }
          );
        };

        buildPagesScript = pkgs.writeShellApplication {
          name = "build-pages";
          runtimeInputs = [
            python
            pkgs.gitMinimal
            pkgs.curl
            pkgs.zola
          ];
          text = ''
            ${repoScripts}
            exec python3 -m averagechris_site.build "$@"
          '';
        };

        publishPagesScript = pkgs.writeShellApplication {
          name = "publish-pages";
          runtimeInputs = [
            python
            srhtPackage
          ];
          text = ''
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
              site_config_args=(--site-config-not-found 404.html)
            fi
            # CI (builds.sr.ht oauth grant) exports OAUTH2_TOKEN and provisions
            # ~/.config/hut/config with `access-token "..."` (HCL); srht reads
            # SRHT_TOKEN. Locally, fall through to srht's own keyring auth.
            # shellcheck source=/dev/null
            source ${./scripts/sourcehut_auth.sh}
            sourcehut_auth
            exec srht pages publish "$tarball" --domain "$domain" "''${site_config_args[@]}"
          '';
        };

        refreshPagesScript = pkgs.writeShellApplication {
          name = "refresh-pages";
          runtimeInputs = [
            python
            srhtPackage
            publishPagesScript
            pkgs.gitMinimal
            pkgs.curl
            pkgs.zola
          ];
          text = ''
            ${repoScripts}
            exec python3 scripts/refresh_pages.py "$@"
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
          export PYTHONPATH="$repo_root/scripts''${PYTHONPATH:+:$PYTHONPATH}"
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
            # srht is deliberately listed rather than merely discovered: the
            # approved CLI closure must be warm before consumers advance fleet.
            approvedSrhtPaths = [srhtPackage];
            cacheablePackageNames = builtins.filter (name: name != "srht" && !(builtins.elem name uncachedPackageNames)) (builtins.attrNames packageOutputs);
            cacheableAppNames = builtins.filter (name: name != "srht" && !(builtins.elem name websiteAppNames)) (builtins.attrNames appOutputs);
          in
            approvedSrhtPaths
            ++ (map (name: packageOutputs.${name}) cacheablePackageNames)
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
        checks.srht-channel = assert self.packages.${system}.srht == srhtPackage;
        assert self.apps.${system}.srht.program == fleet.apps.${system}.srht.program;
          pkgs.runCommand "check-approved-srht-channel" {nativeBuildInputs = [pkgs.gnugrep];} ''
            grep -Fx ${pkgs.lib.escapeShellArg (toString srhtPackage)} ${flakeOutputCache}/nix-support/cache-paths
            touch "$out"
          '';

        apps = {
          # Re-export the input app verbatim; do not rebuild it with site nixpkgs.
          srht = fleet.apps.${system}.srht;

          build-pages = {
            type = "app";
            program = pkgs.lib.getExe buildPagesScript;
          };

          publish-pages = {
            type = "app";
            program = pkgs.lib.getExe publishPagesScript;
          };

          refresh-pages = {
            type = "app";
            program = pkgs.lib.getExe refreshPagesScript;
          };

          add-project = mkApp "add-project" ''
            ${repoScripts}
            exec python3 scripts/add_project.py "$@"
          '';

          note = mkApp "note" ''
            ${repoScripts}
            exec python3 scripts/note.py "$@"
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
            srhtPackage
            pkgs.zola
          ];
        };

        # Everything the hourly refresh CI job needs at runtime. thorny's
        # fleet-cache-warmer builds this and pushes it to cachix so the
        # builds.sr.ht job substitutes instead of building.
        packages.fleet-ci-closure = pkgs.symlinkJoin {
          name = "fleet-ci-closure";
          paths = [
            buildPagesScript
            publishPagesScript
            refreshPagesScript
          ];
        };

        # Re-export the approved input derivation verbatim. Consumer projects
        # may pass this to fleet presets as `srhtPackage`.
        packages.srht = srhtPackage;
        packages.flake-output-cache = flakeOutputCache;

        formatter = nixFormatter;
      }
    );
}
