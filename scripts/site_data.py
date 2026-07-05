#!/usr/bin/env python3
"""Checked loader for renderer-agnostic site data."""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import re
import sys
import tomllib


class SiteDataError(ValueError):
    """Raised when canonical site data is invalid or ambiguous."""


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIERS = {"featured", "more"}
BODY_FORMATS = {"markdown", "html"}


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
class SiteData:
    site: dict
    projects: list[dict]
    pages: list[Page]
    notes: list[Note]


def _fail(path: pathlib.Path, message: str) -> "sys.NoReturn":
    raise SiteDataError(f"{path}: {message}")


def _text(value: object, path: pathlib.Path, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(path, f"missing required string field {key!r}")
    return value


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


def _load_body(meta_path: pathlib.Path, slug: str, body_format: str) -> str:
    suffix = ".md" if body_format == "markdown" else ".html"
    slug_body_path = meta_path.with_name(f"{slug}{suffix}")
    sidecar_body_path = meta_path.with_suffix(suffix)
    matches = [path for path in (slug_body_path, sidecar_body_path) if path.exists()]
    if not matches:
        _fail(meta_path, f"body file missing for slug {slug!r}")
    if len(set(matches)) > 1:
        _fail(meta_path, f"ambiguous body files for slug {slug!r}: {matches[0].name}, {matches[1].name}")
    body_path = matches[0]
    return body_path.read_text()


def _load_pages(root: pathlib.Path) -> list[Page]:
    pages_root = root / "pages"
    if not pages_root.is_dir():
        _fail(pages_root, "missing pages directory")
    pages: list[Page] = []
    seen: set[str] = set()
    for meta_path in sorted(pages_root.glob("*.toml")):
        meta = _read_toml(meta_path)
        slug = _slug(meta.get("slug"), meta_path)
        if slug in seen:
            _fail(meta_path, f"duplicate page slug {slug!r}")
        seen.add(slug)
        fmt = _body_format(meta.get("body_format"), meta_path)
        pages.append(
            Page(
                slug=slug,
                title=_text(meta.get("title"), meta_path, "title"),
                description=_text(meta.get("description"), meta_path, "description"),
                date=_date(meta["date"], meta_path) if "date" in meta else None,
                listed=_bool(meta.get("listed"), meta_path, "listed"),
                draft=_bool(meta.get("draft"), meta_path, "draft"),
                body_format=fmt,
                body=_load_body(meta_path, slug, fmt),
            )
        )
    return pages


def _load_notes(root: pathlib.Path) -> list[Note]:
    notes_root = root / "notes"
    if not notes_root.is_dir():
        _fail(notes_root, "missing notes directory")
    notes: list[Note] = []
    seen: set[str] = set()
    for base in (notes_root, notes_root / "_drafts"):
        if not base.exists():
            continue
        for meta_path in sorted(base.glob("*.toml")):
            meta = _read_toml(meta_path)
            slug = _slug(meta.get("slug"), meta_path)
            if slug in seen:
                _fail(meta_path, f"duplicate note slug {slug!r}")
            seen.add(slug)
            fmt = _body_format(meta.get("body_format"), meta_path)
            draft = _bool(meta.get("draft"), meta_path, "draft")
            listed = _bool(meta.get("listed"), meta_path, "listed")
            if base.name == "_drafts" and (not draft or listed):
                _fail(meta_path, "notes in _drafts must be draft=true and listed=false")
            if base.name != "_drafts" and (draft or not listed):
                _fail(meta_path, "published notes must be draft=false and listed=true")
            notes.append(
                Note(
                    slug=slug,
                    title=_text(meta.get("title"), meta_path, "title"),
                    description=_text(meta.get("description"), meta_path, "description"),
                    date=_date(meta.get("date"), meta_path),
                    draft=draft,
                    listed=listed,
                    body_format=fmt,
                    body=_load_body(meta_path, slug, fmt),
                    source_dir=base,
                )
            )
    return notes


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
        seen.add(p)
        for key in ("name", "description", "repo"):
            _text(project.get(key), path, key)
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
            _text(link.get("label"), path, "extra_links.label")
            _text(link.get("url"), path, "extra_links.url")
    return projects


def load_site_data(repo: pathlib.Path | str) -> SiteData:
    root = pathlib.Path(repo) / "site-data"
    site_path = root / "site.toml"
    site = _read_toml(site_path).get("site")
    if not isinstance(site, dict):
        _fail(site_path, "missing [site] table")
    for key in ("domain", "title", "name", "about"):
        _text(site.get(key), site_path, key)
    return SiteData(site=site, projects=_load_projects(root), pages=_load_pages(root), notes=_load_notes(root))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate canonical site data")
    args = parser.parse_args()
    if not args.check:
        parser.print_help()
        return
    repo = pathlib.Path(__file__).resolve().parent.parent
    try:
        data = load_site_data(repo)
    except SiteDataError as error:
        raise SystemExit(f"error: {error}") from error
    print(f"ok: {len(data.projects)} projects, {len(data.pages)} pages, {len(data.notes)} notes")


if __name__ == "__main__":
    main()
