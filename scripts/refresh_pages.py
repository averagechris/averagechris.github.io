#!/usr/bin/env python3
"""Race-safe refresh for the single-publisher Pages site."""

from __future__ import annotations

import argparse, concurrent.futures, json, os, pathlib, re, subprocess, sys, tempfile, time, tomllib

SEMVER = re.compile(r"^v\d+\.\d+\.\d+$")

def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, check=True, text=True, **kw)

def ls_refs(repo: str) -> tuple[list[str], str, str, dict[str, str]]:
    """Return (all semver tags, latest tag, main sha, tag->sha) for a fleet repo."""
    # git's default UA gets tarpitted by sr.ht anti-scraper defenses on
    # datacenter IPs (silent multi-minute hang); use the curl UA and retry
    # once, with a hard timeout so the job fails loudly instead of hanging.
    command = ["git", "-c", f"http.userAgent={USER_AGENT}", "ls-remote",
               f"https://git.sr.ht/~averagechris/{repo}"]
    try:
        out = subprocess.check_output(command, text=True, timeout=120)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        out = subprocess.check_output(command, text=True, timeout=120)
    tags, tag_shas, main = [], {}, ""
    for line in out.splitlines():
        sha, ref = line.split("\t", 1)
        if ref == "refs/heads/main": main = sha
        if ref.startswith("refs/tags/v") and not ref.endswith("^{}"):
            tag = ref.removeprefix("refs/tags/")
            if SEMVER.match(tag):
                tags.append((tuple(map(int, tag[1:].split("."))), tag, sha)); tag_shas[tag] = sha
    tags.sort(reverse=True)
    return ([t[1] for t in tags], tags[0][1] if tags else "", main, tag_shas)

PLATFORMS = ("aarch64-darwin", "x86_64-darwin", "aarch64-linux", "x86_64-linux")
USER_AGENT = "averagechris-fleet-pages (+https://averagechris.srht.site)"

def probe(url: str) -> bool:
    # Tri-state: only 200/404 are stable fingerprint inputs. Tarpits, 5xx,
    # empty codes, and curl failures retry once, then fail loudly rather than
    # silently flipping an artifact between present/absent.
    observed = []
    for _ in range(2):
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

def fingerprint(root: pathlib.Path) -> tuple[dict[str, dict], dict[str, dict]]:
    """Latest tag + main sha + which platform artifacts exist on the latest tag.
    Artifacts are part of the fingerprint so a late-arriving Linux build still
    triggers a republish of an already-published tag."""
    repos = tomllib.loads((root / "fleet.toml").read_text())["repos"]
    out: dict[str, dict] = {}
    refs: dict[str, dict] = {}
    def one(r: dict) -> tuple[str, dict, str, dict]:
        repo = r.get("srht_repo", r["name"])
        _, tag, main, tags = ls_refs(repo)
        artifacts = []
        if tag:
            prefix = r.get("artifact_prefix", r["name"])
            for platform in PLATFORMS:
                name = f"{prefix}-{tag}-{platform}.tar.gz"
                if probe(f"https://git.sr.ht/~averagechris/{repo}/refs/download/{tag}/{name}"):
                    artifacts.append(name)
        return r["pages_subdir"], {"tag": tag, "main_sha": main, "artifacts": sorted(artifacts)}, repo, {"tags": tags, "main_sha": main}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(one, r): r for r in repos}
        results = {futures[f]["pages_subdir"]: f.result() for f in concurrent.futures.as_completed(futures)}
    for r in repos:
        page, fp, repo, ref = results[r["pages_subdir"]]
        out[page] = fp; refs[repo] = ref
    return out, refs

def write_refs_json(root: pathlib.Path, refs: dict[str, dict]) -> pathlib.Path:
    (root / "dist").mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=root / "dist", prefix="fleet-refs-", suffix=".json", delete=False) as f:
        path = pathlib.Path(f.name)
    path.write_text(json.dumps(refs, sort_keys=True))
    return path

def live_state(domain: str) -> dict:
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
    for k, v in state.get("projects", {}).items():
        artifacts = sorted(a.get("name", "") for a in v.get("artifacts", []) if a.get("version") == v.get("tag"))
        fp[k] = {"tag": v.get("tag", ""), "main_sha": v.get("main_sha", ""), "artifacts": artifacts}
    return fp

def wait_for_trigger(root: pathlib.Path) -> None:
    project, tag = os.environ.get("TRIGGER_PROJECT"), os.environ.get("TRIGGER_TAG")
    if not project or not tag: return
    repos = tomllib.loads((root / "fleet.toml").read_text())["repos"]
    entry = next((r for r in repos if project in (r["pages_subdir"], r["name"], r.get("srht_repo"))), None)
    repo = (entry.get("srht_repo") or entry["name"]) if entry else project
    deadline, delay = time.time() + 300, 5
    while time.time() < deadline:
        if tag in ls_refs(repo)[0]:
            print(f"trigger tag {project}/{tag} is visible")
            return
        print(f"waiting for {project}/{tag} to appear...")
        time.sleep(delay); delay = min(delay * 2, 60)
    raise SystemExit(f"timed out waiting for {project}/{tag}")

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="averagechris.srht.site")
    ap.add_argument("--no-publish", action="store_true")
    args = ap.parse_args()
    root = pathlib.Path(__file__).resolve().parent.parent
    wait_for_trigger(root)
    current, refs = fingerprint(root)
    if current == live_fingerprint(args.domain):
        print("fingerprint unchanged; no publish needed")
        return
    before, before_refs = current, refs
    for attempt in range(1, 4):
        # Hand build_pages the exact refs captured by this attempt's before pass.
        refs_path = write_refs_json(root, before_refs)
        env = os.environ.copy(); env["FLEET_REFS_JSON"] = str(refs_path)
        run([sys.executable, "scripts/build_pages.py", "--domain", args.domain], cwd=root, env=env)
        after, after_refs = fingerprint(root)
        if before == after:
            if args.no_publish:
                print("would publish dist/pages.tar.gz")
                return
            run(["nix", "run", ".#publish-pages", "--", "--domain", args.domain], cwd=root)
            return
        print(f"fingerprint moved during build (attempt {attempt}); rebuilding")
        before, before_refs = after, after_refs
    raise SystemExit("fingerprint kept moving after 3 builds")

if __name__ == "__main__": main()
