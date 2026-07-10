#!/usr/bin/env python3
"""Build the averagechris.srht.site root Pages tarball.

Single-publisher model: renders every fleet project's downloads subdirectory
from durable sources (annotated git tags, tag artifacts, and docs pages fetched
from each repo), generates the homepage plus root-owned pages (site-data
markdown, /tools/, 404.html), writes SourceHut siteconfig.json, records input
pins in state.json, and packs dist/site into dist/pages.tar.gz. Root publishes
replace the entire site; site-data/projects.toml is the registry of subdirectories.
"""

from __future__ import annotations

import argparse
import html
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib

import markdown

from site_data import Page, load_site_data
from fleet_data import (
    DOC_PAGES,
    acquire_fleet_data,
    load_fleet_json,
    write_fleet_json,
)

PROJECT_INFO_PAGES = DOC_PAGES
RELEASE_DATES_HEADER = """# Cache of release tag dates, updated automatically by build-pages when
# local fleet repos are available. Safe to commit; CI reads it as-is.
[dates]
"""

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
  .profile-links { display: flex; gap: 1.25rem; margin: 1rem 0 0; font-size: 0.95rem; flex-wrap: wrap; }
  .about { max-width: 62ch; margin-top: 1.75rem; font-size: 1.08rem; }
  .muted { color: var(--muted); }
  .mono { font-family: ui-monospace, Menlo, monospace; }
  .divider { border: none; border-top: 1px solid var(--hl-med); margin: 2.5rem 0; position: relative; overflow: visible; }
  .divider::after {
    content: "\\2766"; position: absolute; top: -0.85em; left: 50%; transform: translateX(-50%);
    background: var(--base); padding: 0 0.75rem; color: var(--muted); font-size: 1rem;
    line-height: 1.7; transition: background 0.25s ease;
  }
  h2 { font-size: 1.5rem; margin: 0 0 1.25rem; font-weight: 700; }
  h3 { margin-top: 1.6rem; }
  .projects { display: grid; gap: 1.1rem; grid-template-columns: repeat(auto-fit, minmax(270px, 1fr)); padding: 0; }
  .project {
    background: var(--surface);
    border: 1px solid var(--hl-med);
    border-radius: 4px;
    padding: 1.3rem 1.4rem;
    box-shadow: 2px 2px 0 var(--hl-med);
    transition: box-shadow 0.15s ease, transform 0.15s ease, background 0.25s ease;
  }
  .project:hover { transform: translate(-1px, -1px); box-shadow: 4px 4px 0 var(--hl-med); }
  .project h3 { margin: 0 0 0.5rem; font-size: 1.15rem; font-family: ui-monospace, Menlo, monospace; font-weight: 600; }
  .version {
    float: right; font-family: ui-monospace, Menlo, monospace;
    font-size: 0.72rem; background: var(--overlay); color: var(--foam);
    padding: 0.12rem 0.55rem; border-radius: 3px; margin-top: 0.25rem; margin-left: 0.5rem;
  }
  .project p { margin: 0 0 0.9rem; font-size: 0.95rem; color: var(--subtle); }
  .project-links, .page-links { display: flex; gap: 1.1rem; font-size: 0.9rem; font-family: ui-monospace, Menlo, monospace; flex-wrap: wrap; }
  .project-links a.primary-link { font-weight: 700; }
  .pending { color: var(--muted); font-style: italic; }
  .more-projects { padding-left: 1.4rem; }
  .more-projects li { margin-bottom: 0.55rem; color: var(--subtle); }
  .more-projects li::marker { content: "\\273F  "; color: var(--love); }
  .more-projects a { font-family: ui-monospace, Menlo, monospace; font-size: 0.92rem; }
  details.install { margin-top: 0.8rem; }
  details.install summary { cursor: pointer; color: var(--pine); font-family: ui-monospace, Menlo, monospace; font-size: 0.88rem; }
  .code-line, pre { background: var(--overlay); border: 1px solid var(--hl-med); border-radius: 4px; overflow-x: auto; }
  .code-line { display: flex; gap: 0.5rem; align-items: start; margin: 0.45rem 0; padding: 0.45rem; }
  .code-line code, pre code { font-family: ui-monospace, Menlo, monospace; font-size: 0.78rem; white-space: pre; }
  .copy { background: var(--surface); border: 1px solid var(--hl-med); color: var(--subtle); border-radius: 3px; font-size: 0.72rem; cursor: pointer; }
  .copy:hover { color: var(--text); border-color: var(--rose); }
  .content { max-width: 70ch; }
  .content pre { padding: 0.8rem; }
  .content code { background: var(--overlay); border-radius: 3px; padding: 0.05rem 0.2rem; }
  .content pre code { padding: 0; background: transparent; }
  .content h2 { margin-top: 2rem; border-bottom: 1px solid var(--hl-med); padding-bottom: 0.25rem; }
  .content h3 { color: var(--subtle); }
  .content li { margin: 0.35rem 0; }
  .tool { border-top: 1px solid var(--hl-med); padding-top: 1.2rem; margin-top: 1.2rem; }
  .tool h2 { margin-bottom: 0.3rem; }
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
  document.addEventListener("click", function (event) {
    var button = event.target.closest("button.copy");
    if (!button) return;
    var text = button.dataset.copy || "";
    function done() {
      var old = button.textContent;
      button.textContent = "copied";
      setTimeout(function () { button.textContent = old; }, 1200);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(function () {});
    }
  });
