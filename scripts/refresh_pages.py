#!/usr/bin/env python3
"""Race-safe refresh for the single-publisher Pages site."""

from __future__ import annotations

import argparse, json, os, pathlib, re, subprocess, sys, time, tomllib, urllib.error, urllib.request

SEMVER = re.compile(r"^v\d+\.\d+\.\d+$")

def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, check=True, text=True, **kw)

def ls_refs(repo: str) -> tuple[list[str], str, str]:
    """Return (all semver tags, latest tag, main sha) for a fleet repo."""
    out = subprocess.check_output(["git", "ls-remote", f"https://git.sr.ht/~averagechris/{repo}"], text=True)
    tags, main = [], ""
    for line in out.splitlines():
        sha, ref = line.split("\t", 1)
        if ref == "refs/heads/main": main = sha
        if ref.startswith("refs/tags/v") and not ref.endswith("^{}"):
            tag = ref.removeprefix("refs/tags/")
            if SEMVER.match(tag): tags.append((tuple(map(int, tag[1:].split("."))), tag, sha))
    tags.sort(reverse=True)
    return ([t[1] for t in tags], tags[0][1] if tags else "", main)

def ls(repo: str) -> tuple[str, str]:
    _, latest, main = ls_refs(repo)
    return (latest, main)

def fingerprint(root: pathlib.Path) -> dict[str, dict[str, str]]:
    fleet = tomllib.loads((root / "fleet.toml").read_text())["repos"]
    return {r["pages_subdir"]: {"tag": (t := ls(r.get("srht_repo", r["name"])))[0], "main_sha": t[1]} for r in fleet}

def live_state(domain: str) -> dict:
    try:
        with urllib.request.urlopen(f"https://{domain}/state.json", timeout=30) as r:
            return json.load(r)
    except Exception:
        return {"projects": {}}

def live_fingerprint(domain: str) -> dict[str, dict[str, str]]:
    state = live_state(domain)
    return {k: {"tag": v.get("tag", ""), "main_sha": v.get("main_sha", "")} for k, v in state.get("projects", {}).items()}

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
    current = fingerprint(root)
    if current == live_fingerprint(args.domain):
        print("fingerprint unchanged; no publish needed")
        return
    for attempt in range(1, 4):
        before = fingerprint(root)
        run([sys.executable, "scripts/build_pages.py", "--domain", args.domain], cwd=root)
        after = fingerprint(root)
        if before == after:
            if args.no_publish:
                print("would publish dist/pages.tar.gz")
                return
            run(["nix", "run", ".#publish-pages", "--", "--domain", args.domain], cwd=root)
            return
        print(f"fingerprint moved during build (attempt {attempt}); rebuilding")
    raise SystemExit("fingerprint kept moving after 3 builds")

if __name__ == "__main__": main()
