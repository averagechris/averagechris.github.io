{
  description = "Root homepage for averagechris.srht.site";

  nixConfig = {
    extra-substituters = ["https://averagechris-dotfiles.cachix.org"];
    extra-trusted-public-keys = ["averagechris-dotfiles.cachix.org-1:VwJkl5dG1+xGDY5x884mH/kVwwpgwBAdBKIF3BZiia4="];
  };

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    # Approved fleet channel. Advance this release tag only together with the
    # x86_64-linux flake-output-cache warm.
    srht.url = "git+https://git.sr.ht/~averagechris/srht?ref=refs/tags/v0.9.0";
  };

  outputs = {
    self,
    nixpkgs,
    flake-utils,
    srht,
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
        srhtPackage = srht.packages.${system}.srht;
        python = pkgs.python3;
        webGameFixtureWeb = pkgs.runCommand "web-game-fixture-web" {} ''
          mkdir -p "$out/assets"
          printf '<!doctype html><title>fixture</title>\n' > "$out/index.html"
          printf 'fixture\n' > "$out/assets/game.js"
        '';
        webGameFixtureCi = name:
          pkgs.writeShellApplication {
            inherit name;
            text = "true";
          };
        webGameFixture = self.lib.fleet.presets.webGame {
          inherit pkgs;
          self = ./tests/fixtures/web-game;
          pname = "web-game-fixture";
          webPackage = webGameFixtureWeb;
          ciFmt = webGameFixtureCi "fixture-fmt";
          ciTest = webGameFixtureCi "fixture-test";
          ciCheck = webGameFixtureCi "fixture-check";
          prepareVerify = null;
          inherit srhtPackage;
        };

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

        newProjectScript = pkgs.writeShellApplication {
          name = "new-project";
          runtimeInputs = [
            pkgs.python3
            pkgs.jujutsu
            pkgs.cargo
            pkgs.nix
            srhtPackage
          ];
          text = ''
            export PYTHONPATH=${./scripts}:''${PYTHONPATH:-}
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
        checks.web-game-preset = assert builtins.all (name: builtins.hasAttr name webGameFixture.apps) [
          "prepare-release"
          "release-tag"
          "release"
          "ci-fmt"
          "ci-test"
          "ci-check"
          "ci-web"
          "static-checks"
        ];
          pkgs.runCommand "check-web-game-preset" {
            nativeBuildInputs = with pkgs; [coreutils git gnugrep gnutar gzip jujutsu python3];
          } ''
              cp -R ${./tests/fixtures/web-game} work
              chmod -R u+w work
              cd work
            ${webGameFixture.apps.release.program} --help | grep -q -- '--check'
            RELEASE_PROGRAM=${webGameFixture.apps.release.program} python3 ${./tests/release_behavior.py}
            ${webGameFixture.apps.prepare-release.program} --version 1.2.4
            python3 -c 'import json; assert json.load(open("package.json"))["version"] == "1.2.4"'
            grep -q 'web-game-fixture-v1.2.4-web.tar.gz' builds/release-web.yml
            grep -q '^## v1.2.4 - ' CHANGELOG.md
            if ${webGameFixture.apps.prepare-release.program} --version 1.2.3; then
              printf 'prepare-release unexpectedly allowed a downgrade\n' >&2
              exit 1
            fi
              artifact=${webGameFixture.packages.release-artifact}
              (cd "$artifact" && sha256sum -c web-game-fixture-v1.2.3-web.tar.gz.sha256)
              tar -tzf "$artifact/web-game-fixture-v1.2.3-web.tar.gz" | grep -q '^web-game-fixture-v1.2.3-web/index.html$'
              touch "$out"
          '';

        checks.srht-channel = assert self.packages.${system}.srht == srhtPackage;
        assert self.apps.${system}.srht.program == srht.apps.${system}.srht.program;
          pkgs.runCommand "check-approved-srht-channel" {nativeBuildInputs = [pkgs.gnugrep];} ''
            grep -Fx ${pkgs.lib.escapeShellArg (toString srhtPackage)} ${flakeOutputCache}/nix-support/cache-paths
            touch "$out"
          '';

        apps = {
          # Re-export the input app verbatim; do not rebuild it with site nixpkgs.
          srht = srht.apps.${system}.srht;

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

          fleet-tracker-audit = mkApp "fleet-tracker-audit" ''
            ${repoScripts}
            exec python3 scripts/fleet_tracker_audit.py "$@"
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

        packages.new-project = newProjectScript;
        # Re-export the approved input derivation verbatim. Consumer projects
        # may pass this to fleet presets as `srhtPackage`.
        packages.srht = srhtPackage;
        packages.flake-output-cache = flakeOutputCache;

        formatter = nixFormatter;
      }
    );
}
