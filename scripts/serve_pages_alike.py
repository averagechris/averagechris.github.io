#!/usr/bin/env python3
"""Serve dist/site with SourceHut Pages-like headers and behavior."""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import mimetypes
import os
from pathlib import Path
from typing import BinaryIO


# Captured from SourceHut Pages on 2026-07-05. Re-capture with:
# curl -sI https://averagechris.srht.site/ | grep -i content-security-policy
SOURCEHUT_PAGES_CSP = "default-src 'self' data: blob:; script-src 'self' 'unsafe-eval' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; worker-src 'self' 'unsafe-eval' 'unsafe-inline' data: blob:; frame-src https:; img-src data: https:; media-src https:; object-src 'none'; sandbox allow-downloads allow-forms allow-modals allow-pointer-lock allow-popups allow-presentation allow-same-origin allow-scripts;"


PAGES_MIME_TYPES = {
    ".wasm": "application/wasm",
    ".json": "application/json",
    ".js": "text/javascript",
    ".html": "text/html; charset=utf-8",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".sha256": "text/plain",
    ".gz": "application/gzip",
    ".tgz": "application/gzip",
    ".tar": "application/octet-stream",
}


class PagesAlikeHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler with SourceHut Pages-like local QA behavior."""

    server_version = "PagesAlikeHTTP/0.1"

    def __init__(self, *args, directory: str, **kwargs):
        self.site_root = Path(directory).resolve()
        self.not_found_path = self._load_not_found_path(self.site_root)
        super().__init__(*args, directory=directory, **kwargs)

    def end_headers(self) -> None:
        self.send_header("Content-Security-Policy", SOURCEHUT_PAGES_CSP)
        self.send_header("access-control-allow-origin", "*")
        super().end_headers()

    def guess_type(self, path: str) -> str:
        suffixes = Path(path).suffixes
        if suffixes[-2:] == [".tar", ".gz"]:
            return "application/gzip"
        mime_type = PAGES_MIME_TYPES.get(Path(path).suffix.lower())
        if mime_type is not None:
            return mime_type
        return mimetypes.guess_type(path)[0] or "application/octet-stream"

    def list_directory(self, path: str) -> BinaryIO | None:
        self.send_pages_404()
        return None

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        if code == 404:
            self.send_pages_404()
            return
        super().send_error(code, message, explain)

    def send_pages_404(self) -> None:
        body = self._not_found_body()
        self.send_response(404, "Not Found")
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _not_found_body(self) -> bytes:
        if self.not_found_path is not None and self.not_found_path.is_file():
            return self.not_found_path.read_bytes()
        return b"<!doctype html><title>404 Not Found</title><h1>404 Not Found</h1>"

    @staticmethod
    def _load_not_found_path(site_root: Path) -> Path | None:
        config_path = site_root.parent / "siteconfig.json"
        if not config_path.is_file():
            config_path = site_root / "siteconfig.json"
        if not config_path.is_file():
            return site_root / "404.html"
        try:
            site_config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return site_root / "404.html"
        not_found = site_config.get("notFound")
        if not isinstance(not_found, str) or not_found.startswith("/"):
            return site_root / "404.html"
        candidate = (site_root / not_found).resolve()
        try:
            candidate.relative_to(site_root)
        except ValueError:
            return site_root / "404.html"
        return candidate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve a static site like SourceHut Pages")
    parser.add_argument("root", help="static site root, usually dist/site")
    parser.add_argument("port", nargs="?", type=int, default=8000, help="port to listen on (default: 8000)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"missing site root: {root}")

    handler = functools.partial(PagesAlikeHandler, directory=os.fspath(root))
    with http.server.ThreadingHTTPServer(("", args.port), handler) as httpd:
        print(f"Serving {root} at http://localhost:{args.port}/")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