"""

def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def fail(message: str) -> "sys.NoReturn":
    raise SystemExit(f"error: {message}")


def render_download_page(site: dict, project: dict, base_url: str, info: dict) -> str:
    def build_card(a: dict) -> str:
        rel = f"downloads/{a['name']}" if a.get("hosted") else a["url"]
        chk = f"downloads/{a['name']}.sha256" if a.get("hosted") else a["sha_url"]
        return f"""
          <article class="build"><h4>{esc(a['label'])}</h4><p class="filename"><code>{esc(a['name'])}</code></p>
          <p class="download-links"><a class="primary-link" href="{esc(rel)}">Download tarball</a><a href="{esc(chk)}">Checksum</a></p>
          <details><summary>SHA-256</summary><pre><code>{esc(a['sha256'])}  {esc(a['name'])}</code></pre></details></article>"""
    releases = []
    for tag in info["versions"]:
        arts = [a for a in info["artifacts"] if a["version"] == tag]
        if not arts:
            continue
        body = "".join(build_card(a) for a in arts)
        klass = "release latest" if tag == info["tag"] else "release"
        label = "Latest release" if tag == info["tag"] else "Release"
        releases.append(f"""<section class="{klass}"><div class="release-heading"><div><p class="eyebrow">{label}</p><h3>{esc(tag)}</h3></div><span class="build-count">{len(arts)} builds</span></div><div class="build-grid">{body}</div></section>""")
    page_links = "".join(f'<a class="page-link" href="{esc(p)}">{esc(p.removesuffix(".html"))}</a>' for p in info["docs"] if p in DOC_PAGES)
    whats = md_to_html(info["changelog"].get(info["tag"], "No changelog entry found."))
    prev = "".join(f'<details><summary>{esc(t)}</summary>{md_to_html(info["changelog"].get(t, ""))}</details>' for t in info["versions"][1:3] if info["changelog"].get(t))
    latest_art = next((a for a in info["artifacts"] if a["version"] == info["tag"]), None)
    install = ""
    if latest_art:
        commands = []
        stem = latest_art["name"].removesuffix(".tar.gz")
        for binary in project.get("binaries", [project["name"]]):
            commands.append(f"install -m 0755 {stem}/{binary} ~/.local/bin/{binary}")
        install = f"curl -LO {base_url}/{project['pages_subdir']}/downloads/{latest_art['name']}\nsha256sum -c {latest_art['name']}.sha256\ntar -xzf {latest_art['name']}\n" + "\n".join(commands)
    body = f"""<main class="content"><div class="masthead"><div><h1>{esc(project['name'])} downloads</h1><p class="home-link"><a href="/">~averagechris</a> / {esc(project['pages_subdir'])}</p></div><button class="theme-toggle" id="theme-toggle" aria-label="toggle color theme">dawn &frasl; moon</button></div>
    <p>{esc(project.get('description',''))}</p><p class="page-links">{page_links}</p><p><a href="https://git.sr.ht/~averagechris/{esc(project['srht_repo'])}">Source repository</a></p>
    <h2>What's new in {esc(info['tag'])}</h2>{whats}{prev}<h2>Binary downloads</h2>{''.join(releases)}<h2>Manual install</h2><pre><code>{esc(install)}</code></pre></main>"""
    return page_chrome(f"{project['name']} downloads", project.get("description", ""), f"{base_url}/{project['pages_subdir']}/", site, body)



