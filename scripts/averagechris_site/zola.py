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
    return site["description"]


def public_pages(config: dict) -> list:
    return [page for page in config["pages"] if page.listed and not page.draft]


def published_wiki(config: dict) -> list[dict]:
    pages = []
    for wiki in config.get("wiki", []):
        if wiki.listed and not wiki.draft:
            item = dataclasses.asdict(wiki) | {"source": "site"}
            item.pop("source_dir", None)
            pages.append(item)
    return sorted(pages, key=lambda wiki: wiki["title"].lower())


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
    site["home_body"] = config["home_body"]

    meta = dict(fleet_json.get("meta", {}))
    project_pages = dict(fleet_json.get("project_pages", {}))
    dates = dict(fleet_json.get("release_dates", {}))
    notes = published_notes(config)
    wiki_pages = list(fleet_json.get("wiki", [])) or published_wiki(config)
    site_wiki = [w for w in wiki_pages if w.get("source") == "site"]
    project_wiki = {}
    for w in wiki_pages:
        project = w.get("project")
        if project:
            project_wiki.setdefault(project["pages_subdir"], {"project": project, "pages": []})["pages"].append(w)
    for group in project_wiki.values():
        group["pages"].sort(key=lambda w: w["title"].lower())

    content_pages = [dataclasses.asdict(page) for page in public_pages(config) if page.slug != "now"]
    now = next((dataclasses.asdict(page) for page in config["pages"] if page.slug == "now" and page.listed and not page.draft), None)

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
                "info_links_relative": info_links(project, project_pages),
                "version": bits["version"],
                "date": bits["date"],
                "tools_rows": install_rows(m.get("artifacts", [])) if has_downloads and m else [],
                "verified_rows": install_rows(m.get("artifacts", []), verified=True) if has_downloads and m else [],
            }
        )
        projects.append(item)

    by_path = {project["path"]: project for project in projects}
    featured_projects = [by_path[path] for path in site["featured_projects"]]

    project_details = []
    fleet_projects = dict(fleet_json.get("projects", {}))
    for project in projects:
        path = project["path"]
        info = fleet_projects.get(path)
        releases = []
        if info:
            for tag in info.get("versions", []):
                arts = []
                for artifact in info.get("artifacts", []):
                    if artifact.get("version") != tag:
                        continue
                    arts.append({**artifact, "download_rel": f"downloads/{artifact['name']}" if artifact.get("hosted") else artifact["url"], "checksum_rel": f"downloads/{artifact['name']}.sha256" if artifact.get("hosted") else artifact["sha_url"]})
                if arts:
                    releases.append({"tag": tag, "latest": tag == info["tag"], "artifacts": arts})
        latest_art = next((a for a in info.get("artifacts", []) if a.get("version") == info["tag"]), None) if info else None
        install = ""
        if latest_art:
            stem = latest_art["name"].removesuffix(".tar.gz")
            release_project = info["project"]
            binaries = release_project.get("binaries", [release_project["name"]])
            installs = "\n".join(f"install -m 0755 {stem}/{binary} ~/.local/bin/{binary}" for binary in binaries)
            install = f"curl -LO {base_url}/{path}/downloads/{latest_art['name']}\nsha256sum -c {latest_art['name']}.sha256\ntar -xzf {latest_art['name']}\n{installs}"
        release_project = info.get("project", {}) if info else {}
        project_details.append(
            {
                "path": path,
                "project": project,
                "info": info,
                "page_links": [{"label": p.removesuffix(".html"), "url": p} for p in info.get("docs", []) if p in DOC_PAGES] if info else [],
                "releases": releases,
                "whats_new": info.get("changelog", {}).get(info["tag"], "No changelog entry found.") if info else "",
                "previous": [{"tag": t, "body": info.get("changelog", {}).get(t, "")} for t in info.get("versions", [])[1:3] if info.get("changelog", {}).get(t)] if info else [],
                "install": install,
                "has_release": bool(info and releases),
                "issues_url": (
                    f"https://todo.sr.ht/~averagechris/projects?search=label%3A%22repo%3A{release_project['srht_repo']}%22"
                    if release_project.get("srht_repo")
                    else "https://todo.sr.ht/~averagechris/projects"
                ),
            }
        )

    page_slugs = {page["slug"] for page in content_pages}
    primary_nav = [{"label": "software", "url": "/tools/"}]
    if notes:
        primary_nav.append({"label": "notes", "url": "/notes/"})
    if wiki_pages:
        primary_nav.append({"label": "guides", "url": "/wiki/"})
    if "uses" in page_slugs:
        primary_nav.append({"label": "uses", "url": "/uses/"})
    if now:
        primary_nav.append({"label": "now", "url": "/now/"})

    recent_guides = sorted(
        [wiki for wiki in wiki_pages if wiki.get("date")],
        key=lambda wiki: (str(wiki["date"]), str(wiki["slug"])),
        reverse=True,
    )[:3]
    additional_pages = [page for page in content_pages if page["slug"] not in {"uses", "keys", "fleet"}]

    return {
        "base_url": base_url,
        "site": site,
        "content_pages": content_pages,
        "now": now,
        "primary_nav": primary_nav,
        "additional_pages": additional_pages,
        "notes": notes,
        "recent_notes": notes[:3],
        "wiki": wiki_pages,
        "recent_guides": recent_guides,
        "site_wiki": site_wiki,
        "project_wiki": [project_wiki[k] for k in sorted(project_wiki)],
        "projects": projects,
        "featured_projects": featured_projects,
        "project_details": project_details,
    }


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
            write_page(content, f"/{page['slug']}/", f"{page['title']} · ~averagechris", page["description"], f"{base_url}/{page['slug']}/", kind="content", body=page["body"], extra={"slug": page["slug"], "body_format": page["body_format"]})
        if data["now"]:
            now = data["now"]
            write_page(content, "/now/", "Now · ~averagechris", now["description"], f"{base_url}/now/", kind="now", body=now["body"], extra={"slug": "now", "body_format": now["body_format"]})
        if data["notes"]:
            write_page(content, "/notes/", "Notes · ~averagechris", "Published notes, observations, and technical lessons.", f"{base_url}/notes/", kind="notes_index")
            for note in data["notes"]:
                write_page(content, f"/notes/{note['slug']}/", f"{note['title']} · ~averagechris", note["description"], f"{base_url}/notes/{note['slug']}/", kind="note", body=note["body"], extra={"slug": note["slug"], "body_format": note["body_format"]})
        if data["wiki"]:
            write_page(content, "/wiki/", "Guides · ~averagechris", "Guides and reference material for the site and its software.", f"{base_url}/wiki/", kind="wiki_index")
            for wiki in data["wiki"]:
                write_page(content, f"/wiki/{wiki['slug']}/", f"{wiki['title']} · ~averagechris", wiki.get("description", data["site"]["description"]), f"{base_url}/wiki/{wiki['slug']}/", kind="wiki", body=wiki["body"], extra={"slug": wiki["slug"], "body_format": wiki.get("body_format", "markdown")})
        write_page(content, "/tools/", "Software · ~averagechris", "All software projects, source links, and available downloads.", base_url + "/tools/", kind="tools")
        for item in data["project_details"]:
            project = item["project"]
            write_page(content, f"/{item['path']}/", f"{project['name']} · ~averagechris", project["description"], f"{base_url}/{item['path']}/", kind="project", extra={"path": item["path"]})
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
