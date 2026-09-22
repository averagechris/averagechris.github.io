#!/usr/bin/env python3
"""Race-safe refresh for the single-publisher Pages site."""

from __future__ import annotations

import argparse, concurrent.futures, copy, json, os, pathlib, re, shutil, subprocess, sys, tempfile, time, tomllib, urllib.parse

import site_measure

SEMVER = re.compile(r"^v\d+\.\d+\.\d+$")

def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, check=True, text=True, **kw)

def ls_refs(repo: str) -> tuple[list[str], str, str, dict[str, str], dict[str, str]]:
    """Return tags/latest/main plus tag-object and peeled commit SHAs."""
    # git's default UA gets tarpitted by sr.ht anti-scraper defenses on
    # datacenter IPs (silent multi-minute hang); use the curl UA and retry
    # once, with a hard timeout so the job fails loudly instead of hanging.
    command = ["git", "-c", f"http.userAgent={USER_AGENT}", "ls-remote",
               f"https://git.sr.ht/~averagechris/{repo}"]
    with site_measure.operation("git_ls_remote_count", "git_ls_remote_ms"):
        try:
            out = subprocess.check_output(command, text=True, timeout=120)
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
            site_measure.count("git_ls_remote_retries")
            out = subprocess.check_output(command, text=True, timeout=120)
    tags, tag_shas, tag_commits, main = [], {}, {}, ""
    for line in out.splitlines():
        sha, ref = line.split("\t", 1)
        if ref == "refs/heads/main": main = sha
        if ref.startswith("refs/tags/v") and ref.endswith("^{}"):
            tag_commits[ref.removeprefix("refs/tags/").removesuffix("^{}")] = sha
        elif ref.startswith("refs/tags/v"):
            tag = ref.removeprefix("refs/tags/")
            if SEMVER.match(tag):
                tags.append((tuple(map(int, tag[1:].split("."))), tag, sha)); tag_shas[tag] = sha
    tags.sort(reverse=True)
    for tag, sha in tag_shas.items():
        tag_commits.setdefault(tag, sha)
    return ([t[1] for t in tags], tags[0][1] if tags else "", main, tag_shas, tag_commits)

PLATFORMS = ("aarch64-darwin", "x86_64-darwin", "aarch64-linux", "x86_64-linux")
USER_AGENT = "averagechris-fleet-pages (+https://averagechris.srht.site)"

def github_release(repo: str) -> tuple[list[str], str, str, dict[str, str], dict[str, str], dict[str, dict]]:
    """Resolve public, published GitHub releases and their assets.

    Release publication is the atomic readiness signal: producers must publish
    only after every configured artifact and checksum has been uploaded.
    """
    releases = github_api(repo, "releases?per_page=100")
    assert isinstance(releases, list)
    published = [r for r in releases if not r.get("draft") and SEMVER.match(str(r.get("tag_name", "")))]
    published.sort(key=lambda r: tuple(map(int, r["tag_name"][1:].split("."))), reverse=True)
    refs = github_api(repo, "git/matching-refs/tags/v")
    published_names = {r["tag_name"] for r in published}
    annotated = [r for r in refs if r["ref"].removeprefix("refs/tags/") in published_names and r["object"].get("type") == "tag"]
    tag_shas = {r["ref"].removeprefix("refs/tags/"): r["object"]["sha"] for r in annotated}
    tag_commits = {tag: github_api(repo, f"git/tags/{sha}")["object"]["sha"] for tag, sha in tag_shas.items()}
    published = [r for r in published if r["tag_name"] in tag_shas]
    main = github_api(repo, "commits/main")
    assets = {r["tag_name"]: {a["name"]: a for a in r.get("assets", [])} for r in published}
    tags = [r["tag_name"] for r in published]
    return tags, tags[0] if tags else "", main["sha"], tag_shas, tag_commits, assets

