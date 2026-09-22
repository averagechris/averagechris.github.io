#!/usr/bin/env python3
"""Add a project entry to site-data/projects.toml.

Usage:
    add_project.py <path> --description "..." [--name NAME] [--repo URL] [--unlisted]

<path> is the subdirectory under https://averagechris.github.io/ where the
project publishes its downloads page. Defaults: name = path, repo =
https://git.sr.ht/~averagechris/<path>.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import tomllib


RESERVED_SITE_PATHS = {
    "404",
    "assets",
    "fleet",
    "keys",
    "notes",
    "now",
    "state",
    "state.json",
    "tools",
    "uses",
}


def toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="subdirectory under the site root, e.g. linear-cli")
    parser.add_argument("--description", required=True)
    parser.add_argument("--name", default=None, help="display name (default: same as path)")
    parser.add_argument("--repo", default=None, help="source repo URL (default: git.sr.ht/~averagechris/<path>)")
    parser.add_argument("--unlisted", action="store_true", help="mirror the subdirectory but do not show a card")
    parser.add_argument("--no-downloads", action="store_true", help="project has no downloads page; link source only")
    parser.add_argument("--tier", choices=["featured", "more"], default="featured", help="featured card or compact 'more projects' list")
    args = parser.parse_args()

    path = args.path.strip("/")
    if not path or "/" in path:
        raise SystemExit("error: path must be a single top-level subdirectory name")
    if path in RESERVED_SITE_PATHS:
        raise SystemExit(f"error: path {path!r} is reserved by the root site")

    repo_root = pathlib.Path(__file__).resolve().parent.parent
    config_path = repo_root / "site-data" / "projects.toml"
    config = tomllib.loads(config_path.read_text())

    if any(project["path"] == path for project in config.get("projects", [])):
        print(f"{path} is already in site-data/projects.toml; nothing to do")
        sys.exit(0)

    lines = [
        "",
        "[[projects]]",
        f"path = {toml_string(path)}",
        f"name = {toml_string(args.name or path)}",
        f"description = {toml_string(args.description)}",
        f"repo = {toml_string(args.repo or f'https://git.sr.ht/~averagechris/{path}')}",
    ]
    if args.unlisted:
        lines.append("listed = false")
    if args.no_downloads:
        lines.append("downloads = false")
    if args.tier != "featured":
        lines.append(f"tier = {toml_string(args.tier)}")

    with config_path.open("a") as handle:
        handle.write("\n".join(lines) + "\n")

    # Validate the result still parses.
    tomllib.loads(config_path.read_text())
    print(f"added {path} to site-data/projects.toml")


if __name__ == "__main__":
    main()
