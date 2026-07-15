#!/usr/bin/env python3
"""Remote fleet acquisition for build_pages."""

from __future__ import annotations

import concurrent.futures
import dataclasses
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.parse

import site_measure

ARTIFACT_RE = re.compile(
    r"(.+)-(?P<version>v\d+\.\d+\.\d+)-"
    r"(?P<arch>x86_64|aarch64)-(?P<os>linux|darwin)\.tar\.gz$"
)
SEMVER_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")
PLATFORMS = ("aarch64-darwin", "x86_64-darwin", "aarch64-linux", "x86_64-linux")
DOC_PAGES = (
    "overview.html",
    "examples.html",
    "example.html",
    "demo.html",
    "changelog.html",
    "tour.html",
    "sample-review.html",
)
MAX_DOC_BYTES = 2_000_000
MAX_GAME_FILES = 10_000
MAX_GAME_MEMBERS = 12_000
MAX_GAME_BYTES = 256 * 1024 * 1024
RELEASE_ARTIFACTS_HEADER = """# Cache of immutable release artifact sha256s (and known-absent artifacts on
# older tags), updated automatically by build-pages. Safe to commit; CI reads
# it as-is. Delete a line to force a refetch.
[sha256]
"""


def fail(message: str) -> "sys.NoReturn":
    raise SystemExit(f"error: {message}")

USER_AGENT = "averagechris-fleet-pages (+https://averagechris.srht.site)"


def fetch(url: str, *, soft: bool = False) -> bytes | None:
    """Fetch a URL via curl. python-urllib gets tarpitted by sr.ht's
    anti-scraper defenses on datacenter IPs; curl with a real UA does not."""
    with tempfile.NamedTemporaryFile() as body, site_measure.operation(
        "acquisition_fetch_count", "acquisition_fetch_ms"
    ):
        try:
            result = subprocess.run(
                ["curl", "-sS", "--location", "--max-time", "120", "--retry", "2",
                 "--user-agent", USER_AGENT, "-o", body.name, "-w", "%{http_code}", url],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=420,
            )
        except subprocess.TimeoutExpired:
            fail(f"fetching {url}: curl timed out")
        code = result.stdout.strip()
        if result.returncode != 0 and not code.isdigit():
            if soft:
                return None
            fail(f"fetching {url}: {result.stderr.strip()}")
        if code == "200":
            data = pathlib.Path(body.name).read_bytes()
            site_measure.count("acquisition_transfer_bytes", len(data))
            return data
        if code == "404" or soft:
            return None
        fail(f"fetching {url}: HTTP {code}")


def run_text(command: list[str]) -> str:
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        fail(f"command timed out after 120s: {' '.join(command)}")
    if result.returncode != 0:
        fail(f"command failed: {' '.join(command)}\n{result.stderr.strip()}")
    return result.stdout


def semver_key(tag: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in tag.removeprefix("v").split("."))  # type: ignore[return-value]


def load_fleet(repo: pathlib.Path) -> dict[str, dict]:
    data = tomllib.loads((repo / "fleet.toml").read_text())
    return {r["pages_subdir"]: r for r in data.get("repos", []) if r.get("pages_subdir")}


def load_release_artifacts(repo: pathlib.Path) -> tuple[dict[str, str], dict[str, bool]]:
    path = repo / "release-artifacts.toml"
    if not path.exists():
        return {}, {}
    data = tomllib.loads(path.read_text())
    return dict(data.get("sha256", {})), dict(data.get("absent", {}))


def update_release_artifacts(repo: pathlib.Path, sha256: dict[str, str], absent: dict[str, bool], learned_sha256: dict[str, str], learned_absent: dict[str, bool]) -> None:
    changed = False
    for key, value in learned_sha256.items():
        if sha256.get(key) != value:
            sha256[key] = value; absent.pop(key, None); changed = True
    for key in learned_absent:
        if key not in sha256 and key not in absent:
            absent[key] = True; changed = True
    if changed:
        body = RELEASE_ARTIFACTS_HEADER
        body += "".join(f'"{k}" = "{sha256[k]}"\n' for k in sorted(sha256))
        body += "\n[absent]\n"
        body += "".join(f'"{k}" = true\n' for k in sorted(absent))
        (repo / "release-artifacts.toml").write_text(body)
        print("updated release-artifacts.toml with learned artifact shas; commit it with this change")


