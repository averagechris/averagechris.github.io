#!/usr/bin/env python3
"""Compare two rendered static site trees structurally.

This intentionally avoids byte-for-byte HTML comparison so renderer swaps can be
validated while preserving URL coverage, page semantics, and downloadable asset
integrity.
"""

from __future__ import annotations

import argparse
import contextlib
import html.parser
import json
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse


VOLATILE_FILE_NAMES = {"state.json"}
SAME_ORIGIN_HOSTS = {"averagechris.srht.site"}
VOLATILE_TEXT_PATTERNS = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}[T ][0-9:.+-]+Z?\b"),
    re.compile(r"\b(?:build|built|generated|updated)(?: at| on|:)?\s+[^<\n]{0,80}\d{4}-\d{2}-\d{2}[^<\n]*", re.I),
]
WS_RE = re.compile(r"\s+")
SHA_RE = re.compile(r"^[0-9a-fA-F]{64}(?:\s|$)")
DOWNLOAD_EXTS = {".tar", ".tgz", ".gz", ".bz2", ".xz", ".zip", ".whl"}
ASSET_EXTS = {".css", ".js", ".wasm", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".txt", ".xml"}


def norm_ws(value: str) -> str:
    return WS_RE.sub(" ", value).strip()


def scrub_volatile(value: str) -> str:
    for pattern in VOLATILE_TEXT_PATTERNS:
        value = pattern.sub("<volatile>", value)
    return value


def category(path: str) -> str:
    suffixes = PurePosixPath(path).suffixes
    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".html":
        return "html page"
    if suffix == ".sha256":
        return ".sha256"
    if suffix in DOWNLOAD_EXTS or any(".tar" == s.lower() for s in suffixes):
        return "download tarball"
    if suffix == ".json":
        return "json"
    if suffix in ASSET_EXTS:
        return "asset"
    return "other"


def iter_files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def normalize_internal_href(href: str, page: str) -> str | None:
    parsed = urlparse(href)
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc and parsed.netloc.lower() not in SAME_ORIGIN_HOSTS:
        return None
    base = "/" + str(PurePosixPath(page).parent) + "/"
    if base == "/./":
        base = "/"
    joined = urlparse(urljoin(base, urlunparse(("", "", parsed.path, parsed.params, parsed.query, ""))))
    path = joined.path or "/"
    if path.endswith("/index.html"):
        path = path[: -len("index.html")]
    elif path.endswith("index.html"):
        path = path[: -len("index.html")]
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse(("", "", path or "/", "", joined.query, ""))


class PageParser(html.parser.HTMLParser):
    def __init__(self, page: str, ignore_volatile: bool) -> None:
        super().__init__(convert_charrefs=True)
        self.page = page
        self.ignore_volatile = ignore_volatile
        self.title = ""
        self.meta_description = ""
        self.canonical = ""
        self.headings: dict[str, set[str]] = {"h1": set(), "h2": set(), "h3": set()}
        self.internal_links: set[str] = set()
        self.external_links: set[str] = set()
        self.visible_chunks: list[str] = []
        self._stack: list[str] = []
        self._capture: str | None = None
        self._buf: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs = {k.lower(): (v or "") for k, v in attrs_list}
        self._stack.append(tag)
        if tag in {"script", "style", "noscript", "template", "svg"}:
            self._hidden_depth += 1
        if tag == "title" or tag in self.headings:
            self._capture = tag
            self._buf = []
        if tag == "meta" and attrs.get("name", "").lower() == "description":
            self.meta_description = norm_ws(attrs.get("content", ""))
        if tag == "link" and attrs.get("rel", "").lower() == "canonical":
            self.canonical = norm_ws(attrs.get("href", ""))
        if tag == "a" and attrs.get("href"):
            href = attrs["href"].strip()
            parsed = urlparse(href)
            if parsed.scheme in {"http", "https"} and parsed.netloc and parsed.netloc.lower() not in SAME_ORIGIN_HOSTS:
                self.external_links.add(urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path or "/", parsed.params, parsed.query, "")))
            else:
                norm = normalize_internal_href(href, self.page)
                if norm:
                    self.internal_links.add(norm)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._capture == tag:
            text = norm_ws("".join(self._buf))
            if self.ignore_volatile:
                text = scrub_volatile(text)
            if tag == "title":
                self.title = text
            elif tag in self.headings and text:
                self.headings[tag].add(text)
            self._capture = None
            self._buf = []
        if tag in {"script", "style", "noscript", "template", "svg"} and self._hidden_depth:
            self._hidden_depth -= 1
        with contextlib.suppress(ValueError):
            i = len(self._stack) - 1 - self._stack[::-1].index(tag)
            del self._stack[i:]

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buf.append(data)
        if self._hidden_depth == 0:
            text = norm_ws(data)
            if text:
                if self.ignore_volatile:
                    text = scrub_volatile(text)
                self.visible_chunks.append(text)

    def result(self) -> dict[str, Any]:
        text = norm_ws(" ".join(self.visible_chunks))
        return {
            "title": self.title,
            "meta_description": self.meta_description,
            "canonical": self.canonical,
            "headings": {k: sorted(v) for k, v in self.headings.items()},
            "internal_links": sorted(self.internal_links),
            "external_links": sorted(self.external_links),
            "visible_text_length": len(text),
        }


