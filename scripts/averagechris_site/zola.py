#!/usr/bin/env python3
"""Materialize canonical site data into a temporary Zola site and merge HTML."""

from __future__ import annotations

import dataclasses
import json
import pathlib
import shutil
import subprocess
import tempfile

from averagechris_site.fleet import DOC_PAGES


def site_description(site: dict) -> str:
    return site.get("description") or site.get("about", "").strip().split(".")[0] + "."


def public_pages(config: dict) -> list:
    return [page for page in config["pages"] if page.listed and not page.draft]


def published_wiki(config: dict) -> list[dict]:
    return sorted([dataclasses.asdict(w) | {"source": "site"} for w in config.get("wiki", []) if w.listed and not w.draft], key=lambda w: w["title"].lower())


def published_notes(config: dict) -> list[dict]:
    notes = []
    for note in config["notes"]:
        if note.listed and not note.draft:
            item = dataclasses.asdict(note)
            item.pop("source_dir", None)
            notes.append(item)
    return sorted(
        notes,
        key=lambda note: (str(note["date"]), str(note["slug"])),
        reverse=True,
    )


def code_line(command: str) -> dict:
    return {"command": command}


def install_rows(artifacts: list[dict], *, verified: bool = False) -> list[dict]:
    rows = []
    for artifact in artifacts:
        command = f"curl -fsSL {artifact['url']} | tar xz"
        if verified:
            command = f"curl -fsSLO {artifact['url']}\necho \"{artifact['sha256']}  {artifact['name']}\" | shasum -a 256 -c\ntar xzf {artifact['name']}"
        rows.append({"label": artifact["label"], "command": command})
    return rows


def version_bits(path: str, meta: dict[str, dict], dates: dict[str, str]) -> dict:
    m = meta.get(path) or {}
    version = m.get("version", "")
    return {
        "version": version,
        "date": dates.get(f"{path}/{version}", "") if version else "",
        "platforms": list(m.get("platforms", [])),
    }


def site_path(path: str) -> str:
    return "/" + path.lstrip("/")


def info_links(project: dict, project_pages: dict[str, list[str]]) -> list[dict]:
    path = project["path"]
    return [
        {"label": page.removesuffix(".html"), "url": f"/{path}/{page}"}
        for page in DOC_PAGES
        if page in set(project_pages.get(path, []))
    ]


def build_template_data(config: dict, base_url: str, fleet_json: dict) -> dict:
    site = {k: v for k, v in config["site"].items() if k != "_config"}
    site["description"] = site_description(site)
    if site.get("portrait"):
        site["portrait_url"] = site_path(site["portrait"])
    site["about_paragraphs"] = [p.strip() for p in site.get("about", "").split("\n\n") if p.strip()]

    published = dict(fleet_json.get("published", {}))
    meta = dict(fleet_json.get("meta", {}))
    project_pages = dict(fleet_json.get("project_pages", {}))
    dates = dict(fleet_json.get("release_dates", {}))
    notes = published_notes(config)
    games = [game for game in fleet_json.get("games", []) if game.get("listed", True)]
    wiki_pages = list(fleet_json.get("wiki", [])) or published_wiki(config)
    site_wiki = [w for w in wiki_pages if w.get("source") == "site"]
    project_wiki = {}
    for w in wiki_pages:
        project = w.get("project")
        if project:
            project_wiki.setdefault(project["pages_subdir"], {"project": project, "pages": []})["pages"].append(w)
    for group in project_wiki.values():
        group["pages"].sort(key=lambda w: w["title"].lower())

    content_pages = [dataclasses.asdict(page) for page in public_pages(config)]
    now = next((dataclasses.asdict(page) for page in config["pages"] if page.slug == "now" and not page.draft), None)
    nav_pages = [page for page in content_pages]

    projects = []
    for project in config["projects"]:
        if not project.get("listed", True):
            continue
        path = project["path"]
        has_downloads = project.get("downloads", True)
        bits = version_bits(path, meta, dates)
        m = meta.get(path)
        item = dict(project)
        item.update(
            {
                "has_downloads": has_downloads,
                "published": published.get(path),
                "downloads_url": f"/{path}/",
                "info_links_home": info_links(project, project_pages),
                "info_links_relative": info_links(project, project_pages),
                "version": bits["version"],
                "date": bits["date"],
                "platforms": bits["platforms"],
                "install_rows": install_rows(m.get("artifacts", [])) if has_downloads and m else [],
                "tools_rows": install_rows(m.get("artifacts", [])) if has_downloads and m else [],
                "verified_rows": install_rows(m.get("artifacts", []), verified=True) if has_downloads and m else [],
                "in_tools": bool(has_downloads and m),
            }
        )
        projects.append(item)

    downloads = []
    for path, info in fleet_json.get("projects", {}).items():
        project = dict(info["project"])
        releases = []
        for tag in info.get("versions", []):
            arts = []
            for artifact in info.get("artifacts", []):
                if artifact.get("version") != tag:
                    continue
                arts.append({**artifact, "download_rel": f"downloads/{artifact['name']}" if artifact.get("hosted") else artifact["url"], "checksum_rel": f"downloads/{artifact['name']}.sha256" if artifact.get("hosted") else artifact["sha_url"]})
            if arts:
                releases.append({"tag": tag, "latest": tag == info["tag"], "artifacts": arts})
        latest_art = next((a for a in info.get("artifacts", []) if a.get("version") == info["tag"]), None)
        install = ""
        if latest_art:
            stem = latest_art["name"].removesuffix(".tar.gz")
            binaries = project.get("binaries", [project["name"]])
            installs = "\n".join(f"install -m 0755 {stem}/{binary} ~/.local/bin/{binary}" for binary in binaries)
            install = f"curl -LO {base_url}/{project['pages_subdir']}/downloads/{latest_art['name']}\nsha256sum -c {latest_art['name']}.sha256\ntar -xzf {latest_art['name']}\n{installs}"
        downloads.append({"path": path, "project": project, "info": info, "page_links": [{"label": p.removesuffix(".html"), "url": p} for p in info.get("docs", []) if p in DOC_PAGES], "releases": releases, "whats_new": info.get("changelog", {}).get(info["tag"], "No changelog entry found."), "previous": [{"tag": t, "body": info.get("changelog", {}).get(t, "")} for t in info.get("versions", [])[1:3] if info.get("changelog", {}).get(t)], "install": install})

    return {"base_url": base_url, "site": site, "content_pages": content_pages, "now": now, "nav_pages": nav_pages, "notes": notes, "games": games, "wiki": wiki_pages, "site_wiki": site_wiki, "project_wiki": [project_wiki[k] for k in sorted(project_wiki)], "projects": projects, "downloads": downloads, "has_keys": any(p["slug"] == "keys" for p in content_pages)}