def ls_remote(srht_repo: str) -> tuple[dict[str, str], str]:
    refs_json = os.environ.get("FLEET_REFS_JSON")
    if refs_json:
        try:
            entry = json.loads(pathlib.Path(refs_json).read_text()).get(srht_repo)
        except (OSError, json.JSONDecodeError, AttributeError) as error:
            fail(f"invalid FLEET_REFS_JSON {refs_json}: {error}")
        if not isinstance(entry, dict) or not isinstance(entry.get("tags"), dict) or not isinstance(entry.get("main_sha"), str):
            fail(f"FLEET_REFS_JSON has no valid pinned refs for {srht_repo}")
        # refresh_pages hands off the refs from the build attempt's stable
        # before fingerprint so this render skips duplicate ls-remote calls.
        return dict(entry["tags"]), entry["main_sha"]
    # git's default UA gets tarpitted by sr.ht's anti-scraper defenses on
    # datacenter IPs just like python-urllib (observed as a silent 120s hang
    # in CI); send the same UA curl uses, and retry once since the tarpit
    # is intermittent.
    command = ["git", "-c", f"http.userAgent={USER_AGENT}", "ls-remote",
               f"https://git.sr.ht/~averagechris/{srht_repo}"]
    try:
        out = run_text(command)
    except SystemExit:
        out = run_text(command)
    tags: dict[str, str] = {}
    main_sha = ""
    for line in out.splitlines():
        sha, ref = line.split("\t", 1)
        if ref == "refs/heads/main":
            main_sha = sha
        elif ref.startswith("refs/tags/v") and not ref.endswith("^{}"):
            tag = ref.removeprefix("refs/tags/")
            if SEMVER_TAG_RE.match(tag):
                tags[tag] = sha
    return tags, main_sha


def srht_raw(repo_name: str, ref: str, path: str) -> str:
    return f"https://git.sr.ht/~averagechris/{repo_name}/blob/{urllib.parse.quote(ref, safe='')}/{urllib.parse.quote(path, safe='/')}"



def parse_wiki_manifest(data: bytes, *, repo_name: str, manifest_path: str = "docs/wiki/index.toml") -> list[dict]:
    try:
        manifest = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        fail(f"{repo_name} {manifest_path}: invalid wiki manifest: {error}")
    pages = manifest.get("pages", [])
    if not isinstance(pages, list):
        fail(f"{repo_name} {manifest_path}: missing [[pages]] table")
    parsed = []
    seen: set[str] = set()
    for index, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            fail(f"{repo_name} {manifest_path}: pages[{index}] must be a table")
        slug = str(page.get("slug", ""))
        if not re.match(r"^[a-z0-9][a-z0-9-]*$", slug):
            fail(f"{repo_name} {manifest_path}: pages[{index}].slug must be a lowercase URL slug")
        if slug in seen:
            fail(f"{repo_name} {manifest_path}: duplicate wiki slug {slug!r}")
        seen.add(slug)
        title = str(page.get("title", "")).strip()
        description = str(page.get("description", "")).strip()
        file = str(page.get("file", "")).strip()
        if not title or not description or not file:
            fail(f"{repo_name} {manifest_path}: page {slug!r} needs title, description, and file")
        if file.startswith("/") or ".." in pathlib.PurePosixPath(file).parts:
            fail(f"{repo_name} {manifest_path}: page {slug!r} file must stay under docs/wiki")
        parsed.append({"slug": slug, "title": title, "description": description, "file": file})
    return parsed


def detect_wiki_collisions(pages: list[dict]) -> None:
    owners: dict[str, list[str]] = {}
    for page in pages:
        owners.setdefault(page["slug"], []).append(str(page.get("source", "site")))
    collisions = {slug: vals for slug, vals in owners.items() if len(vals) > 1}
    if collisions:
        details = "; ".join(f"{slug}: {', '.join(vals)}" for slug, vals in sorted(collisions.items()))
        fail(f"duplicate wiki slug(s): {details}")

def srht_download(repo_name: str, tag: str, name: str) -> str:
    return f"https://git.sr.ht/~averagechris/{repo_name}/refs/download/{tag}/{urllib.parse.quote(name)}"


def parse_changelog(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        m = re.match(r"^## (v\d+\.\d+\.\d+)(?:\s+-\s+.*)?\s*$", line)
        if m:
            current = m.group(1)
            sections[current] = []
        elif current:
            if line.startswith("## "):
                current = None
            else:
                sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items() if "\n".join(v).strip()}


