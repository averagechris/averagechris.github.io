#!/usr/bin/env python3
"""Remote fleet acquisition for build_pages."""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.parse

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
    with tempfile.NamedTemporaryFile() as body:
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
            return pathlib.Path(body.name).read_bytes()
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
        except Exception:
            entry = None
        if entry:
            # refresh_pages hands off the refs from the build attempt's stable
            # before fingerprint so this render skips duplicate ls-remote calls.
            return dict(entry.get("tags", {})), entry.get("main_sha", "")
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


def download_artifact(repo: pathlib.Path, url: str, name: str, dest: pathlib.Path, *, soft: bool = False, sha256: str | None = None) -> bool:
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

    cache = artifact_cache_path(repo, name)
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists() and not valid(cache.read_bytes()):
        print(f"  warn: discarding invalid cached artifact {name}")
        cache.unlink()
    if not cache.exists():
        data = fetch(url, soft=soft)
        if data is None:
            return False
        if not valid(data):
            message = f"artifact {name} from {url} is empty or fails sha256 verification"
            if soft:
                print(f"  warn: {message}; skipping")
                return False
            fail(message)
        cache.write_bytes(data)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cache, dest)
    return True


def acquire_fleet_data(repo: pathlib.Path, config: dict, site_dir: pathlib.Path, base_url: str) -> dict:
    fleet = load_fleet(repo)
    cached_sha256, cached_absent = load_release_artifacts(repo)
    published: dict[str, bool] = {}
    meta: dict[str, dict] = {}
    pages: dict[str, set[str]] = {}
    fleet_projects: dict[str, dict] = {}
    state = {"generated_at": dt.datetime.now(dt.UTC).isoformat(), "trigger": {"source": os.environ.get("TRIGGER_SOURCE", "manual"), "project": os.environ.get("TRIGGER_PROJECT", ""), "tag": os.environ.get("TRIGGER_TAG", ""), "sha": os.environ.get("TRIGGER_SHA", "")}, "projects": {}}
    site_wiki = [
        {
            "slug": w.slug,
            "title": w.title,
            "description": w.description,
            "date": w.date,
            "body": w.body,
            "body_format": w.body_format,
            "source": "site",
        }
        for w in config["wiki"]
        if w.listed and not w.draft
    ]
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
    update_release_artifacts(repo, cached_sha256, cached_absent, learned_sha256, learned_absent)
    all_wiki = site_wiki + [page for info in fleet_projects.values() for page in info.get("wiki", [])]
    detect_wiki_collisions(all_wiki)
    return {"published": published, "meta": meta, "project_pages": {k: sorted(v) for k, v in pages.items()}, "projects": fleet_projects, "wiki": all_wiki, "state": state, "release_dates": {}}


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
