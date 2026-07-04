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

# Rosé Pine Dawn (light) / Rosé Pine Moon (dark). SourceHut Pages' CSP allows
# inline styles/scripts but blocks external stylesheets, fonts, and scripts,
# so everything ships inline and fonts are system stacks.
STYLE = """\
  /* Rosé Pine Dawn */
  :root, :root[data-theme="dawn"] {
    --base: #faf4ed;
    --surface: #fffaf3;
    --overlay: #f2e9e1;
    --hl-med: #dfdad9;
    --muted: #9893a5;
    --subtle: #797593;
    --text: #575279;
    --love: #b4637a;
    --rose: #d7827e;
    --pine: #286983;
    --foam: #56949f;
  }
  /* Rosé Pine Moon */
  :root[data-theme="moon"] {
    --base: #232136;
    --surface: #2a273f;
    --overlay: #393552;
    --hl-med: #44415a;
    --muted: #6e6a86;
    --subtle: #908caa;
    --text: #e0def4;
    --love: #eb6f92;
    --rose: #ea9a97;
    --pine: #3e8fb0;
    --foam: #9ccfd8;
  }
  * { box-sizing: border-box; }
  body {
    background: var(--base);
    color: var(--text);
    font-family: Charter, Georgia, "Iowan Old Style", serif;
    line-height: 1.65;
    max-width: 920px;
    margin: 0 auto;
    padding: 3rem 1.25rem 4rem;
    transition: background 0.25s ease, color 0.25s ease;
  }
  a { color: var(--pine); text-decoration-color: color-mix(in srgb, var(--pine) 40%, transparent); }
  a:hover { color: var(--rose); }
  .masthead { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; }
  .identity { display: flex; align-items: center; gap: 1.15rem; }
  .portrait {
    width: 88px; height: 88px; border-radius: 50%; object-fit: cover;
    border: 2px solid var(--hl-med);
    box-shadow: 2px 2px 0 var(--hl-med);
    flex-shrink: 0;
  }
  h1 { font-size: 2.4rem; margin: 0; font-weight: 700; letter-spacing: -0.01em; }
  h1 small { color: var(--muted); font-weight: 400; font-size: 1.2rem; font-style: italic; }
  .tagline { color: var(--subtle); font-style: italic; margin: 0.25rem 0 0; }
  .theme-toggle {
    background: var(--surface); border: 1px solid var(--hl-med); color: var(--subtle);
    border-radius: 999px; padding: 0.3rem 0.8rem; cursor: pointer;
    font-family: inherit; font-size: 0.85rem; font-style: italic;
    transition: border-color 0.15s ease;
    flex-shrink: 0; margin-top: 0.5rem;
  }
  .theme-toggle:hover { border-color: var(--rose); color: var(--text); }
  .profile-links { display: flex; gap: 1.25rem; margin: 1rem 0 0; font-size: 0.95rem; }
  .about { max-width: 62ch; margin-top: 1.75rem; font-size: 1.08rem; }
  .divider { border: none; border-top: 1px solid var(--hl-med); margin: 2.5rem 0; position: relative; overflow: visible; }
  .divider::after {
    content: "\\2766"; position: absolute; top: -0.85em; left: 50%; transform: translateX(-50%);
    background: var(--base); padding: 0 0.75rem; color: var(--muted); font-size: 1rem;
    line-height: 1.7; transition: background 0.25s ease;
  }
  h2 { font-size: 1.5rem; margin: 0 0 1.25rem; font-weight: 700; }
  .projects {
    display: grid; gap: 1.1rem;
    grid-template-columns: repeat(auto-fit, minmax(270px, 1fr));
    padding: 0;
  }
  .project {
    background: var(--surface);
    border: 1px solid var(--hl-med);
    border-radius: 4px;
    padding: 1.3rem 1.4rem;
    box-shadow: 2px 2px 0 var(--hl-med);
    transition: box-shadow 0.15s ease, transform 0.15s ease, background 0.25s ease;
  }
  .project:hover { transform: translate(-1px, -1px); box-shadow: 4px 4px 0 var(--hl-med); }
  .project h3 {
    margin: 0 0 0.5rem; font-size: 1.15rem;
    font-family: ui-monospace, Menlo, monospace; font-weight: 600;
  }
  .version {
    float: right; font-family: ui-monospace, Menlo, monospace;
    font-size: 0.72rem; background: var(--overlay); color: var(--foam);
    padding: 0.12rem 0.55rem; border-radius: 3px; margin-top: 0.25rem; margin-left: 0.5rem;
  }
  .project p { margin: 0 0 0.9rem; font-size: 0.95rem; color: var(--subtle); }
  .project-links { display: flex; gap: 1.1rem; font-size: 0.9rem; font-family: ui-monospace, Menlo, monospace; }
  .project-links a.primary-link { font-weight: 700; }
  .pending { color: var(--muted); font-style: italic; }
  .more-projects { padding-left: 1.4rem; }
  .more-projects li { margin-bottom: 0.55rem; color: var(--subtle); }
  .more-projects li::marker { content: "\\273F  "; color: var(--love); }
  .more-projects a { font-family: ui-monospace, Menlo, monospace; font-size: 0.92rem; }
  footer { color: var(--muted); font-size: 0.88rem; margin-top: 3.5rem; font-style: italic; text-align: center; }
"""