def platform_label(platform: str) -> str:
    arch, os_name = platform.split("-", 1)
    return f"{'macos' if os_name == 'darwin' else os_name} {'arm64' if arch == 'aarch64' and os_name == 'darwin' else arch}"


def artifact_cache_path(repo: pathlib.Path, name: str) -> pathlib.Path:
    safe = urllib.parse.quote(name, safe="")
    return repo / ".cache" / "artifacts" / safe


def download_artifact(repo: pathlib.Path, url: str, name: str, dest: pathlib.Path, *, soft: bool = False, sha256: str | None = None, cache_key: str | None = None) -> bool:
    """Copy a release artifact into place, verifying integrity against its sha256.

    A soft-failed fetch or a truncated/corrupt cache entry must never publish a
    bad tarball next to a valid .sha256 (seen once as a zero-byte artifact in a
    build output). Invalid cache entries are discarded and refetched.
    """
    def valid(data: bytes) -> bool:
        if not data:
            return False
        if sha256 is not None:
            return hashlib.sha256(data).hexdigest() == sha256
        return True

    cache = artifact_cache_path(repo, cache_key or name)
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists() and not valid(cache.read_bytes()):
        print(f"  warn: discarding invalid cached artifact {name}")
        cache.unlink()
    if not cache.exists():
        site_measure.count("artifact_cache_misses")
        data = fetch(url, soft=soft)
        if data is None:
            return False
        if not valid(data):
            message = f"artifact {name} from {url} is empty or fails sha256 verification"
            if soft:
                print(f"  warn: {message}; skipping")
                return False
            fail(message)
        with tempfile.NamedTemporaryFile(dir=cache.parent, delete=False) as staged:
            staged.write(data)
            staged_path = pathlib.Path(staged.name)
        staged_path.replace(cache)
        site_measure.count("artifact_transfer_bytes", len(data))
    else:
        site_measure.count("artifact_cache_hits")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if cache.resolve() != dest.resolve():
        shutil.copy2(cache, dest)
    return True


def parse_checksum(data: bytes, expected_name: str, source: str) -> str:
    try:
        fields = data.decode("ascii").strip().split()
    except UnicodeDecodeError as error:
        fail(f"{source}: checksum is not ASCII: {error}")
    if not fields or len(fields) > 2 or not re.fullmatch(r"[0-9a-fA-F]{64}", fields[0]):
        fail(f"{source}: expected a SHA-256 checksum")
    if len(fields) > 1 and fields[-1].lstrip("*") != expected_name:
        fail(f"{source}: checksum names {fields[-1]!r}, expected {expected_name!r}")
    return fields[0].lower()