def publisher_revision(root: pathlib.Path, *, provider: str = "sourcehut") -> str:
    try:
        local = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except subprocess.CalledProcessError:
        # Managed jj workspaces are intentionally not colocated Git checkouts.
        # `jj ws add` leaves an empty working-copy commit above the selected
        # source revision, so its parent is the content being published.
        local = subprocess.check_output(
            ["jj", "log", "-r", "@-", "--no-graph", "-T", "commit_id"],
            cwd=root,
            text=True,
        ).strip()
    if provider == "github":
        remote = github_main("averagechris/averagechris.github.io")
    else:
        remote = ls_refs("averagechris.srht.site")[2]
    if not remote or local != remote:
        raise SystemExit(f"publisher checkout {local} is not current main {remote or '<missing>'}")
    return local

def github_main(repo: str) -> str:
    return str(github_api(repo, "commits/main")["sha"])

def github_api(repo: str, path: str) -> object:
    url = f"https://api.github.com/repos/{repo}/{path}"
    command = ["curl", "-fsSL", "--retry", "2", "--user-agent", USER_AGENT,
               "-H", "Accept: application/vnd.github+json"]
    if token := os.environ.get("GITHUB_TOKEN"):
        command.extend(["-H", f"Authorization: Bearer {token}"])
    raw = subprocess.check_output([*command, url], text=True, timeout=120)
    return json.loads(raw)

def probe(url: str) -> bool:
    # Tri-state: only 200/404 are stable fingerprint inputs. Tarpits, 5xx,
    # empty codes, and curl failures retry once, then fail loudly rather than
    # silently flipping an artifact between present/absent.
    observed = []
    with site_measure.operation("probe_count", "probe_ms"):
        for attempt in range(2):
            if attempt:
                site_measure.count("probe_retries")
            try:
                r = subprocess.run(
                    ["curl", "-sI", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "30",
                     "--retry", "1", "--user-agent", USER_AGENT, url],
                    stdout=subprocess.PIPE, text=True, timeout=120)
                code = r.stdout.strip(); observed.append(code or f"curl exit {r.returncode}")
            except subprocess.TimeoutExpired:
                code = ""; observed.append("timeout")
            if code == "200": return True
            if code == "404": return False
    raise SystemExit(f"unstable artifact probe for {url}: {', '.join(observed)}")