def render_fleet_download_pages(config: dict, site_dir: pathlib.Path, base_url: str, fleet_json: dict) -> None:
    for project in config["projects"]:
        path = project["path"]
        info = fleet_json.get("projects", {}).get(path)
        if not info:
            continue
        f = info["project"]
        project_dir = site_dir / path
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "index.html").write_text(render_download_page(config["site"], f, base_url, info))


def fleet_render_inputs(fleet_json: dict) -> tuple[dict[str, bool], dict[str, dict], dict[str, set[str]], dict[str, str]]:
    return (
        dict(fleet_json.get("published", {})),
        dict(fleet_json.get("meta", {})),
        {k: set(v) for k, v in fleet_json.get("project_pages", {}).items()},
        dict(fleet_json.get("release_dates", {})),
    )


def site_path(path: str) -> str:
    return "/" + path.lstrip("/")


def project_info_links(project: dict, pages: dict[str, set[str]]) -> list[str]:
    path = project["path"]
    return [
        f'<a href="/{esc(path)}/{esc(page)}">{esc(page.removesuffix(".html"))}</a>'
        for page in PROJECT_INFO_PAGES
        if page in pages.get(path, set())
    ]



def load_release_dates(repo: pathlib.Path) -> dict[str, str]:
    path = repo / "release-dates.toml"
    if not path.exists():
        return {}
    return dict(tomllib.loads(path.read_text()).get("dates", {}))


def fleet_by_subdir(repo: pathlib.Path) -> dict[str, str]:
    path = repo / "fleet.toml"
    if not path.exists():
        return {}
    return {
        r["pages_subdir"]: r["local"]
        for r in tomllib.loads(path.read_text()).get("repos", [])
        if r.get("pages_subdir") and r.get("local")
    }