def safe_extract_game(archive_path: pathlib.Path, destination: pathlib.Path, entrypoint: str) -> None:
    """Extract a static game bundle without trusting archive paths or links.

    Bundles may contain files directly or one conventional top-level archive
    directory. That directory is stripped; all other nested asset structure is
    preserved verbatim beneath the game's route.
    """
    with tarfile.open(archive_path, "r:*") as archive:
        members = archive.getmembers()
        if len(members) > MAX_GAME_MEMBERS:
            fail(f"{archive_path.name}: game bundle exceeds {MAX_GAME_MEMBERS} archive members")
        files = [member for member in members if member.isfile()]
        if len(files) > MAX_GAME_FILES:
            fail(f"{archive_path.name}: game bundle exceeds {MAX_GAME_FILES} files")
        total = sum(member.size for member in files)
        if total > MAX_GAME_BYTES:
            fail(f"{archive_path.name}: game bundle exceeds {MAX_GAME_BYTES} extracted bytes")
        raw_names: list[pathlib.PurePosixPath] = []
        for member in members:
            raw = pathlib.PurePosixPath(member.name)
            if member.name.startswith("/") or not raw.parts or any(part in ("", ".", "..") for part in raw.parts):
                fail(f"{archive_path.name}: unsafe archive path {member.name!r}")
            if not (member.isfile() or member.isdir()):
                fail(f"{archive_path.name}: links and special files are not allowed: {member.name!r}")
            raw_names.append(raw)
        entry = pathlib.PurePosixPath(entrypoint)
        strip_root: str | None = None
        if entry not in raw_names:
            roots = {path.parts[0] for path in raw_names}
            if len(roots) == 1:
                candidate = next(iter(roots))
                if pathlib.PurePosixPath(candidate) / entry in raw_names:
                    strip_root = candidate
        normalized: list[tuple[tarfile.TarInfo, pathlib.PurePosixPath]] = []
        seen: set[pathlib.PurePosixPath] = set()
        for member, raw in zip(members, raw_names, strict=True):
            parts = raw.parts[1:] if strip_root else raw.parts
            if not parts:
                continue
            rel = pathlib.PurePosixPath(*parts)
            if rel in seen:
                fail(f"{archive_path.name}: duplicate archive path {str(rel)!r}")
            seen.add(rel)
            normalized.append((member, rel))
        if entry not in seen or not any(m.isfile() for m, rel in normalized if rel == entry):
            fail(f"{archive_path.name}: required entrypoint {entrypoint!r} is missing")
        with tempfile.TemporaryDirectory(prefix="averagechris-game-") as tmp:
            stage = pathlib.Path(tmp)
            for member, rel in normalized:
                target = stage.joinpath(*rel.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    fail(f"{archive_path.name}: could not read {member.name!r}")
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o644)
            if destination.exists():
                shutil.rmtree(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(stage, destination)


def acquire_game(repo: pathlib.Path, game: object, site_dir: pathlib.Path) -> dict:
    slug = game.slug
    print(f"  games/{slug}: resolving tags", flush=True)
    tags, main_sha = ls_remote(game.srht_repo)
    versions = sorted(tags, key=semver_key, reverse=True)
    if not versions:
        return {"slug": slug, "published": False, "state": {"tag": "", "tag_sha": "", "main_sha": main_sha, "artifacts": []}}
    tag = versions[0]
    name = f"{game.artifact_prefix}-{tag}-web.tar.gz"
    url = srht_download(game.srht_repo, tag, name)
    checksum_data = fetch(url + ".sha256", soft=True)
    if checksum_data is None:
        fail(f"{game.srht_repo} {tag}: newest semver tag has no web artifact checksum yet; refusing to replace the last playable release")
    checksum = parse_checksum(checksum_data, name, url + ".sha256")
    cache_key = f"games/{game.srht_repo}/{tag}/{name}"
    cached = artifact_cache_path(repo, cache_key)
    if not download_artifact(repo, url, name, cached, soft=False, sha256=checksum, cache_key=cache_key):
        fail(f"{game.srht_repo} {tag}: web artifact disappeared after checksum became visible")
    safe_extract_game(cached, site_dir / "games" / slug, game.entrypoint)
    artifact = {"kind": "web_game", "name": name, "version": tag, "sha256": checksum, "url": url, "sha_url": url + ".sha256"}
    return {
        "slug": slug,
        "published": True,
        "game": dataclasses.asdict(game) if dataclasses.is_dataclass(game) else dict(game),
        "release": {"version": tag, "artifact": artifact, "play_url": f"/games/{slug}/" + ("" if game.entrypoint == "index.html" else game.entrypoint)},
        "state": {"tag": tag, "tag_sha": tags[tag], "main_sha": main_sha, "artifacts": [artifact]},
    }


def acquire_fleet_data(repo: pathlib.Path, config: dict, site_dir: pathlib.Path, base_url: str) -> dict:
    fleet = load_fleet(repo)
    cached_sha256, cached_absent = load_release_artifacts(repo)
    published: dict[str, bool] = {}
    meta: dict[str, dict] = {}
    pages: dict[str, set[str]] = {}
    fleet_projects: dict[str, dict] = {}
    state = {"generated_at": dt.datetime.now(dt.UTC).isoformat(), "publisher_sha": os.environ.get("PUBLISHER_SHA", ""), "trigger": {"source": os.environ.get("TRIGGER_SOURCE", "manual"), "project": os.environ.get("TRIGGER_PROJECT", ""), "tag": os.environ.get("TRIGGER_TAG", ""), "sha": os.environ.get("TRIGGER_SHA", "")}, "projects": {}}
    site_wiki = [{"slug": w.slug, "title": w.title, "description": w.description, "body": w.body, "body_format": w.body_format, "source": "site"} for w in config["wiki"] if w.listed and not w.draft]
    def worker(p: dict) -> dict:
        if not p.get("downloads", True) or p["path"] not in fleet:
            return {"path": p["path"], "published": None, "sha256": {}, "absent": {}}
        f = {**fleet[p["path"]], "description": p.get("description", "")}
        print(f"  {p['path']}: resolving tags", flush=True)
        tags, main_sha = ls_remote(f["srht_repo"])
        versions = sorted(tags, key=semver_key, reverse=True)
        if not versions:
            return {"path": p["path"], "published": False, "sha256": {}, "absent": {}}
        tag = versions[0]
        project_dir = site_dir / p["path"]; project_dir.mkdir(parents=True, exist_ok=True)
        docs = set()
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as inner:
            doc_futures = {inner.submit(fetch, srht_raw(f["srht_repo"], main_sha, f"docs/pages/{doc}"), soft=True): doc for doc in DOC_PAGES}
            changelog_future = inner.submit(fetch, srht_raw(f["srht_repo"], tag, "CHANGELOG.md"), soft=True)
            wiki_manifest_future = inner.submit(fetch, srht_raw(f["srht_repo"], main_sha, "docs/wiki/index.toml"), soft=True)
            doc_results = {doc: future.result() for future, doc in doc_futures.items()}
            changelog_text = (changelog_future.result() or b"").decode("utf-8", "replace")
            wiki_manifest_data = wiki_manifest_future.result()
            wiki_pages = []
            if wiki_manifest_data is None:
                print(f"  {p['path']}: no docs/wiki/index.toml; skipping wiki", flush=True)
            else:
                for wiki in parse_wiki_manifest(wiki_manifest_data, repo_name=f["srht_repo"]):
                    body_data = fetch(srht_raw(f["srht_repo"], main_sha, f"docs/wiki/{wiki['file']}"), soft=True)
                    if body_data is None:
                        print(f"  warn: {p['path']} docs/wiki/{wiki['file']} missing; skipping wiki page {wiki['slug']}", flush=True)
                        continue
                    if len(body_data) > MAX_DOC_BYTES:
                        fail(f"{f['srht_repo']} docs/wiki/{wiki['file']} is larger than {MAX_DOC_BYTES} bytes")
                    wiki_pages.append({**wiki, "body": body_data.decode("utf-8", "replace"), "body_format": "markdown", "source": f["name"], "project": {"name": f["name"], "pages_subdir": f["pages_subdir"]}})
            for doc in DOC_PAGES:
                data = doc_results[doc]
                if data is not None:
                    if len(data) > MAX_DOC_BYTES:
                        fail(f"{f['srht_repo']} docs/pages/{doc} is larger than {MAX_DOC_BYTES} bytes")
                    (project_dir / doc).write_bytes(data); docs.add(doc)

            sha_prefetches = []
            for index, v in enumerate(versions):
                for platform in PLATFORMS:
                    name = f"{f['artifact_prefix']}-{v}-{platform}.tar.gz"
                    url = srht_download(f["srht_repo"], v, name); sha_url = url + ".sha256"
                    key = f"{p['path']}/{name}"
                    hosted = index < 3
                    if hosted or (key not in cached_sha256 and key not in cached_absent):
                        sha_prefetches.append(((v, platform), inner.submit(fetch, sha_url, soft=True)))
            prefetched_sha = {k: future.result() for k, future in sha_prefetches}
        artifacts = []
        hosted_downloads = []
        learned_sha256: dict[str, str] = {}
        learned_absent: dict[str, bool] = {}
        for index, v in enumerate(versions):
            for platform in PLATFORMS:
                name = f"{f['artifact_prefix']}-{v}-{platform}.tar.gz"
                url = srht_download(f["srht_repo"], v, name); sha_url = url + ".sha256"
                key = f"{p['path']}/{name}"
                hosted = index < 3
                sha_data = None
                if not hosted and key in cached_sha256:
                    sha = cached_sha256[key]
                elif not hosted and key in cached_absent:
                    continue
                else:
                    sha_data = prefetched_sha[(v, platform)]
                    if sha_data is None:
                        if not hosted:
                            learned_absent[key] = True
                        continue
                    sha = sha_data.decode().split()[0]
                    learned_sha256[key] = sha
                if hosted:
                    hosted_downloads.append((url, name, project_dir / "downloads" / name, sha, sha_data or b""))
                artifacts.append({"name": name, "version": v, "platform": platform, "label": platform_label(platform), "url": (f"{base_url}/{p['path']}/downloads/{name}" if hosted else url), "sha_url": (f"{base_url}/{p['path']}/downloads/{name}.sha256" if hosted else sha_url), "sha256": sha, "hosted": hosted})
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as inner:
            download_futures = {
                inner.submit(download_artifact, repo, url, name, dest, soft=True, sha256=sha): (dest, name, sha_data)
                for url, name, dest, sha, sha_data in hosted_downloads
            }
            for future, (dest, name, sha_data) in download_futures.items():
                ok = future.result()
                if ok:
                    (dest.parent / f"{name}.sha256").write_bytes(sha_data)
        info = {"project": f, "tag": tag, "tag_sha": tags[tag], "main_sha": main_sha, "versions": versions, "docs": sorted(docs), "changelog": parse_changelog(changelog_text), "artifacts": artifacts, "wiki": wiki_pages}
        manifest = {"version": tag, "artifacts": [{"name": a["name"], "url": a["url"], "sha256": a["sha256"]} for a in artifacts]}
        (project_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        info.update({"hosted_versions": versions[:3]})
        return {"path": p["path"], "published": True, "docs": docs, "meta": parse_manifest(manifest) or {"version": tag, "artifacts": [], "platforms": []}, "state": {"tag": tag, "tag_sha": tags[tag], "main_sha": main_sha, "docs": sorted(docs), "hosted_versions": versions[:3], "artifacts": artifacts}, "info": info, "sha256": learned_sha256, "absent": learned_absent}

    learned_sha256: dict[str, str] = {}
    learned_absent: dict[str, bool] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(worker, p): p for p in config["projects"]}
        results = {futures[future]["path"]: future.result() for future in concurrent.futures.as_completed(futures)}
    for p in config["projects"]:
        result = results[p["path"]]
        learned_sha256.update(result["sha256"]); learned_absent.update(result["absent"])
        if result["published"] is None:
            continue
        published[p["path"]] = result["published"]
        if not result["published"]:
            continue
        pages[p["path"]] = result["docs"]
        meta[p["path"]] = result["meta"]
        state["projects"][p["path"]] = result["state"]
        fleet_projects[p["path"]] = result["info"]
    game_results: dict[str, dict] = {}
    games = list(config.get("games", []))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(acquire_game, repo, game, site_dir): game for game in games}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            game_results[result["slug"]] = result
    game_data = []
    state["games"] = {}
    for game in games:
        result = game_results[game.slug]
        state["games"][game.slug] = result["state"]
        if result["published"]:
            game_data.append({**result["game"], **result["release"], "published": True})
        elif game.listed:
            game_data.append({**dataclasses.asdict(game), "published": False, "version": "", "play_url": ""})
    update_release_artifacts(repo, cached_sha256, cached_absent, learned_sha256, learned_absent)
    all_wiki = site_wiki + [page for info in fleet_projects.values() for page in info.get("wiki", [])]
    detect_wiki_collisions(all_wiki)
    return {"published": published, "meta": meta, "project_pages": {k: sorted(v) for k, v in pages.items()}, "projects": fleet_projects, "games": game_data, "wiki": all_wiki, "state": state, "release_dates": {}}