# Runs before first paint to avoid a theme flash.
HEAD_SCRIPT = """\
  (function () {
    var stored = null;
    try { stored = localStorage.getItem("theme"); } catch (e) {}
    var system = matchMedia("(prefers-color-scheme: dark)").matches ? "moon" : "dawn";
    document.documentElement.dataset.theme = stored || system;
  })();
"""

BODY_SCRIPT = """\
  document.getElementById("theme-toggle").addEventListener("click", function () {
    var next = document.documentElement.dataset.theme === "moon" ? "dawn" : "moon";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) {}
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function (event) {
    var stored = null;
    try { stored = localStorage.getItem("theme"); } catch (e) {}
    if (!stored) document.documentElement.dataset.theme = event.matches ? "moon" : "dawn";
  });

  // Latest-version badges from each project's same-origin manifest.json.
  // Best effort: any failure just means no badge.
  function parseVersion(name) {
    var m = /v(\\d+)\\.(\\d+)\\.(\\d+)/.exec(name);
    return m ? [+m[1], +m[2], +m[3]] : null;
  }
  function newer(a, b) {
    for (var i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] > b[i];
    return false;
  }
  document.querySelectorAll(".project[data-project]").forEach(function (card) {
    fetch("/" + card.dataset.project + "/manifest.json")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (manifest) {
        if (!manifest || !Array.isArray(manifest.artifacts)) return;
        var best = null;
        manifest.artifacts.forEach(function (artifact) {
          var v = parseVersion(artifact.name || "");
          if (v && (!best || newer(v, best))) best = v;
        });
        if (!best) return;
        var badge = document.createElement("span");
        badge.className = "version";
        badge.textContent = "v" + best.join(".");
        card.insertBefore(badge, card.firstElementChild);
      })
      .catch(function () {});
  });
"""


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
        data_attr = ""
        if has_downloads:
            downloads_url = html.escape(f"{base_url}/{project['path']}/")
            if published.get(project["path"]) is False:
                links.append('<span class="pending">no release yet</span>')
            else:
                links.append(f'<a class="primary-link" href="{downloads_url}">downloads</a>')
                data_attr = f' data-project="{html.escape(project["path"])}"'
        links.append(f'<a href="{repo_url}">source</a>')
        cards.append(
            "\n".join(
                (
                    f'    <article class="project"{data_attr}>',
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
            "\n  <hr class=\"divider\">\n\n  <h2>More projects</h2>\n  <ul class=\"more-projects\">\n"
            + "\n".join(more_items)
            + "\n  </ul>\n"
        )

    profile_links = " ".join(
        f'<a href="{html.escape(link["url"])}">{html.escape(link["label"])}</a>'
        for link in site.get("links", [])
    )
    about_paragraphs = "\n".join(
        f'  <p class="about">{html.escape(paragraph.strip())}</p>'
        for paragraph in site["about"].split("\n\n")
        if paragraph.strip()
    )
    tagline = ""
    if site.get("tagline"):
        tagline = f'\n        <p class="tagline">{html.escape(site["tagline"])}</p>'
    portrait = ""
    if site.get("portrait"):
        portrait_src = html.escape(site["portrait"])
        portrait_alt = html.escape(site["name"])
        portrait = (
            f'\n      <img class="portrait" src="{portrait_src}" alt="{portrait_alt}"'
            ' width="88" height="88">'
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(site["title"])}</title>
  <script>
{HEAD_SCRIPT}  </script>
  <style>
{STYLE}  </style>
</head>
<body>
  <header>
    <div class="masthead">
      <div class="identity">{portrait}
      <div>
        <h1>{html.escape(site["name"])} <small>{html.escape(site["title"])}</small></h1>{tagline}
      </div>
      </div>
      <button class="theme-toggle" id="theme-toggle" aria-label="toggle color theme">dawn &frasl; moon</button>
    </div>
    <nav class="profile-links">{profile_links}</nav>
  </header>

{about_paragraphs}

  <hr class="divider">

  <h2>Projects</h2>
  <section class="projects">
{chr(10).join(cards)}
  </section>
{more_section}
  <footer>
    <p>Each project page hosts prebuilt binaries with sha256 checksums.<br>
    Source for this page: <a href="https://git.sr.ht/~averagechris/averagechris.srht.site">averagechris.srht.site</a>.</p>
  </footer>
  <script>
{BODY_SCRIPT}  </script>
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

    assets_dir = repo / "assets"
    if assets_dir.is_dir():
        for asset in sorted(assets_dir.iterdir()):
            if asset.is_file():
                shutil.copy2(asset, site_dir / asset.name)

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
