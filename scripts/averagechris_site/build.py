#!/usr/bin/env python3
"""Build the averagechris.github.io root Pages artifact.

Single-publisher model: acquires every fleet project's downloads subdirectory
from durable sources (annotated git tags, tag artifacts, and docs pages fetched
from each repo), materializes canonical site data for Zola, invokes Zola, writes
SourceHut siteconfig.json, records input pins in state.json, and packs dist/site
into dist/pages.tar.gz. Root publishes replace the entire site;
site-data/projects.toml and site-data/games.toml are the registries of routes.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import tarfile
import tomllib

import site_measure

from averagechris_site.data import load_site_data
from averagechris_site.fleet import acquire_fleet_data, load_fleet_json, write_fleet_json
from averagechris_site.paths import repo_root
from averagechris_site.zola import render_zola_site

def fail(message: str) -> "sys.NoReturn":
    raise SystemExit(f"error: {message}")


def reject_obsolete_renderer_args(argv: list[str]) -> None:
    """Fail loudly for the retired renderer switch instead of accepting it."""
    for index, arg in enumerate(argv):
        if arg == "--renderer":
            value = argv[index + 1] if index + 1 < len(argv) else None
            suffix = f" {value}" if value else ""
            fail(f"--renderer{suffix} is obsolete; Zola is the only renderer")
        if arg.startswith("--renderer="):
            fail(f"{arg} is obsolete; Zola is the only renderer")


def load_release_dates(repo: pathlib.Path) -> dict[str, str]:
    path = repo / "release-dates.toml"
    if not path.exists():
        return {}
    return dict(tomllib.loads(path.read_text()).get("dates", {}))


def update_release_dates(repo: pathlib.Path, _meta: dict[str, dict]) -> dict[str, str]:
    # The site projection deliberately excludes operational local checkout
    # paths. Release dates remain durable, explicitly refreshed website state.
    return load_release_dates(repo)


def assemble_site(repo: pathlib.Path, out_dir: pathlib.Path, site_dir: pathlib.Path, state: dict) -> None:
    (site_dir / "state.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    assets_dir = repo / "assets"
    if assets_dir.is_dir():
        for asset in sorted(assets_dir.iterdir()):
            if asset.is_file():
                shutil.copy2(asset, site_dir / asset.name)
    out_dir.mkdir(exist_ok=True)
    (out_dir / "siteconfig.json").write_text(json.dumps({"notFound": "404.html"}) + "\n")
    tarball = out_dir / "pages.tar.gz"
    with tarfile.open(tarball, "w:gz") as archive:
        for path in sorted(site_dir.rglob("*")):
            if path.is_file():
                archive.add(path, arcname=str(path.relative_to(site_dir)))
    (out_dir / "PREVIEW_ONLY").unlink(missing_ok=True)
    print(f"site: {site_dir}")
    print(f"tarball: {tarball}")


def main() -> None:
    reject_obsolete_renderer_args(sys.argv[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", default=None)
    parser.add_argument("--out", default="dist")
    args = parser.parse_args()
    repo = repo_root()
    loaded = load_site_data(repo)
    config = {"site": dict(loaded.site), "projects": loaded.projects, "games": loaded.games, "pages": loaded.pages, "notes": loaded.notes, "wiki": loaded.wiki}
    site = config["site"]
    domain = args.domain or site["domain"]
    base_url = f"https://{domain}"

    out_dir = repo / args.out
    site_dir = out_dir / "site"
    if site_dir.exists():
        shutil.rmtree(site_dir)
    site_dir.mkdir(parents=True)

    print("building fleet project pages from sr.ht tags and repo files")
    with site_measure.stage("acquisition"):
        fleet_json = acquire_fleet_data(repo, config, site_dir, base_url)
    fleet_json["release_dates"] = update_release_dates(repo, fleet_json["meta"])
    fleet_json_path = write_fleet_json(repo, fleet_json)
    fleet_json = load_fleet_json(fleet_json_path)
    render_zola_site(repo, config, site_dir, base_url, fleet_json)
    assemble_site(repo, out_dir, site_dir, fleet_json["state"])


if __name__ == "__main__":
    main()