def checksum(url: str, name: str) -> str | None:
    observed = []
    with site_measure.operation("checksum_count", "checksum_ms"):
        for attempt in range(2):
            if attempt:
                site_measure.count("checksum_retries")
            try:
                r = subprocess.run(
                    ["curl", "-sS", "--location", "--max-time", "30", "--retry", "1",
                     "--user-agent", USER_AGENT, "-w", "\n%{http_code}", url],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
                body, _, code = r.stdout.rpartition("\n")
                observed.append(code or f"curl exit {r.returncode}")
            except subprocess.TimeoutExpired:
                code, body = "", ""; observed.append("timeout")
            if code == "404": return None
            if code == "200":
                fields = body.strip().split()
                if not fields or len(fields) > 2 or not re.fullmatch(r"[0-9a-fA-F]{64}", fields[0]):
                    raise SystemExit(f"invalid checksum at {url}")
                if len(fields) == 2 and fields[1].lstrip("*") != name:
                    raise SystemExit(f"checksum at {url} names {fields[1]!r}, expected {name!r}")
                return fields[0].lower()
    raise SystemExit(f"unstable checksum fetch for {url}: {', '.join(observed)}")

def fingerprint(root: pathlib.Path, *, publisher_sha_override: str | None = None,
                publisher_provider: str = "sourcehut") -> tuple[dict[str, dict], dict[str, dict]]:
    """Latest tag + main sha + which platform artifacts exist on the latest tag.
    Artifacts are part of the fingerprint so a late-arriving Linux build still
    triggers a republish of an already-published tag."""
    fleet = {r["pages_subdir"]: r for r in tomllib.loads((root / "fleet-site.toml").read_text())["repos"]}
    # Only canonical site projects can appear in state.json. Fleet-only repos
    # are maintenance inventory, not render inputs, and previously made every
    # unchanged refresh look different from the live fingerprint.
    projects = tomllib.loads((root / "site-data" / "projects.toml").read_text()).get("projects", [])
    repos = [
        {**fleet[p["path"]], "kind": "native", "key": p["path"]}
        for p in projects
        if p.get("downloads", True) and p["path"] in fleet
    ]
    games = [{**g, "kind": "web_game", "key": f"games/{g['slug']}"} for g in tomllib.loads((root / "site-data" / "games.toml").read_text()).get("games", [])]
    entries = repos + games
    publisher_sha = publisher_sha_override or publisher_revision(root, provider=publisher_provider)
    out: dict[str, dict] = {"_publisher": {"main_sha": publisher_sha}}
    refs: dict[str, dict] = {}
    def one(r: dict) -> tuple[str, dict, str, dict]:
        repo = r.get("github_repo") if r.get("provider") == "github" else r.get("srht_repo", r.get("name", r.get("slug")))
        gh_assets = {}
        if r.get("provider") == "github":
            _, tag, main, tags, _, gh_assets = github_release(repo)
        else:
            _, tag, main, tags, _ = ls_refs(repo)
        artifacts = []
        if tag:
            prefix = r.get("artifact_prefix", r.get("name", r.get("slug")))
            suffixes = ["web"] if r["kind"] == "web_game" else expected_platforms(r)
            for suffix in suffixes:
                name = f"{prefix}-{tag}-{suffix}.tar.gz"
                if r.get("provider") == "github":
                    listed = gh_assets.get(tag, {})
                    asset = listed.get(name); sum_asset = listed.get(name + ".sha256")
                    url = asset["browser_download_url"] if asset else ""
                    digest = checksum(sum_asset["browser_download_url"], name) if asset and sum_asset else None
                    present = bool(asset and sum_asset)
                else:
                    url = f"https://git.sr.ht/~averagechris/{repo}/refs/download/{tag}/{name}"
                    present = probe(url); digest = checksum(url + ".sha256", name) if present else None
                if present:
                    if digest is not None:
                        artifacts.append({"name": name, "sha256": digest})
        return r["key"], {"tag": tag, "tag_sha": tags.get(tag, ""), "main_sha": main, "artifacts": sorted(artifacts, key=lambda a: a["name"])}, repo, {"tags": tags, "main_sha": main}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(one, r): r for r in entries}
        results = {futures[f]["key"]: f.result() for f in concurrent.futures.as_completed(futures)}
    for r in entries:
        page, fp, repo, ref = results[r["key"]]
        out[page] = fp; refs[repo] = ref
    return out, refs

def write_refs_json(root: pathlib.Path, refs: dict[str, dict]) -> pathlib.Path:
    (root / "dist").mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=root / "dist", prefix="fleet-refs-", suffix=".json", delete=False) as f:
        path = pathlib.Path(f.name)
    path.write_text(json.dumps(refs, sort_keys=True))
    return path

def live_state(domain: str) -> dict:
    with site_measure.operation("live_state_fetch_count", "live_state_fetch_ms"):
        r = subprocess.run(
            ["curl", "-sS", "--max-time", "60", "--retry", "1", "--user-agent", USER_AGENT,
             f"https://{domain}/state.json"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=180)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"projects": {}}

def live_fingerprint(domain: str) -> dict[str, dict]:
    state = live_state(domain)
    fp: dict[str, dict] = {}
    if state.get("publisher_sha"):
        fp["_publisher"] = {"main_sha": state["publisher_sha"]}
    for k, v in state.get("projects", {}).items():
        artifacts = sorted(({"name": a.get("name", ""), "sha256": a.get("sha256", "")} for a in v.get("artifacts", []) if a.get("version") == v.get("tag")), key=lambda a: a["name"])
        fp[k] = {"tag": v.get("tag", ""), "tag_sha": v.get("tag_sha", ""), "main_sha": v.get("main_sha", ""), "artifacts": artifacts}
    for k, v in state.get("games", {}).items():
        artifacts = sorted(({"name": a.get("name", ""), "sha256": a.get("sha256", "")} for a in v.get("artifacts", []) if a.get("version") == v.get("tag")), key=lambda a: a["name"])
        fp[f"games/{k}"] = {"tag": v.get("tag", ""), "tag_sha": v.get("tag_sha", ""), "main_sha": v.get("main_sha", ""), "artifacts": artifacts}
    return fp