def update_release_dates(repo: pathlib.Path, meta: dict[str, dict]) -> dict[str, str]:
    dates = load_release_dates(repo)
    fleet = fleet_by_subdir(repo)
    changed = False
    for subdir, m in meta.items():
        key = f"{subdir}/{m['version']}"
        if key in dates or subdir not in fleet:
            continue
        result = subprocess.run(
            ["git", "-C", fleet[subdir], "log", "-1", "--format=%cs", f"refs/tags/{m['version']}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            dates[key] = result.stdout.strip()
            changed = True
    if changed:
        body = RELEASE_DATES_HEADER + "".join(f'"{k}" = "{dates[k]}"\n' for k in sorted(dates))
        (repo / "release-dates.toml").write_text(body)
        print("updated release-dates.toml with learned tag dates; commit it with this change")
    return dates

def markdown_title(text: str, fallback: str) -> tuple[str, str]:
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        return lines[0][2:].strip(), "\n".join(lines[1:]).lstrip("\n")
    return fallback, text


def md_to_html(text: str) -> str:
    return markdown.markdown(text, extensions=["fenced_code", "tables"])


def site_description(site: dict) -> str:
    return site.get("description") or site.get("about", "").strip().split(".")[0] + "."


def head(title: str, desc: str, url: str, site: dict, *, image: bool = False) -> str:
    image_tag = ""
    if image:
        image_url = url.rsplit("/", 1)[0] + "/" + site.get("portrait", "portrait.jpg")
        image_tag = f'\n  <meta property="og:image" content="{esc(image_url)}">'
    return f"""<meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{esc(desc)}">
  <link rel="canonical" href="{esc(url)}">
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(desc)}">
  <meta property="og:type" content="website">
  <meta property="og:url" content="{esc(url)}">{image_tag}
  <title>{esc(title)}</title>
  <script>\n{HEAD_SCRIPT}  </script>
  <style>\n{STYLE}  </style>"""


def page_chrome(title: str, desc: str, url: str, site: dict, body: str, *, home: bool = False) -> str:
    masthead = ""
    if not home:
        masthead = """
  <header>
    <div class="masthead">
      <h1><a href="/">~averagechris</a></h1>
      <button class="theme-toggle" id="theme-toggle" aria-label="toggle color theme">dawn &frasl; moon</button>
    </div>
  </header>
  <hr class="divider">
"""

    return f"""<!doctype html>
<html lang="en">
<head>
  {head(title, desc, url, site, image=home)}
</head>
<body>{masthead}
{body}
  <footer>
    <p>Source for this page: <a href="https://git.sr.ht/~averagechris/averagechris.srht.site">averagechris.srht.site</a>.</p>
  </footer>
  <script>
{BODY_SCRIPT}  </script>
</body>
</html>
"""


def code_line(text: str) -> str:
    return (
        '<div class="code-line">'
        f'<button class="copy" data-copy="{esc(text)}">copy</button>'
        f"<code>{esc(text)}</code>"
        "</div>"
    )


def install_details(artifacts: list[dict], verified: bool = False) -> str:
    rows = []
    for artifact in artifacts:
        command = f"curl -fsSL {artifact['url']} | tar xz"
        if verified:
            command = (
                f"curl -fsSLO {artifact['url']}\n"
                f"echo \"{artifact['sha256']}  {artifact['name']}\" | shasum -a 256 -c\n"
                f"tar xzf {artifact['name']}"
            )
        rows.append(f'<p class="muted mono">{esc(artifact["label"])}</p>{code_line(command)}')
    return "".join(rows)


def version_bits(path: str, meta: dict[str, dict], dates: dict[str, str]) -> tuple[str, str, list[str]]:
    m = meta.get(path) or {}
    version = m.get("version")
    date = dates.get(f"{path}/{version}") if version else None
    badge = f'<span class="version">{esc(version)}</span>' if version else ""
    date_text = date or ""
    platforms = list(m.get("platforms", []))
    return badge, date_text, platforms


def card_meta_line(platforms: list[str], date: str) -> str:
    if platforms:
        text = " · ".join(platforms)
        if date:
            text = f"{text} — {date}"
        return f'<p class="mono muted">{esc(text)}</p>'
    if date:
        return f'<p class="mono muted">{esc(date)}</p>'
    return ""


DATE_PREFIX_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})-(?P<slug>.+)$")


