#!/usr/bin/env python3
"""Checked loader for renderer-agnostic site data."""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import pathlib
import re
import sys
import tomllib
import urllib.parse

from averagechris_site.paths import repo_root


class SiteDataError(ValueError):
    """Raised when canonical site data is invalid or ambiguous."""


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIERS = {"featured", "more"}
BODY_FORMATS = {"markdown", "html"}
DEVELOPMENT_STATES = {"active", "maintenance", "paused", "archived"}
MATURITY_STATES = {"experimental", "usable", "stable"}
USE_SIGNALS = {"dogfooded", "team-used", "public"}
ORIGINS = {"original", "maintained-fork"}
UNRESOLVED_MARKERS = (
    "CHRIS:",
    "PLACEHOLDER: Chris should edit this",
    "UNVERIFIED FACT",
)
RESERVED_PROJECT_PATHS = {"404", "notes", "now", "tools", "wiki"}
RESERVED_PAGE_SLUGS = {"404", "notes", "tools", "wiki"}


@dataclasses.dataclass(frozen=True)
class Page:
    slug: str
    title: str
    description: str
    body_format: str
    body: str
    listed: bool
    draft: bool
    date: str | None = None


@dataclasses.dataclass(frozen=True)
class Note:
    slug: str
    title: str
    description: str
    date: str
    body_format: str
    body: str
    draft: bool
    listed: bool
    source_dir: pathlib.Path


@dataclasses.dataclass(frozen=True)
class WikiPage:
    slug: str
    title: str
    description: str
    date: str
    body_format: str
    body: str
    draft: bool
    listed: bool
    source_dir: pathlib.Path


@dataclasses.dataclass(frozen=True)
class SiteData:
    site: dict
    home_body: str
    projects: list[dict]
    pages: list[Page]
    notes: list[Note]
    wiki: list[WikiPage]


def _fail(path: pathlib.Path, message: str) -> "sys.NoReturn":
    raise SiteDataError(f"{path}: {message}")