def toml_string(value: str) -> str:
    return json.dumps(value)


def write_page(content_dir: pathlib.Path, rel: str, title: str, desc: str, canonical: str, *, kind: str, body: str = "", extra: dict | None = None, template: str = "page.html") -> None:
    if rel == "/":
        dest = content_dir / "_index.md"
        template = "section.html"
    elif rel.endswith(".html"):
        dest = content_dir / f"{rel.strip('/').removesuffix('.html')}.md"
    else:
        dest = content_dir / rel.strip("/") / "index.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    extra = extra or {}
    fm = ["+++", f"title = {toml_string(title)}", f"description = {toml_string(desc)}", f"template = {toml_string(template)}", "[extra]", f"canonical = {toml_string(canonical)}", f"kind = {toml_string(kind)}"]
    for key, value in extra.items():
        fm.append(f"{key} = {json.dumps(value)}")
    fm.append("+++\n")
    dest.write_text("\n".join(fm) + body)


def render_zola_site(repo: pathlib.Path, config: dict, site_dir: pathlib.Path, base_url: str, fleet_json: dict) -> tuple[set[str], list[dict[str, object]]]:
    data = build_template_data(config, base_url, fleet_json)
    slugs = {page["slug"] for page in data["content_pages"]}
    wiki_seen: dict[str, str] = {}
    for wiki in data["wiki"]:
        owner = wiki.get("source", "site")
        if wiki["slug"] in wiki_seen:
            raise SystemExit(f"error: duplicate wiki slug {wiki['slug']!r}: {wiki_seen[wiki['slug']]} and {owner}")
        wiki_seen[wiki["slug"]] = owner

    with tempfile.TemporaryDirectory(prefix="averagechris-zola-") as tmp:
        tmp_path = pathlib.Path(tmp)
        shutil.copytree(repo / "renderers" / "zola" / "templates", tmp_path / "templates")
        shutil.copy2(repo / "renderers" / "zola" / "config.toml", tmp_path / "config.toml")
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "site.json").write_text(json.dumps(data, sort_keys=True))
        content = tmp_path / "content"
        content.mkdir()

        write_page(content, "/", data["site"]["title"], data["site"]["description"], base_url + "/", kind="home", extra={"home": True})
        for page in data["content_pages"]:
            if page["slug"] == "now":
                continue
            write_page(content, f"/{page['slug']}/", f"{page['title']} · ~averagechris", data["site"]["description"], f"{base_url}/{page['slug']}/", kind="content", body=page["body"], extra={"slug": page["slug"], "body_format": page["body_format"]})
        if data["notes"]:
            write_page(content, "/notes/", "Notes · ~averagechris", data["site"]["description"], f"{base_url}/notes/", kind="notes_index")
            for note in data["notes"]:
                write_page(content, f"/notes/{note['slug']}/", f"{note['title']} · ~averagechris", data["site"]["description"], f"{base_url}/notes/{note['slug']}/", kind="note", body=note["body"], extra={"slug": note["slug"], "body_format": note["body_format"]})
        if data["games"]:
            write_page(content, "/games/", "Games · ~averagechris", data["site"]["description"], f"{base_url}/games/", kind="games_index")
        if data["wiki"]:
            write_page(content, "/wiki/", "Wiki · ~averagechris", data["site"]["description"], f"{base_url}/wiki/", kind="wiki_index")
            for wiki in data["wiki"]:
                write_page(content, f"/wiki/{wiki['slug']}/", f"{wiki['title']} · ~averagechris", wiki.get("description", data["site"]["description"]), f"{base_url}/wiki/{wiki['slug']}/", kind="wiki", body=wiki["body"], extra={"slug": wiki["slug"], "body_format": wiki.get("body_format", "markdown")})
        write_page(content, "/tools/", "Tools · ~averagechris", data["site"]["description"], base_url + "/tools/", kind="tools")
        for item in data["downloads"]:
            project = item["project"]
            write_page(content, f"/{item['path']}/", f"{project['name']} downloads", project.get("description", ""), f"{base_url}/{item['path']}/", kind="download", extra={"path": item["path"]})
        write_page(content, "/404.html", "404 · ~averagechris", "nothing grows here", base_url + "/404.html", kind="404")

        subprocess.run(["zola", "build", "--output-dir", str(tmp_path / "public")], cwd=tmp_path, check=True)
        for path in (tmp_path / "public").rglob("*.html"):
            rel = path.relative_to(tmp_path / "public")
            if rel == pathlib.Path("404/index.html"):
                rel = pathlib.Path("404.html")
            dest = site_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
    return slugs, data["notes"]
