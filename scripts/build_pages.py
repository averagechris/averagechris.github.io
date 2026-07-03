#!/usr/bin/env python3
"""Build the averagechris.srht.site root site tarball.

SourceHut Pages replaces the ENTIRE site on a root publish, so this script:

1. Mirrors every project subdirectory listed in projects.toml from the live
   site (index.html, manifest.json, and every file linked from the page).
2. Generates a fresh index.html at the site root.
3. Packs everything into a gzipped tarball ready for `hut pages publish`.

Usage:
    build_pages.py [--domain DOMAIN] [--skip-mirror] [--out DIR]
"""

from __future__ import annotations

import argparse
import html
import pathlib
import re
import shutil
import sys
import tarfile
import tomllib
import urllib.error
import urllib.parse
import urllib.request

HREF_RE = re.compile(r'href="([^"]+)"')
EXTRA_SUBTREE_FILES = ("manifest.json",)


def fail(message: str) -> "sys.NoReturn":
    raise SystemExit(f"error: {message}")


def fetch(url: str) -> bytes | None:
    """Fetch a URL, returning None on 404 and failing hard on anything else."""
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        fail(f"fetching {url}: HTTP {error.code}")
    except urllib.error.URLError as error:
        fail(f"fetching {url}: {error}")


def subtree_files_from_page(page_html: str) -> set[str]:
    """Extract relative file paths within a project subtree from its index page."""
    files: set[str] = set()
    for href in HREF_RE.findall(page_html):
        parsed = urllib.parse.urlparse(href)
        if parsed.scheme or parsed.netloc or href.startswith(("/", "#")):
            continue
        candidate = urllib.parse.unquote(parsed.path)
        normalized = pathlib.PurePosixPath(candidate)
        if not candidate or candidate.endswith("/") or ".." in normalized.parts:
            continue
        files.add(str(normalized))
    return files


def mirror_project(base_url: str, path: str, site_dir: pathlib.Path) -> bool:
    """Mirror one project subtree from the live site. Returns True if mirrored."""
    project_url = f"{base_url}/{path}"
    index_bytes = fetch(f"{project_url}/index.html") or fetch(f"{project_url}/")
    if index_bytes is None:
        print(f"  {path}: not published yet, skipping mirror")
        return False

    project_dir = site_dir / path
    project_dir.mkdir(parents=True)
    (project_dir / "index.html").write_bytes(index_bytes)

    files = subtree_files_from_page(index_bytes.decode("utf-8", errors="replace"))
    files.update(EXTRA_SUBTREE_FILES)
    files.discard("index.html")

    fetched = 0
    for relative in sorted(files):
        content = fetch(f"{project_url}/{urllib.parse.quote(relative)}")
        if content is None:
            if relative in EXTRA_SUBTREE_FILES:
                continue
            fail(f"{path}: linked file {relative} returned 404; refusing to publish an incomplete mirror")
        destination = project_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        fetched += 1

    print(f"  {path}: mirrored index.html + {fetched} files")
    return True


