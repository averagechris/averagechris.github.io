#!/usr/bin/env python3
"""Race-safe refresh for the single-publisher Pages site."""

from __future__ import annotations

import argparse, concurrent.futures, copy, json, os, pathlib, re, shutil, subprocess, sys, tempfile, time, tomllib

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

def publisher_revision(root: pathlib.Path) -> str:
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
    remote = ls_refs("averagechris.srht.site")[2]
    if not remote or local != remote:
        raise SystemExit(f"publisher checkout {local} is not current main {remote or '<missing>'}")
    return local

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

def fingerprint(root: pathlib.Path, *, publisher_sha_override: str | None = None) -> tuple[dict[str, dict], dict[str, dict]]:
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
    publisher_sha = publisher_sha_override or publisher_revision(root)
    out: dict[str, dict] = {"_publisher": {"main_sha": publisher_sha}}
    refs: dict[str, dict] = {}
    def one(r: dict) -> tuple[str, dict, str, dict]:
        repo = r.get("srht_repo", r.get("name", r.get("slug")))
        _, tag, main, tags, _ = ls_refs(repo)
        artifacts = []
        if tag:
            prefix = r.get("artifact_prefix", r.get("name", r.get("slug")))
            suffixes = ["web"] if r["kind"] == "web_game" else list(PLATFORMS)
            for suffix in suffixes:
                name = f"{prefix}-{tag}-{suffix}.tar.gz"
                url = f"https://git.sr.ht/~averagechris/{repo}/refs/download/{tag}/{name}"
                if probe(url):
                    digest = checksum(url + ".sha256", name)
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
    if not project or not tag: return
    if not expected_sha: raise SystemExit("TRIGGER_SHA is required with TRIGGER_PROJECT/TRIGGER_TAG")
    repos = [{**r, "kind": "native"} for r in tomllib.loads((root / "fleet-site.toml").read_text())["repos"]]
    games = [{**g, "kind": "web_game", "pages_subdir": f"games/{g['slug']}", "name": g["slug"]} for g in tomllib.loads((root / "site-data" / "games.toml").read_text()).get("games", [])]
    entry = next((r for r in repos + games if project in (r["pages_subdir"], r["name"], r.get("srht_repo"))), None)
    repo = (entry.get("srht_repo") or entry["name"]) if entry else project
    deadline, delay = time.monotonic() + 300, 5
    while time.monotonic() < deadline:
        refs = ls_refs(repo)
        if tag in refs[0]:
            observed_sha = refs[4].get(tag, "")
            if observed_sha != expected_sha:
                raise SystemExit(f"trigger tag {project}/{tag} resolves to {observed_sha}, expected {expected_sha}")
            prefix = entry.get("artifact_prefix", entry["name"]) if entry else project
            suffixes = ["web"] if entry and entry["kind"] == "web_game" else list(PLATFORMS)
            base = f"https://git.sr.ht/~averagechris/{repo}/refs/download/{tag}/"
            ready = []
            for suffix in suffixes:
                name = f"{prefix}-{tag}-{suffix}.tar.gz"
                if probe(base + name) and checksum(base + name + ".sha256", name) is not None:
                    ready.append(name)
            if ready:
                print(f"trigger tag and artifact are visible: {project}/{tag} ({', '.join(ready)})")
                return
        print(f"waiting for {project}/{tag} and release artifact to appear...")
        time.sleep(delay); delay = min(delay * 2, 60)
    raise SystemExit(f"timed out waiting for {project}/{tag}")

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
    wait_for_trigger(root)
    with site_measure.stage("before_fingerprint"):
        current, refs = fingerprint(
            root,
            publisher_sha_override=benchmark_publisher_sha or None,
        )
    with site_measure.stage("live_state_comparison"):
        live = benchmark_live_fingerprint(current, args.benchmark_live_state) if args.benchmark_live_state else live_fingerprint(args.domain)
        comparison = classify_comparison(current, live)
    print(f"fingerprint comparison: {comparison}")
    if not args.force and comparison == "unchanged":
        print("fingerprint unchanged; no publish needed")
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
            )
        if before == after:
            if args.no_publish:
                print("would publish dist/pages.tar.gz")
                return
            # Prefer the app-provided binary to skip a second in-job flake eval/build.
            if shutil.which("publish-pages"):
                run(["publish-pages", "--domain", args.domain], cwd=root)
            else:
                run(["nix", "run", ".#publish-pages", "--", "--domain", args.domain], cwd=root)
            return
        print(f"fingerprint moved during build (attempt {attempt}); rebuilding")
        before, before_refs = after, after_refs
    raise SystemExit("fingerprint kept moving after 3 builds")

if __name__ == "__main__": main()