def write_fleet_json(repo: pathlib.Path, fleet_json: dict) -> pathlib.Path:
    generated_dir = repo / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    path = generated_dir / "fleet.json"
    path.write_text(json.dumps(fleet_json, indent=2, sort_keys=True) + "\n")
    return path


def load_fleet_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text())


def parse_manifest(manifest: dict | None) -> dict | None:
    if not manifest:
        return None
    artifacts = [a for a in manifest.get("artifacts", []) if isinstance(a, dict)]
    version = manifest.get("version") or None
    if not version:
        versions = [
            match.group("version")
            for artifact in artifacts
            if (match := ARTIFACT_RE.match(str(artifact.get("name", ""))))
        ]
        version = sorted(set(versions))[-1] if versions else None
    if not version:
        return None
    current = []
    for artifact in artifacts:
        name = str(artifact.get("name", ""))
        match = ARTIFACT_RE.match(name)
        if not match or match.group("version") != version:
            continue
        os_name = "macos" if match.group("os") == "darwin" else match.group("os")
        arch = (
            "arm64"
            if match.group("arch") == "aarch64" and os_name == "macos"
            else match.group("arch")
        )
        current.append(
            {
                "name": name,
                "url": str(artifact.get("url", "")),
                "sha256": str(artifact.get("sha256", "")),
                "label": f"{os_name} {arch}",
            }
        )
    return {
        "version": version,
        "artifacts": current,
        "platforms": [artifact["label"] for artifact in current],
    }