def file_date(repo: pathlib.Path, path: pathlib.Path) -> str:
    result = subprocess.run(
        ["git", "log", "-1", "--format=%cs", "--", str(path.relative_to(repo))],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return dt.date.fromtimestamp(path.stat().st_mtime).isoformat()


def note_slug_and_date(repo: pathlib.Path, path: pathlib.Path) -> tuple[str, str]:
    match = DATE_PREFIX_RE.match(path.stem)
    if match:
        return match.group("slug"), match.group("date")
    return path.stem, file_date(repo, path)


def published_notes(repo: pathlib.Path) -> list[dict[str, object]]:
    notes_dir = repo / "content" / "notes"
    if not notes_dir.is_dir():
        return []

    notes = []
    for path in sorted(notes_dir.glob("*.md")):
        slug, date = note_slug_and_date(repo, path)
        title, body_md = markdown_title(path.read_text(), path.stem)
        notes.append(
            {
                "path": path,
                "slug": slug,
                "date": date,
                "title": title,
                "body_md": body_md,
            }
        )
    return sorted(notes, key=lambda note: (str(note["date"]), str(note["slug"])), reverse=True)


def public_content_pages(config: dict) -> list[Page]:
    return [page for page in config["pages"] if page.listed and not page.draft]


def now_section(config: dict) -> str:
    page = next((page for page in config["pages"] if page.slug == "now" and not page.draft), None)
    if page is None:
        return ""
    date = page.date or ""
    return f"""
  <section class="content">
    <h2>Now</h2>
    <p class="muted">updated {esc(date)}</p>
{md_to_html(page.body)}
  </section>"""

def render_index(
    repo: pathlib.Path,
    config: dict,
    base_url: str,
    published: dict[str, bool],
    meta: dict[str, dict],
    project_pages: dict[str, set[str]],
    dates: dict[str, str],
    notes: list[dict[str, object]],
) -> str:
    site = config["site"]
    cards = []
    more_items = []
    for project in config["projects"]:
        if not project.get("listed", True):
            continue
        name = esc(project["name"])
        description = esc(project["description"])
        repo_url = esc(project["repo"])
        has_downloads = project.get("downloads", True)

        if project.get("tier", "featured") == "more":
            more_links = []
            if has_downloads:
                more_links.append(f'<a href="/{esc(project["path"])}/">downloads</a>')
                more_links.extend(project_info_links(project, project_pages))
            more_links.extend(
                f'<a href="{esc(link["url"])}">{esc(link["label"])}</a>'
                for link in project.get("extra_links", [])
            )
            suffix = f' ({" · ".join(more_links)})' if more_links else ""
            more_items.append(
                f'    <li><a href="{repo_url}">{name}</a> &mdash; {description}{suffix}</li>'
            )
            continue

        links = []
        if has_downloads:
            if published.get(project["path"]) is False:
                links.append('<span class="pending">no release yet</span>')
            else:
                downloads_url = f'/{esc(project["path"])}/'
                links.append(f'<a class="primary-link" href="{downloads_url}">downloads</a>')
                links.extend(project_info_links(project, project_pages))
        for link in project.get("extra_links", []):
            links.append(f'<a href="{esc(link["url"])}">{esc(link["label"])}</a>')
        links.append(f'<a href="{repo_url}">source</a>')

        badge, date_text, platforms = version_bits(project["path"], meta, dates)
        metadata = card_meta_line(platforms, date_text)
        install = ""
        if has_downloads and project["path"] in meta:
            install = (
                '<details class="install"><summary>install</summary>'
                f'{install_details(meta[project["path"]]["artifacts"])}'
                "</details>"
            )
        card_parts = [
            '    <article class="project">',
            f"      {badge}<h3>{name}</h3>",
            f"      <p>{description}</p>",
        ]
        if metadata:
            card_parts.append(f"      {metadata}")
        card_parts.extend(
            [
                f'      <p class="project-links">{" ".join(links)}</p>',
                f"      {install}" if install else "",
                "    </article>",
            ]
        )
        cards.append("\n".join(part for part in card_parts if part))

    more_section = ""
    if more_items:
        more_section = (
            '\n  <hr class="divider">\n\n  <h2>More projects</h2>\n  <ul class="more-projects">\n'
            + "\n".join(more_items)
            + "\n  </ul>\n"
        )

    content_nav = " ".join(
        f'<a href="/{esc(page.slug)}/">{esc(page.slug)}</a>'
        for page in public_content_pages(config)
    )
    profile_links = " ".join(
        f'<a href="{esc(link["url"])}">{esc(link["label"])}</a>'
        for link in site.get("links", [])
    )
    notes_nav = ' <a href="/notes/">notes</a>' if notes else ""
    profile_links = f'{profile_links} <a href="/tools/">tools</a> {content_nav}'
    profile_links = f"{profile_links}{notes_nav}"
    about = "\n".join(
        f'  <p class="about">{esc(paragraph.strip())}</p>'
        for paragraph in site["about"].split("\n\n")
        if paragraph.strip()
    )
    tagline = ""
    if site.get("tagline"):
        tagline = f'\n        <p class="tagline">{esc(site["tagline"])}</p>'
    portrait = ""
    if site.get("portrait"):
        portrait = (
            f'\n      <img class="portrait" src="{esc(site_path(site["portrait"]))}" '
            f'alt="{esc(site["name"])}" width="88" height="88">'
        )
    body = f"""  <header>
    <div class="masthead">
      <div class="identity">{portrait}
      <div>
        <h1>{esc(site["name"])} <small>{esc(site["title"])}</small></h1>{tagline}
      </div>
      </div>
      <button class="theme-toggle" id="theme-toggle" aria-label="toggle color theme">dawn &frasl; moon</button>
    </div>
    <nav class="profile-links">{profile_links}</nav>
  </header>

{about}
{now_section(config)}

  <hr class="divider">

  <h2>Projects</h2>
  <p class="muted">all current versions + install one-liners on <a href="/tools/">one tools page</a>.</p>
  <section class="projects">
{chr(10).join(cards)}
  </section>{more_section}"""
    return page_chrome(site["title"], site_description(site), base_url + "/", site, body, home=True)

def render_content_pages(repo: pathlib.Path, site_dir: pathlib.Path, site: dict, base_url: str) -> set[str]:
    del repo
    slugs = set()
    for page in public_content_pages(site["_config"]):
        title = page.title
        body_md = page.body
        slug = page.slug
        slugs.add(slug)
        body = f"""  <main class="content">
    <h1>{esc(title)}</h1>
{md_to_html(body_md)}
  </main>"""
        dest = site_dir / slug / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            page_chrome(
                f"{title} · ~averagechris",
                site_description(site),
                f"{base_url}/{slug}/",
                site,
                body,
            )
        )
    return slugs