@dataclass
class Report:
    old_root: str
    new_root: str
    missing: dict[str, list[str]] = field(default_factory=dict)
    added: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)

    def fail(self, kind: str, path: str, detail: str, **extra: Any) -> None:
        self.failures.append({"kind": kind, "path": path, "detail": detail, **extra})


def parse_page(root: Path, rel: str, ignore_volatile: bool) -> dict[str, Any]:
    parser = PageParser(rel, ignore_volatile)
    parser.feed((root / rel).read_text(encoding="utf-8", errors="replace"))
    parser.close()
    return parser.result()


def compare(old_root: Path, new_root: Path, tolerance: float, ignore_volatile: bool) -> Report:
    report = Report(str(old_root), str(new_root))
    old_files, new_files = iter_files(old_root), iter_files(new_root)
    for rel in sorted(old_files - new_files):
        cat = category(rel); report.missing.setdefault(cat, []).append(rel)
        if cat in {"html page", "download tarball", ".sha256"}:
            report.fail("missing", rel, f"missing from NEW ({cat})")
    for rel in sorted(new_files - old_files):
        cat = category(rel); report.added.setdefault(cat, []).append(rel)
        report.warnings.append(f"added in NEW ({cat}): {rel}")
    for rel in sorted(old_files & new_files):
        if ignore_volatile and PurePosixPath(rel).name in VOLATILE_FILE_NAMES:
            continue
        if rel.endswith(".html"):
            old, new = parse_page(old_root, rel, ignore_volatile), parse_page(new_root, rel, ignore_volatile)
            for key in ["title", "meta_description", "canonical"]:
                if old[key] != new[key]:
                    report.fail("html", rel, f"{key} differs", old=old[key], new=new[key])
            for h in ["h1", "h2", "h3"]:
                a, b = set(old["headings"][h]), set(new["headings"][h])
                if a != b:
                    report.fail("html", rel, f"{h} heading set differs", missing=sorted(a-b), added=sorted(b-a))
            for key in ["internal_links", "external_links"]:
                a, b = set(old[key]), set(new[key])
                if a != b:
                    report.fail("html", rel, f"{key} set differs", missing=sorted(a-b), added=sorted(b-a))
            olen, nlen = old["visible_text_length"], new["visible_text_length"]
            allowed = max(1, int(olen * tolerance))
            if abs(olen - nlen) > allowed:
                report.fail("html", rel, "visible text length outside tolerance", old=olen, new=nlen, tolerance=tolerance)
        else:
            old_bytes, new_bytes = (old_root / rel).read_bytes(), (new_root / rel).read_bytes()
            if old_bytes != new_bytes:
                report.fail("bytes", rel, f"non-HTML bytes differ ({category(rel)})", old_size=len(old_bytes), new_size=len(new_bytes))
    return report


