{lib}: let
  q = lib.escapeShellArg;
  app = drv: {
    type = "app";
    program = lib.getExe drv;
  };

  core = rec {
    # Core release building blocks. Presets wire language-specific version and
    # validation behavior while keeping the fleet command names stable.
    mkPrepareRelease = {
      pkgs,
      pname,
      changelog ? "CHANGELOG.md",
      manifestPath ? "builds/release-linux-x86_64.yml",
      setVersion,
      verify ? null,
      runtimeInputs ? [],
      ...
    }:
      pkgs.writeShellApplication {
        name = "prepare-release";
        runtimeInputs = (with pkgs; [python3]) ++ runtimeInputs;
        text = ''
          set -euo pipefail
          usage() { printf 'usage: prepare-release [--version X.Y.Z]\n' >&2; }
          version=""
          while [ "$#" -gt 0 ]; do
            case "$1" in
              --version) version="''${2:-}"; shift 2 ;;
              -h|--help) usage; exit 0 ;;
              *) usage; exit 2 ;;
            esac
          done
          ${setVersion}
          VERSION="$version" PNAME=${q pname} CHANGELOG=${q changelog} MANIFEST_PATH=${q manifestPath} python3 - <<'PY'
          from pathlib import Path
          import datetime, os, re
          version = os.environ["VERSION"]
          if not isinstance(version, str) or not re.fullmatch(r"v?\d+\.\d+\.\d+", version):
              raise SystemExit(f"invalid semver version: {version}")
          version = version.removeprefix("v")
          manifest = Path(os.environ["MANIFEST_PATH"])
          if manifest.exists():
              p = re.escape(os.environ["PNAME"])
              manifest.write_text(re.sub(rf"{p}-v\d+\.\d+\.\d+-x86_64-linux\.tar\.gz", f"{os.environ['PNAME']}-v{version}-x86_64-linux.tar.gz", manifest.read_text()))
          changelog = Path(os.environ["CHANGELOG"])
          content = changelog.read_text() if changelog.exists() else "# Changelog\n\n## Unreleased\n"
          if not content.startswith("# Changelog"): content = "# Changelog\n\n" + content
          if not re.search(r"(?m)^## Unreleased\s*$", content): content = content.rstrip() + "\n\n## Unreleased\n"
          tag = f"v{version}"
          if not re.search(rf"(?m)^## {re.escape(tag)}(?:\s+-\s+.*)?$", content):
              m = re.search(r"(?m)^## Unreleased\s*$", content); start = m.end()
              nxt = re.search(r"(?m)^## ", content[start:]); end = start + nxt.start() if nxt else len(content)
              body = content[start:end].strip() or "### Changed\n\n- Maintenance release."
              content = content[:start] + f"\n\n## {tag} - {datetime.date.today().isoformat()}\n\n{body}\n" + content[end:].lstrip("\n")
          changelog.write_text(content.rstrip() + "\n")
          PY
          ${lib.optionalString (verify != null) verify}
        '';
      };

    mkReleaseTag = {
      pkgs,
      pname,
      versionFile ? "Cargo.toml",
      versionExpr,
    }:
      pkgs.writeShellApplication {
        name = "release-tag";
        runtimeInputs = with pkgs; [git jujutsu python3];
        text = ''
          set -euo pipefail
          revision="@"; while [[ $# -gt 0 ]]; do case "$1" in --revision) revision="$2"; shift 2;; -h|--help) printf 'usage: release-tag [--revision REV]\n'; exit 0;; *) printf 'unknown argument: %s\n' "$1" >&2; exit 1;; esac; done
          repo_root="$(git rev-parse --show-toplevel 2>/dev/null || jj root)"; cd "$repo_root"
          version="$(python3 -c 'import pathlib,tomllib; data=tomllib.load(open(${q versionFile},"rb")); v=${versionExpr}; assert isinstance(v,str) and v; print(v)')"
          [[ "$version" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+$ ]] || { printf 'version must be semver\n' >&2; exit 1; }
          tag="v''${version#v}"
          [[ -z "$(git ls-remote --tags origin "refs/tags/$tag" 2>/dev/null)" ]] || { printf 'remote tag exists: %s\n' "$tag" >&2; exit 1; }
          if [[ -d .jj ]]; then commit="$(jj log -r "$revision" --no-graph --color=never -T 'commit_id')"; else commit="$(git rev-parse "$revision")"; fi
          git tag -fa "$tag" -m "${pname} $tag" "$commit"
          git push origin "refs/tags/$tag"
        '';
      };

    mkRefreshTriggerManifest = {
      pname,
      subdir ? pname,
    }: ''
      tmp="$(mktemp)"
      cat > "$tmp" <<EOF
      image: nixos/unstable
      arch: x86_64
      oauth: pages.sr.ht/PAGES:RW
      environment:
        NIX_CONFIG: "experimental-features = nix-command flakes"
        TRIGGER_SOURCE: release
        TRIGGER_PROJECT: ${subdir}
        TRIGGER_TAG: $tag
        TRIGGER_SHA: $commit
      sources:
        - https://git.sr.ht/~averagechris/averagechris.srht.site
      tasks:
        - refresh: |
            cd averagechris.srht.site
            nix run .#refresh-pages
      EOF
      hut builds submit "$tmp" --note "site refresh: ${pname} $tag" --visibility unlisted
    '';

    mkRelease = {
      pkgs,
      pname,
      srhtRepo ? pname,
      versionFile ? "Cargo.toml",
      versionExpr,
      refreshTrigger,
      prepareRelease,
      releaseTag,
      ciApps ? [],
      artifactPackage,
      linuxManifest ? "builds/release-linux-x86_64.yml",
      runtimeInputs ? [],
    }: let
      validateScript =
        if ciApps == []
        then "true"
        else lib.concatMapStringsSep "\n" (name: "nix run .#${name}") ciApps;
    in
      pkgs.writeShellApplication {
        name = "release";
        runtimeInputs = (with pkgs; [coreutils git hut jujutsu nix python3]) ++ runtimeInputs;
        text = ''
          set -euo pipefail; repo_root="$(git rev-parse --show-toplevel 2>/dev/null || jj root)"; cd "$repo_root"
          version=""; revision="@"; validate=1; tag_release=1; build_artifact=1; upload_artifact=1; submit_refresh=1; submit_linux_build=0; linux_manifest=${q linuxManifest}
          while [[ $# -gt 0 ]]; do case "$1" in --version) version="$2"; shift 2;; --revision) revision="$2"; shift 2;; --skip-validate) validate=0; shift;; --skip-tag) tag_release=0; shift;; --skip-artifact) build_artifact=0; shift;; --skip-upload) upload_artifact=0; shift;; --skip-refresh) submit_refresh=0; shift;; --submit-linux-build) submit_linux_build=1; shift;; -h|--help) printf 'usage: release [--version X.Y.Z] [--submit-linux-build] [--skip-*]\n'; exit 0;; *) printf 'unknown argument: %s\n' "$1" >&2; exit 1;; esac; done
          args=(); [[ -n "$version" ]] && args=(--version "$version"); nix run .#prepare-release -- "''${args[@]}"
          version="$(python3 -c 'import tomllib; data=tomllib.load(open(${q versionFile},"rb")); print(${versionExpr})')"; tag="v''${version#v}"
          if [[ -d .jj && -z "$(jj log -r @ --no-graph --color=never -T 'description.first_line()')" ]]; then jj describe -m "chore: release $tag"; fi
          [[ $validate -eq 0 ]] || { ${validateScript}; }
          if [[ -d .jj ]]; then commit="$(jj log -r "$revision" --no-graph --color=never -T 'commit_id')"; else commit="$(git rev-parse "$revision")"; fi
          if [[ $tag_release -eq 1 ]]; then nix run .#release-tag -- --revision "$commit"; if [[ -d .jj ]]; then jj bookmark set main --revision "$commit"; jj git push --remote origin --bookmark main; fi; fi
          if [[ $build_artifact -eq 1 ]]; then nix build .#release-artifact --out-link result-release-artifact; fi
          if [[ $upload_artifact -eq 1 ]]; then for f in result-release-artifact/*.tar.gz; do hut git artifact upload -r ${q srhtRepo} --rev "$tag" "$f" "$f.sha256"; done; fi
          if [[ $submit_refresh -eq 1 ]]; then ${refreshTrigger}; fi
          if [[ $submit_linux_build -eq 1 ]]; then hut builds submit "$linux_manifest" --note "${pname} $tag linux release" --tags "${pname}/$tag/release" --visibility unlisted; fi
        '';
      };

    mkReleaseTarball = {
      pkgs,
      pname,
      version,
      contents,
    }: system: let
      platform =
        if pkgs.stdenv.hostPlatform.isDarwin && pkgs.stdenv.hostPlatform.isAarch64
        then "aarch64-darwin"
        else if pkgs.stdenv.hostPlatform.isDarwin && pkgs.stdenv.hostPlatform.isx86_64
        then "x86_64-darwin"
        else if pkgs.stdenv.hostPlatform.isLinux && pkgs.stdenv.hostPlatform.isAarch64
        then "aarch64-linux"
        else if pkgs.stdenv.hostPlatform.isLinux && pkgs.stdenv.hostPlatform.isx86_64
        then "x86_64-linux"
        else null;
      artifactName = "${pname}-v${version}-${platform}.tar.gz";
    in
      if platform == null
      then null
      else
        pkgs.runCommand "${pname}-release-artifact-${version}-${platform}" {nativeBuildInputs = with pkgs; [coreutils gnutar gzip];} ''
          stage="$TMPDIR/stage/${lib.removeSuffix ".tar.gz" artifactName}"; mkdir -p "$out" "$stage"
          ${contents system}
          tar --sort=name --format=ustar --mtime='@1' --owner=0 --group=0 --numeric-owner -C "$TMPDIR/stage" -cf - "${lib.removeSuffix ".tar.gz" artifactName}" | gzip -n > "$out/${artifactName}"
          sha256sum "$out/${artifactName}" | sed 's#.*/##' > "$out/${artifactName}.sha256"
        '';
  };

  presets.rust = args @ {
    pkgs,
    self,
    pname,
    binaries ? [pname],
    subdir ? pname,
    srhtRepo ? pname,
    versionMode ? "package",
    versionFile ? "Cargo.toml",
    lockPackages ? [pname],
    workspaceDepPins ? [],
    changelog ? "CHANGELOG.md",
    ...
  }: let
    cargoVersionExpr =
      if versionMode == "workspace"
      then ''data.get("workspace", {}).get("package", {}).get("version")''
      else ''data.get("package", {}).get("version")'';
    versionToml = builtins.fromTOML (builtins.readFile (self + "/${versionFile}"));
    version =
      if versionMode == "workspace"
      then versionToml.workspace.package.version
      else versionToml.package.version;
    rustToolchain = with pkgs; [cargo clippy rustc rustfmt stdenv.cc] ++ lib.optionals stdenv.isDarwin [libiconv];
    darwinLinkEnv = lib.optionalString pkgs.stdenv.isDarwin ''
      export LIBRARY_PATH="${pkgs.libiconv}/lib''${LIBRARY_PATH:+:$LIBRARY_PATH}"
    '';
    setCargoVersion = ''
      VERSION="$version" VERSION_MODE=${q versionMode} VERSION_FILE=${q versionFile} LOCK_PACKAGES=${q (lib.concatStringsSep "," lockPackages)} WORKSPACE_DEP_PINS=${q (lib.concatStringsSep "," workspaceDepPins)} python3 - <<'PY'
      from pathlib import Path
      import os, re, tomllib
      version = os.environ["VERSION"]
      version_file = Path(os.environ["VERSION_FILE"])
      mode = os.environ["VERSION_MODE"]
      if not version:
          data = tomllib.loads(version_file.read_text())
          version = (data.get("workspace", {}).get("package", {}) if mode == "workspace" else data.get("package", {})).get("version")
      if not isinstance(version, str) or not re.fullmatch(r"v?\d+\.\d+\.\d+", version):
          raise SystemExit(f"invalid semver version: {version}")
      version = version.removeprefix("v")
      text = version_file.read_text()
      if mode == "workspace":
          text, count = re.subn(r'(?ms)(\[workspace\.package\].*?^version = ")[^"]+?("\s*)', rf'\g<1>{version}\2', text, count=1)
          if count != 1: raise SystemExit("could not update [workspace.package] version")
      else:
          text, count = re.subn(r'(?ms)(\[package\].*?^version = ")[^"]+?("\s*)', rf'\g<1>{version}\2', text, count=1)
          if count != 1: raise SystemExit("could not update [package] version")
      for dep in filter(None, os.environ["WORKSPACE_DEP_PINS"].split(",")):
          pat = rf'(?m)^({re.escape(dep)} = \{{[^\n]*?version = ")[^"]+?("[^\n]*?\}})$'
          text, count = re.subn(pat, rf'\g<1>{version}\2', text, count=1)
          if count != 1: raise SystemExit(f"could not update [workspace.dependencies] {dep} pin")
      version_file.write_text(text)
      lock = Path("Cargo.lock")
      if lock.exists():
          lock_text = lock.read_text()
          for name in filter(None, os.environ["LOCK_PACKAGES"].split(",")):
              lock_text, count = re.subn(rf'(\[\[package\]\]\nname = "{re.escape(name)}"\nversion = ")[^"]+(")', rf'\g<1>{version}\2', lock_text, count=1)
              if count != 1: raise SystemExit(f"could not update Cargo.lock package {name}")
          lock.write_text(lock_text)
      Path(".fleet-release-version").write_text(version)
      PY
      version="$(cat .fleet-release-version)"
      rm .fleet-release-version
    '';
    prepareRelease = core.mkPrepareRelease {
      inherit pkgs pname changelog;
      setVersion = setCargoVersion;
      verify = "cargo check --locked --workspace";
      runtimeInputs = rustToolchain;
    };
    releaseTag = core.mkReleaseTag {
      inherit pkgs pname versionFile;
      versionExpr = cargoVersionExpr;
    };
    refreshTrigger = core.mkRefreshTriggerManifest {inherit pname subdir;};
    release = core.mkRelease {
      inherit pkgs pname srhtRepo versionFile refreshTrigger prepareRelease releaseTag;
      versionExpr = cargoVersionExpr;
      runtimeInputs = rustToolchain;
      ciApps = ["ci-fmt" "ci-clippy" "ci-test"];
      artifactPackage = releaseArtifact;
    };
    ciFmt = pkgs.writeShellApplication {
      name = "ci-fmt";
      runtimeInputs = rustToolchain;
      text = darwinLinkEnv + "\ncargo fmt --all -- --check\n";
    };
    ciClippy = pkgs.writeShellApplication {
      name = "ci-clippy";
      runtimeInputs = rustToolchain;
      text = darwinLinkEnv + "\ncargo clippy --locked --workspace --all-targets -- -D warnings\n";
    };
    ciTest = pkgs.writeShellApplication {
      name = "ci-test";
      runtimeInputs = rustToolchain;
      text = darwinLinkEnv + "\ncargo test --workspace\n";
    };
    releaseArtifact = core.mkReleaseTarball {
      inherit pkgs pname version;
      contents = system: ''
        ${lib.concatMapStringsSep "\n" (b: ''cp -p ${self.packages.${system}.${b}}/bin/${b} "$stage/${b}"; chmod 0555 "$stage/${b}"'') binaries}
        for f in README.md CHANGELOG.md LICENSE LICENSE-APACHE LICENSE-MIT; do [ -e ${self}/$f ] && cp -p ${self}/$f "$stage/$f" || true; done
      '';
    };
  in {
    packages.release-artifact = releaseArtifact;
    apps = {
      prepare-release = app prepareRelease;
      release-tag = app releaseTag;
      release = app release;
      ci-fmt = app ciFmt;
      ci-clippy = app ciClippy;
      ci-test = app ciTest;
    };
    inherit releaseArtifact;
  };
in {
  fleet = {inherit core presets;};
  mkFleetApps = presets.rust;
}