def render_notes(repo: pathlib.Path, site_dir: pathlib.Path, site: dict, base_url: str) -> list[dict[str, object]]:
    del repo
    notes = sorted(
        (
            {"slug": note.slug, "date": note.date, "title": note.title, "body_md": note.body}
            for note in site["_config"]["notes"]
            if note.listed and not note.draft
        ),
        key=lambda note: (str(note["date"]), str(note["slug"])),
        reverse=True,
    )
    if not notes:
        return []

    notes_dir = site_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for note in notes:
        slug = str(note["slug"])
        title = str(note["title"])
        date = str(note["date"])
        body = f"""  <main class="content">
    <h1>{esc(title)}</h1>
    <p class="muted mono">{esc(date)}</p>
{md_to_html(str(note["body_md"]))}
  </main>"""
        dest = notes_dir / slug / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            page_chrome(
                f"{title} · ~averagechris",
                site_description(site),
                f"{base_url}/notes/{slug}/",
                site,
                body,
            )
        )
        entries.append(
            f'    <li><span class="muted mono">{esc(date)}</span> — '
            f'<a href="/notes/{esc(slug)}/">{esc(title)}</a></li>'
        )

    index_body = f"""  <main class="content">
    <h1>Notes</h1>
    <ul class="more-projects">
{chr(10).join(entries)}
    </ul>
  </main>"""
    (notes_dir / "index.html").write_text(
        page_chrome(
            "Notes · ~averagechris",
            site_description(site),
            f"{base_url}/notes/",
            site,
            index_body,
        )
    )
    return notes