def human(report: Report, verbose: bool) -> str:
    lines = [f"Compared {report.old_root} -> {report.new_root}"]
    lines.append(f"Missing: {sum(map(len, report.missing.values()))}; added: {sum(map(len, report.added.values()))}; warnings: {len(report.warnings)}; failures: {len(report.failures)}")
    for label, items in [("missing", report.missing), ("added", report.added)]:
        for cat, paths in sorted(items.items()):
            lines.append(f"  {label} {cat}: {len(paths)}")
    max_items = None if verbose else 25
    details = report.failures + ([{"kind": "warning", "path": "", "detail": w} for w in report.warnings])
    for item in details[:max_items]:
        loc = f" {item['path']}" if item.get("path") else ""
        lines.append(f"- {item['kind']}:{loc}: {item['detail']}")
        for key in ["old", "new", "missing", "added", "old_size", "new_size"]:
            if key in item:
                lines.append(f"    {key}: {item[key]}")
    if max_items is not None and len(details) > max_items:
        lines.append(f"... {len(details) - max_items} more; rerun with --verbose")
    return "\n".join(lines)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def self_test() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); a = root / "a"; b = root / "b"
        html = """<html><head><title>Home</title><meta name=description content="Desc"><link rel=canonical href="https://averagechris.srht.site/"></head><body><h1>Hi</h1><h2>Two</h2><a href="/x/#frag">x</a><a href="rel/index.html">r</a><a href="https://example.com/a#z">e</a><p>Generated at 2026-07-05T12:00:00Z words here.</p></body></html>"""
        write(a / "index.html", html); write(b / "index.html", html.replace("12:00", "12:01"))
        (a / "pkg.tar.gz").write_bytes(b"abc"); (b / "pkg.tar.gz").write_bytes(b"abc")
        write(a / "pkg.sha256", "a" * 64 + "  pkg.tar.gz\n"); write(b / "pkg.sha256", "a" * 64 + "  pkg.tar.gz\n")
        write(a / "state.json", '{"built":"now-a"}\n'); write(b / "state.json", '{"built":"now-b"}\n')
        assert compare(a, b, 0.15, True).failures == []
        r = compare(a, b, 0.15, False); assert len(r.failures) == 1  # state bytes
        shutil.copytree(b, root / "c")
        (root / "c" / "index.html").write_text(html.replace("Two", "Too"), encoding="utf-8")
        (root / "c" / "pkg.sha256").write_text("short\n", encoding="utf-8")
        (root / "c" / "missing.html").write_text(html, encoding="utf-8")
        r = compare(a, root / "c", 0.15, True)
        assert any(f["detail"] == "h2 heading set differs" for f in r.failures)
        assert any(f["kind"] == "bytes" and f["path"] == "pkg.sha256" for f in r.failures)
        assert r.warnings
    print("self-test passed")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Structurally compare two rendered static site trees.")
    ap.add_argument("old_tree", nargs="?")
    ap.add_argument("new_tree", nargs="?")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("--ignore-volatile", action="store_true", help="ignore state.json and conservative timestamp/build-date text")
    ap.add_argument("--visible-text-tolerance", type=float, default=0.15, help="relative visible text length tolerance (default: 0.15)")
    ap.add_argument("--verbose", action="store_true", help="show all human-readable details")
    ap.add_argument("--self-test", action="store_true", help="run synthetic tests and exit")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.old_tree or not args.new_tree or args.visible_text_tolerance < 0:
        ap.print_usage(sys.stderr); return 2
    old_root, new_root = Path(args.old_tree), Path(args.new_tree)
    if not old_root.is_dir() or not new_root.is_dir():
        print("OLD_TREE and NEW_TREE must be directories", file=sys.stderr); return 2
    report = compare(old_root, new_root, args.visible_text_tolerance, args.ignore_volatile)
    if args.json:
        print(json.dumps({"old_root": report.old_root, "new_root": report.new_root, "missing": report.missing, "added": report.added, "warnings": report.warnings, "failures": report.failures, "equivalent": not report.failures}, indent=2, sort_keys=True))
    else:
        print(human(report, args.verbose))
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