def benchmark_live_fingerprint(current: dict[str, dict], scenario: str) -> dict[str, dict]:
    """Create controlled comparison input; callers must enforce no-publish."""
    controlled = copy.deepcopy(current)
    if scenario == "unchanged":
        return controlled
    if scenario == "palabra-main-sha-mismatch":
        key = "games/palabra"
        if key not in controlled:
            raise SystemExit("benchmark scenario requires canonical games/palabra")
        controlled[key]["main_sha"] = "0" * 40 if controlled[key].get("main_sha") != "0" * 40 else "f" * 40
        return controlled
    raise SystemExit(f"unknown benchmark live-state scenario: {scenario}")

def classify_comparison(current: dict[str, dict], live: dict[str, dict]) -> str:
    if current == live:
        return "unchanged"
    keys = set(current) | set(live)
    changed = []
    for key in sorted(keys):
        fields = set(current.get(key, {})) | set(live.get(key, {}))
        changed.extend((key, field) for field in sorted(fields) if current.get(key, {}).get(field) != live.get(key, {}).get(field))
    if changed == [("games/palabra", "main_sha")]:
        return "games.palabra.main_sha-only"
    return "other-mismatch"

def wait_for_trigger(root: pathlib.Path) -> None:
    project, tag, expected_sha = os.environ.get("TRIGGER_PROJECT"), os.environ.get("TRIGGER_TAG"), os.environ.get("TRIGGER_SHA")
    supplied = (bool(project), bool(tag), bool(expected_sha))
    if not any(supplied):
        return
    if not all(supplied):
        raise SystemExit("TRIGGER_PROJECT, TRIGGER_TAG, and TRIGGER_SHA must be supplied together")
    if not SEMVER.fullmatch(tag):
        raise SystemExit(f"TRIGGER_TAG must be a semver tag, got {tag!r}")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
        raise SystemExit("TRIGGER_SHA must be a full lowercase commit SHA")
    repos = [{**r, "kind": "native"} for r in tomllib.loads((root / "fleet-site.toml").read_text())["repos"]]
    games = [{**g, "kind": "web_game", "pages_subdir": f"games/{g['slug']}", "name": g["slug"]} for g in tomllib.loads((root / "site-data" / "games.toml").read_text()).get("games", [])]
    entry = next((r for r in repos + games if project in (r["pages_subdir"], r["name"], r.get("srht_repo"), r.get("github_repo"))), None)
    if entry is None:
        raise SystemExit(f"TRIGGER_PROJECT is not in the site registry: {project}")
    provider = entry.get("provider", "sourcehut") if entry else "sourcehut"
    repo = entry.get("github_repo") if provider == "github" else entry.get("srht_repo") or entry["name"]
    deadline, delay = time.monotonic() + 300, 5
    while time.monotonic() < deadline:
        gh_assets = {}
        if provider == "github":
            refs = github_release(repo)
            gh_assets = refs[5].get(tag, {})
        else:
            refs = ls_refs(repo)
        if tag in refs[0]:
            observed_sha = refs[4].get(tag, "")
            if observed_sha != expected_sha:
                raise SystemExit(f"trigger tag {project}/{tag} resolves to {observed_sha}, expected {expected_sha}")
            prefix = entry.get("artifact_prefix", entry["name"]) if entry else project
            suffixes = ["web"] if entry and entry["kind"] == "web_game" else expected_platforms(entry)
            ready = []
            for suffix in suffixes:
                name = f"{prefix}-{tag}-{suffix}.tar.gz"
                if provider == "github":
                    artifact = gh_assets.get(name)
                    sidecar = gh_assets.get(name + ".sha256")
                    complete = bool(artifact and sidecar and checksum(sidecar["browser_download_url"], name) is not None)
                else:
                    base = f"https://git.sr.ht/~averagechris/{repo}/refs/download/{tag}/"
                    complete = probe(base + name) and checksum(base + name + ".sha256", name) is not None
                if complete:
                    ready.append(name)
            if len(ready) == len(suffixes):
                print(f"trigger tag and artifact are visible: {project}/{tag} ({', '.join(ready)})")
                return
        print(f"waiting for {project}/{tag} and release artifact to appear...")
        time.sleep(delay); delay = min(delay * 2, 60)
    raise SystemExit(f"timed out waiting for {project}/{tag}")