def _text(value: object, path: pathlib.Path, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(path, f"missing required string field {key!r}")
    return value


def _published_text(value: object, path: pathlib.Path, key: str) -> str:
    text = _text(value, path, key)
    _check_unresolved_markers(path, text, field=key)
    return text


def _url(value: object, path: pathlib.Path, key: str, *, root_relative: bool = True) -> str:
    url = _text(value, path, key)
    if root_relative and url.startswith("/") and not url.startswith("//"):
        return url
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        expected = "HTTPS or root-relative" if root_relative else "HTTPS"
        _fail(path, f"{key!r} must be {expected}")
    return url


def _bool(value: object, path: pathlib.Path, key: str) -> bool:
    if not isinstance(value, bool):
        _fail(path, f"missing required boolean field {key!r}")
    return value


def _slug(value: object, path: pathlib.Path, key: str = "slug") -> str:
    slug = _text(value, path, key)
    if not SLUG_RE.match(slug):
        _fail(path, f"{key!r} must be a lowercase URL slug")
    return slug


def _date(value: object, path: pathlib.Path, key: str = "date") -> str:
    date = _text(value, path, key)
    if not DATE_RE.match(date):
        _fail(path, f"{key!r} must be YYYY-MM-DD")
    try:
        datetime.date.fromisoformat(date)
    except ValueError:
        _fail(path, f"{key!r} must be a real calendar date")
    return date


def _body_format(value: object, path: pathlib.Path) -> str:
    fmt = _text(value, path, "body_format")
    if fmt not in BODY_FORMATS:
        _fail(path, f"body_format must be one of {sorted(BODY_FORMATS)}")
    return fmt


def _read_toml(path: pathlib.Path) -> dict:
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as error:
        _fail(path, str(error))


def _check_unresolved_markers(path: pathlib.Path, value: str, *, field: str) -> None:
    for marker in UNRESOLVED_MARKERS:
        if marker in value:
            _fail(path, f"published {field} contains unresolved marker {marker!r}")


def _check_published_body(path: pathlib.Path, body: str) -> None:
    _check_unresolved_markers(path, body, field="body")


def _load_body(meta_path: pathlib.Path, slug: str, body_format: str, *, published: bool) -> str:
    suffix = ".md" if body_format == "markdown" else ".html"
    slug_body_path = meta_path.with_name(f"{slug}{suffix}")
    sidecar_body_path = meta_path.with_suffix(suffix)
    matches = [path for path in (slug_body_path, sidecar_body_path) if path.exists()]
    if not matches:
        _fail(meta_path, f"body file missing for slug {slug!r}")
    if len(set(matches)) > 1:
        _fail(meta_path, f"ambiguous body files for slug {slug!r}: {matches[0].name}, {matches[1].name}")
    body_path = matches[0]
    body = body_path.read_text()
    if published:
        _check_published_body(body_path, body)
    return body


def _load_pages(root: pathlib.Path) -> list[Page]:
    pages_root = root / "pages"
    if not pages_root.is_dir():
        _fail(pages_root, "missing pages directory")
    pages: list[Page] = []
    seen: set[str] = set()
    for base in (pages_root, pages_root / "_drafts"):
        if not base.exists():
            continue
        for meta_path in sorted(base.glob("*.toml")):
            meta = _read_toml(meta_path)
            slug = _slug(meta.get("slug"), meta_path)
            if slug in RESERVED_PAGE_SLUGS:
                _fail(meta_path, f"page slug {slug!r} is reserved by a generated route")
            if slug in seen:
                _fail(meta_path, f"duplicate page slug {slug!r}")
            seen.add(slug)
            fmt = _body_format(meta.get("body_format"), meta_path)
            draft = _bool(meta.get("draft"), meta_path, "draft")
            listed = _bool(meta.get("listed"), meta_path, "listed")
            if base.name == "_drafts" and (not draft or listed):
                _fail(meta_path, "pages in _drafts must be draft=true and listed=false")
            if base.name != "_drafts" and draft:
                _fail(meta_path, "draft pages must live in pages/_drafts")
            if slug == "now" and not draft and "date" not in meta:
                _fail(meta_path, "published Now page must have a date")
            publishable = listed and not draft
            title = _text(meta.get("title"), meta_path, "title")
            description = _text(meta.get("description"), meta_path, "description")
            if publishable:
                _check_unresolved_markers(meta_path, title, field="title")
                _check_unresolved_markers(meta_path, description, field="description")
            pages.append(
                Page(
                    slug=slug,
                    title=title,
                    description=description,
                    date=_date(meta["date"], meta_path) if "date" in meta else None,
                    listed=listed,
                    draft=draft,
                    body_format=fmt,
                    body=_load_body(meta_path, slug, fmt, published=publishable),
                )
            )
    return pages


def _load_note_like(root: pathlib.Path, dirname: str, label: str, cls):
    items = []
    items_root = root / dirname
    if not items_root.is_dir():
        _fail(items_root, f"missing {dirname} directory")
    seen: set[str] = set()
    for base in (items_root, items_root / "_drafts"):
        if not base.exists():
            continue
        for meta_path in sorted(base.glob("*.toml")):
            meta = _read_toml(meta_path)
            slug = _slug(meta.get("slug"), meta_path)
            if slug in seen:
                _fail(meta_path, f"duplicate {label} slug {slug!r}")
            seen.add(slug)
            fmt = _body_format(meta.get("body_format"), meta_path)
            draft = _bool(meta.get("draft"), meta_path, "draft")
            listed = _bool(meta.get("listed"), meta_path, "listed")
            if base.name == "_drafts" and (not draft or listed):
                _fail(meta_path, f"{label}s in _drafts must be draft=true and listed=false")
            if base.name != "_drafts" and (draft or not listed):
                _fail(meta_path, f"published {label}s must be draft=false and listed=true")
            title = _text(meta.get("title"), meta_path, "title")
            description = _text(meta.get("description"), meta_path, "description")
            if listed and not draft:
                _check_unresolved_markers(meta_path, title, field="title")
                _check_unresolved_markers(meta_path, description, field="description")
            items.append(cls(slug=slug, title=title, description=description, date=_date(meta.get("date"), meta_path), draft=draft, listed=listed, body_format=fmt, body=_load_body(meta_path, slug, fmt, published=listed and not draft), source_dir=base))
    return items


def _load_notes(root: pathlib.Path) -> list[Note]:
    return _load_note_like(root, "notes", "note", Note)


def _load_wiki(root: pathlib.Path) -> list[WikiPage]:
    return _load_note_like(root, "wiki", "wiki page", WikiPage)

def _load_projects(root: pathlib.Path) -> list[dict]:
    path = root / "projects.toml"
    data = _read_toml(path)
    projects = data.get("projects")
    if not isinstance(projects, list):
        _fail(path, "missing [[projects]] table")
    seen: set[str] = set()
    for project in projects:
        if not isinstance(project, dict):
            _fail(path, "project entries must be tables")
        p = _slug(project.get("path"), path, "path")
        if p in seen:
            _fail(path, f"duplicate project path {p!r}")
        if p in RESERVED_PROJECT_PATHS:
            _fail(path, f"project path {p!r} is reserved by the site")
        seen.add(p)
        _published_text(project.get("name"), path, "name")
        _published_text(project.get("description"), path, "description")
        _url(project.get("repo"), path, "repo", root_relative=False)
        tier = _text(project.get("tier"), path, "tier")
        if tier not in TIERS:
            _fail(path, f"project {p!r} has invalid tier {tier!r}")
        if "downloads" not in project:
            _fail(path, f"project {p!r} missing required boolean field 'downloads'")
        if "extra_links" not in project:
            _fail(path, f"project {p!r} missing required list field 'extra_links'")
        project.setdefault("listed", True)
        project.setdefault("card", {})
        if not isinstance(project["downloads"], bool) or not isinstance(project["listed"], bool):
            _fail(path, f"project {p!r} downloads/listed must be booleans")
        if not isinstance(project["extra_links"], list) or not isinstance(project["card"], dict):
            _fail(path, f"project {p!r} extra_links/card have invalid shape")
        for link in project["extra_links"]:
            if not isinstance(link, dict):
                _fail(path, f"project {p!r} extra_links entries must be tables")
            _published_text(link.get("label"), path, "extra_links.label")
            _url(link.get("url"), path, "extra_links.url")
        for key, allowed in (
            ("development", DEVELOPMENT_STATES),
            ("maturity", MATURITY_STATES),
            ("use", USE_SIGNALS),
            ("origin", ORIGINS),
        ):
            if key in project:
                value = _text(project.get(key), path, key)
                if value not in allowed:
                    _fail(path, f"project {p!r} has invalid {key} {value!r}; expected one of {sorted(allowed)}")

        # featured_projects owns homepage order; tier mirrors selection only as
        # transitional compatibility. Optional Markdown is project-page prose.
        body_path = root / "projects" / f"{p}.md"
        if body_path.exists():
            body = body_path.read_text()
            _check_published_body(body_path, body)
            project["body"] = body
            project["body_format"] = "markdown"
    return projects


def _load_home(root: pathlib.Path) -> str:
    path = root / "home.md"
    if not path.is_file():
        _fail(path, "missing homepage Markdown body")
    body = path.read_text()
    _check_published_body(path, body)
    return body


def _load_links(site: dict, site_path: pathlib.Path, key: str) -> None:
    links = site.get(key)
    if not isinstance(links, list):
        _fail(site_path, f"missing [[site.{key}]] tables")
    for link in links:
        if not isinstance(link, dict):
            _fail(site_path, f"site.{key} entries must be tables")
        _published_text(link.get("label"), site_path, f"{key}.label")
        _url(link.get("url"), site_path, f"{key}.url")


def _validate_featured(site: dict, projects: list[dict], site_path: pathlib.Path) -> None:
    featured = site.get("featured_projects")
    if not isinstance(featured, list) or not featured:
        _fail(site_path, "featured_projects must be a non-empty list")
    if any(not isinstance(path, str) for path in featured):
        _fail(site_path, "featured_projects entries must be project paths")
    if len(featured) != len(set(featured)):
        _fail(site_path, "featured_projects must not contain duplicates")
    by_path = {project["path"]: project for project in projects}
    for project_path in featured:
        if project_path not in by_path:
            _fail(site_path, f"featured project {project_path!r} is not in projects.toml")
        project = by_path[project_path]
        if not project.get("listed", True):
            _fail(site_path, f"featured project {project_path!r} must be listed")
        for key in ("development", "origin"):
            if key not in project:
                _fail(site_path, f"featured project {project_path!r} must declare {key}")
    tier_featured = {project["path"] for project in projects if project["tier"] == "featured"}
    if tier_featured != set(featured):
        _fail(site_path, "legacy tier=featured projects must exactly match featured_projects")


def _validate_route_collisions(projects: list[dict], pages: list[Page], projects_path: pathlib.Path) -> None:
    page_slugs = {page.slug for page in pages}
    collisions = sorted(project["path"] for project in projects if project["path"] in page_slugs)
    if collisions:
        _fail(projects_path, f"project paths collide with pages: {', '.join(collisions)}")


def load_site_data(repo: pathlib.Path | str) -> SiteData:
    root = pathlib.Path(repo) / "site-data"
    site_path = root / "site.toml"
    site = _read_toml(site_path).get("site")
    if not isinstance(site, dict):
        _fail(site_path, "missing [site] table")
    _text(site.get("domain"), site_path, "domain")
    for key in ("title", "name", "description"):
        _published_text(site.get(key), site_path, key)
    if "tagline" in site:
        _published_text(site.get("tagline"), site_path, "tagline")
    _load_links(site, site_path, "profile_links")
    _load_links(site, site_path, "utility_links")
    projects = _load_projects(root)
    pages = _load_pages(root)
    _validate_featured(site, projects, site_path)
    _validate_route_collisions(projects, pages, root / "projects.toml")
    return SiteData(site=site, home_body=_load_home(root), projects=projects, pages=pages, notes=_load_notes(root), wiki=_load_wiki(root))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate canonical site data")
    args = parser.parse_args()
    if not args.check:
        parser.print_help()
        return
    repo = repo_root()
    try:
        data = load_site_data(repo)
    except SiteDataError as error:
        raise SystemExit(f"error: {error}") from error
    print(f"ok: {len(data.projects)} projects, {len(data.pages)} pages, {len(data.notes)} notes, {len(data.wiki)} wiki pages")


if __name__ == "__main__":
    main()