def render_tools(
    config: dict,
    site: dict,
    base_url: str,
    meta: dict[str, dict],
    project_pages: dict[str, set[str]],
    dates: dict[str, str],
    has_keys: bool,
) -> str:
    verify = "/keys/" if has_keys else "https://meta.sr.ht/~averagechris.pgp"
    entries = []
    for project in config["projects"]:
        if not project.get("downloads", True) or project["path"] not in meta:
            continue
        badge, date_text, _ = version_bits(project["path"], meta, dates)
        date_html = f' <span class="muted mono">{esc(date_text)}</span>' if date_text else ""
        project_meta = meta[project["path"]]
        links = [f'<a class="primary-link" href="/{esc(project["path"])}/">downloads page</a>']
        links.extend(project_info_links(project, project_pages))
        links.append(f'<a href="{esc(project["repo"])}">source</a>')
        entries.append(f"""    <article class="tool" id="{esc(project["path"])}">
      <h2><a href="#{esc(project["path"])}">{esc(project["name"])}</a> {badge}{date_html}</h2>
      <p>{esc(project["description"])}</p>
      <p class="project-links">{" ".join(links)}</p>
      <h3>install</h3>
{install_details(project_meta["artifacts"])}
      <h3>verified install</h3>
{install_details(project_meta["artifacts"], verified=True)}
    </article>""")
    body = f"""  <main class="content">
    <h1>Tools</h1>
    <p>One page with every tool I distribute. See <a href="{esc(verify)}">verification details</a>.</p>
{chr(10).join(entries)}
  </main>"""
    return page_chrome("Tools · ~averagechris", site_description(site), base_url + "/tools/", site, body)


def render_python_site(repo: pathlib.Path, config: dict, site_dir: pathlib.Path, base_url: str, fleet_json: dict) -> tuple[set[str], list[dict[str, object]]]:
    site = config["site"]
    published, meta, project_pages, dates = fleet_render_inputs(fleet_json)
    render_fleet_download_pages(config, site_dir, base_url, fleet_json)
    slugs = render_content_pages(repo, site_dir, site, base_url)
    notes = render_notes(repo, site_dir, site, base_url)
    (site_dir / "index.html").write_text(
        render_index(repo, config, base_url, published, meta, project_pages, dates, notes)
    )
    tools_dir = site_dir / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    (tools_dir / "index.html").write_text(
        render_tools(config, site, base_url, meta, project_pages, dates, "keys" in slugs)
    )
    not_found_body = """  <main class="content">
    <h1>404</h1>
    <p>nothing grows here</p>
    <p><a href="/">home</a> · <a href="/tools/">tools</a></p>
  </main>"""
    (site_dir / "404.html").write_text(
        page_chrome("404 · ~averagechris", "nothing grows here", base_url + "/404.html", site, not_found_body)
    )
    return slugs, notes


def render_zola_site(repo: pathlib.Path, config: dict, site_dir: pathlib.Path, base_url: str, fleet_json: dict) -> tuple[set[str], list[dict[str, object]]]:
    from materialize_zola import render_zola_site as zola_render

    return zola_render(repo, config, site_dir, base_url, fleet_json)


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", default=None)
    parser.add_argument("--out", default="dist")
    parser.add_argument("--renderer", choices=("python", "zola"), default="zola")
    args = parser.parse_args()
    repo = pathlib.Path(__file__).resolve().parent.parent
    loaded = load_site_data(repo)
    config = {"site": dict(loaded.site), "projects": loaded.projects, "pages": loaded.pages, "notes": loaded.notes, "wiki": loaded.wiki}
    site = config["site"]
    site["_config"] = config
    domain = args.domain or site["domain"]
    base_url = f"https://{domain}"

    out_dir = repo / args.out
    site_dir = out_dir / "site"
    if site_dir.exists():
        shutil.rmtree(site_dir)
    site_dir.mkdir(parents=True)

    print("building fleet project pages from sr.ht tags and repo files")
    fleet_json = acquire_fleet_data(repo, config, site_dir, base_url)
    fleet_json["release_dates"] = update_release_dates(repo, fleet_json["meta"])
    fleet_json_path = write_fleet_json(repo, fleet_json)
    fleet_json = load_fleet_json(fleet_json_path)
    if args.renderer == "python":
        render_python_site(repo, config, site_dir, base_url, fleet_json)
    else:
        render_zola_site(repo, config, site_dir, base_url, fleet_json)
    assemble_site(repo, out_dir, site_dir, fleet_json["state"])


if __name__ == "__main__":
    main()