def expected_platforms(entry: dict) -> list[str]:
    """Release platforms configured by the site projection.

    SourceHut rows retain the historical four-platform discovery default. A
    GitHub release is an atomic readiness contract, so migrated rows must state
    that contract explicitly rather than silently accepting the global default.
    """
    configured = entry.get("expected_platforms")
    if configured is None:
        if entry.get("provider", "sourcehut") == "sourcehut":
            return list(PLATFORMS)
        raise SystemExit(f"{entry.get('name', '<unnamed>')}: github provider requires expected_platforms")
    if (not isinstance(configured, list) or not configured or
            any(not isinstance(value, str) or value not in PLATFORMS for value in configured) or
            len(set(configured)) != len(configured)):
        raise SystemExit(f"{entry.get('name', '<unnamed>')}: invalid expected_platforms")
    return configured

def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="averagechris.srht.site")
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--force", action="store_true", help="build even when release inputs match live state")
    ap.add_argument(
        "--benchmark-live-state",
        choices=("unchanged", "palabra-main-sha-mismatch"),
        help="controlled comparison input for non-publishing benchmarks only",
    )
    args = ap.parse_args(argv)
    if args.benchmark_live_state and not args.no_publish:
        ap.error("--benchmark-live-state requires --no-publish")
    benchmark_publisher_sha = os.environ.get("BENCH_EXPECTED_REVISION", "")
    if args.benchmark_live_state and not re.fullmatch(r"[0-9a-f]{40}", benchmark_publisher_sha):
        ap.error("controlled benchmarks require a full BENCH_EXPECTED_REVISION")
    root = pathlib.Path(__file__).resolve().parent.parent
    publisher_provider = "github" if args.domain == "averagechris.github.io" else "sourcehut"
    def output(changed: bool) -> None:
        if path := os.environ.get("GITHUB_OUTPUT"):
            with open(path, "a") as handle:
                handle.write(f"changed={'true' if changed else 'false'}\n")
    wait_for_trigger(root)
    with site_measure.stage("before_fingerprint"):
        current, refs = fingerprint(
            root,
            publisher_sha_override=benchmark_publisher_sha or None,
            publisher_provider=publisher_provider,
        )
    with site_measure.stage("live_state_comparison"):
        live = benchmark_live_fingerprint(current, args.benchmark_live_state) if args.benchmark_live_state else live_fingerprint(args.domain)
        comparison = classify_comparison(current, live)
    print(f"fingerprint comparison: {comparison}")
    if not args.force and comparison == "unchanged":
        print("fingerprint unchanged; no publish needed")
        output(False)
        return
    before, before_refs = current, refs
    for attempt in range(1, 4):
        # Hand build_pages the exact refs captured by this attempt's before pass.
        refs_path = write_refs_json(root, before_refs)
        env = os.environ.copy()
        env["FLEET_REFS_JSON"] = str(refs_path)
        env["PUBLISHER_SHA"] = before["_publisher"]["main_sha"]
        with site_measure.stage("build"):
            run([sys.executable, "scripts/build_pages.py", "--domain", args.domain], cwd=root, env=env)
        with site_measure.stage("after_fingerprint"):
            after, after_refs = fingerprint(
                root,
                publisher_sha_override=benchmark_publisher_sha or None,
                publisher_provider=publisher_provider,
            )
        if before == after:
            if args.no_publish:
                print("would publish dist/pages.tar.gz")
                output(True)
                return
            # Prefer the app-provided binary to skip a second in-job flake eval/build.
            if shutil.which("publish-pages"):
                run(["publish-pages", "--domain", args.domain], cwd=root)
            else:
                run(["nix", "run", ".#publish-pages", "--", "--domain", args.domain], cwd=root)
            output(True)
            return
        print(f"fingerprint moved during build (attempt {attempt}); rebuilding")
        before, before_refs = after, after_refs
    raise SystemExit("fingerprint kept moving after 3 builds")

if __name__ == "__main__": main()