def render_index(config: dict, base_url: str, published: dict[str, bool]) -> str:
    site = config["site"]
    cards: list[str] = []
    more_items: list[str] = []
    for project in config["projects"]:
        if not project.get("listed", True):
            continue
        name = html.escape(project["name"])
        description = html.escape(project["description"])
        repo_url = html.escape(project["repo"])
        has_downloads = project.get("downloads", True)

        if project.get("tier", "featured") == "more":
            more_items.append(
                f'    <li><a href="{repo_url}">{name}</a> &mdash; {description}</li>'
            )
            continue

        links = []
        if has_downloads:
            downloads_url = html.escape(f"{base_url}/{project['path']}/")
            if published.get(project["path"]) is False:
                links.append('<span class="pending">no release yet</span>')
            else:
                links.append(f'<a class="primary-link" href="{downloads_url}">downloads</a>')
        links.append(f'<a href="{repo_url}">source</a>')
        cards.append(
            "\n".join(
                (
                    '    <article class="project">',
                    f"      <h3>{name}</h3>",
                    f"      <p>{description}</p>",
                    f'      <p class="project-links">{" ".join(links)}</p>',
                    "    </article>",
                )
            )
        )

    more_section = ""
    if more_items:
        more_section = (
            "\n  <h2>More projects</h2>\n  <ul class=\"more-projects\">\n"
            + "\n".join(more_items)
            + "\n  </ul>\n"
        )

    profile_links = " ".join(
        f'<a href="{html.escape(link["url"])}">{html.escape(link["label"])}</a>'
        for link in site.get("links", [])
    )
    about_paragraphs = "\n".join(
        f"  <p>{html.escape(paragraph.strip())}</p>"
        for paragraph in site["about"].split("\n\n")
        if paragraph.strip()
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(site["title"])}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 920px; margin: 3rem auto; padding: 0 1rem; line-height: 1.5; }}
    header h1 {{ margin-bottom: 0.25rem; }}
    .profile-links {{ display: flex; gap: 1rem; margin: 0.5rem 0 0; }}
    .projects {{ display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); padding: 0; }}
    .project {{ background: white; border: 1px solid #e5e5e5; border-radius: 12px; padding: 1rem; }}
    .project h3 {{ margin: 0 0 0.5rem; }}
    .project p {{ margin: 0 0 0.75rem; }}
    .project-links {{ display: flex; flex-wrap: wrap; gap: 0.75rem; }}
    .primary-link {{ font-weight: 700; }}
    .pending {{ color: #777; }}
    .more-projects {{ padding-left: 1.25rem; }}
    .more-projects li {{ margin-bottom: 0.5rem; }}
    footer {{ color: #555; font-size: 0.85rem; margin-top: 3rem; }}
  </style>
</head>
<body>
  <header>
    <h1>{html.escape(site["name"])} <small>{html.escape(site["title"])}</small></h1>
    <nav class="profile-links">{profile_links}</nav>
  </header>

{about_paragraphs}

  <h2>Projects</h2>
  <section class="projects">
{chr(10).join(cards)}
  </section>
{more_section}
  <footer>
    <p>Each project page hosts prebuilt binaries with sha256 checksums.
    Source for this page: <a href="https://git.sr.ht/~averagechris/averagechris.srht.site">averagechris.srht.site</a>.</p>
  </footer>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", default=None, help="override site domain")
    parser.add_argument(
        "--skip-mirror",
        action="store_true",
        help="skip mirroring live subdirectories (LOCAL PREVIEW ONLY; publishing this tarball would wipe project pages)",
    )
    parser.add_argument("--out", default="dist", help="output directory (default: dist)")
    args = parser.parse_args()

    repo = pathlib.Path(__file__).resolve().parent.parent
    config = tomllib.loads((repo / "projects.toml").read_text())
    domain = args.domain or config["site"]["domain"]
    base_url = f"https://{domain}"

    out_dir = repo / args.out
    site_dir = out_dir / "site"
    if site_dir.exists():
        shutil.rmtree(site_dir)
    site_dir.mkdir(parents=True)

    published: dict[str, bool] = {}
    if args.skip_mirror:
        print("skipping mirror of live site (preview only)")
    else:
        print(f"mirroring live site from {base_url}")
        for project in config["projects"]:
            if not project.get("downloads", True):
                continue
            published[project["path"]] = mirror_project(base_url, project["path"], site_dir)

    (site_dir / "index.html").write_text(render_index(config, base_url, published))

    tarball = out_dir / "pages.tar.gz"
    with tarfile.open(tarball, "w:gz") as archive:
        for path in sorted(site_dir.rglob("*")):
            if path.is_file():
                archive.add(path, arcname=str(path.relative_to(site_dir)))

    marker = out_dir / "PREVIEW_ONLY"
    if args.skip_mirror:
        marker.write_text("built with --skip-mirror; publishing would wipe project pages\n")
    else:
        marker.unlink(missing_ok=True)

    print(f"site: {site_dir}")
    print(f"tarball: {tarball}")
    if args.skip_mirror:
        print("NOTE: built without mirroring; do NOT publish this tarball")


if __name__ == "__main__":
    main()
