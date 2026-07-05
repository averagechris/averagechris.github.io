#!/usr/bin/env python3
"""Manage local notes for averagechris.srht.site."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import shutil
import subprocess
import sys


DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")
SLUG_RE = re.compile(r"[^a-z0-9]+")


def repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent


def fail(message: str) -> "sys.NoReturn":
    raise SystemExit(f"error: {message}")


def slugify(value: str) -> str:
    slug = SLUG_RE.sub("-", value.lower()).strip("-")
    if not slug:
        fail("title did not produce a usable slug")
    return slug


def notes_dir() -> pathlib.Path:
    return repo_root() / "site-data" / "notes"


def drafts_dir() -> pathlib.Path:
    return notes_dir() / "_drafts"


def today() -> str:
    return dt.date.today().isoformat()


def new_note(args: argparse.Namespace) -> None:
    slug = args.slug or slugify(args.title)
    meta_path = drafts_dir() / f"{today()}-{slug}.toml"
    body_path = drafts_dir() / f"{today()}-{slug}.md"
    if meta_path.exists() or body_path.exists():
        fail(f"refusing to overwrite {meta_path} / {body_path}")
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        f'slug = "{slug}"\n'
        f'title = "{args.title.replace(chr(34), chr(92)+chr(34))}"\n'
        f'description = "draft note"\n'
        f'date = "{today()}"\n'
        'listed = false\n'
        'draft = true\n'
        'body_format = "markdown"\n'
    )
    body_path.write_text("\n")
    print(body_path)


def list_drafts(args: argparse.Namespace) -> None:
    del args
    root = drafts_dir()
    if not root.is_dir():
        print("no drafts")
        return
    drafts = sorted(path for path in root.glob("*.md") if path.is_file())
    if not drafts:
        print("no drafts")
        return
    for path in drafts:
        print(path)


def resolve_draft(name: str) -> pathlib.Path:
    candidate = pathlib.Path(name)
    candidates = []
    if candidate.is_absolute() or candidate.parent != pathlib.Path("."):
        candidates.append(candidate)
    else:
        candidates.append(drafts_dir() / candidate)
        if candidate.suffix != ".md":
            candidates.append(drafts_dir() / f"{candidate}.md")

    for path in candidates:
        if path.exists() and path.is_file():
            return path
    fail(f"draft not found: {name}")


def publish(args: argparse.Namespace) -> None:
    draft = resolve_draft(args.name)
    filename = draft.name
    if not DATE_PREFIX_RE.match(filename):
        filename = f"{today()}-{filename}"
    destination = notes_dir() / filename
    meta = draft.with_suffix(".toml")
    meta_destination = destination.with_suffix(".toml")
    if destination.exists() or meta_destination.exists():
        fail(f"refusing to overwrite {destination} / {meta_destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(draft), destination)
    if meta.exists():
        text = meta.read_text().replace("draft = true", "draft = false").replace("listed = false", "listed = true")
        meta_destination.write_text(text)
        meta.unlink()
    print(destination)
    print("review, commit, and push when ready")


def cell_value(value: object) -> object:
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def run_ctx_sql(sql: str, *, max_rows: int) -> list[dict[str, object]]:
    command = [
        "ctx",
        "sql",
        "--format",
        "json",
        "--max-rows",
        str(max_rows),
        "--max-value-bytes",
        "4000",
        sql,
    ]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        fail("ctx not found on PATH")
    if result.returncode != 0:
        fail(f"ctx sql failed: {result.stderr.strip() or result.stdout.strip()}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        fail(f"ctx sql returned invalid JSON: {error}")

    rows = []
    for row in payload.get("rows", []):
        if isinstance(row, dict):
            rows.append({key: cell_value(value) for key, value in row.items()})
        elif isinstance(row, list):
            rows.append({str(index): cell_value(value) for index, value in enumerate(row)})
    return rows


def metadata_workspace(provider: str, metadata_json: object) -> str:
    try:
        metadata = json.loads(str(metadata_json or "{}"))
    except json.JSONDecodeError:
        return provider
    source_path = metadata.get("source_path") if isinstance(metadata, dict) else None
    if not source_path:
        return provider
    path = pathlib.Path(str(source_path))
    parts = [part for part in path.parts if part not in ("/", "Users", "chris", "projects", ".maint")]
    if parts:
        return parts[-1]
    return path.name or provider


def find_text(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            decoded = None
        if decoded is not None and decoded != value:
            found = find_text(decoded)
            if found:
                return found
        return value
    if isinstance(value, dict):
        for key in ("text", "content", "message", "prompt", "json"):
            found = find_text(value.get(key))
            if found:
                return found
        for nested in value.values():
            found = find_text(nested)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = find_text(item)
            if found:
                return found
    return None


def first_user_snippet(session_id: str) -> str:
    quoted = session_id.replace("'", "''")
    sql = (
        "SELECT payload_json FROM events "
        f"WHERE session_id='{quoted}' AND role='user' ORDER BY seq LIMIT 1"
    )
    try:
        rows = run_ctx_sql(sql, max_rows=1)
    except SystemExit:
        return ""
    if not rows:
        return ""
    payload = next(iter(rows[0].values()), "")
    try:
        decoded = json.loads(str(payload))
    except json.JSONDecodeError:
        decoded = payload
    text = find_text(decoded) or ""
    return re.sub(r"\s+", " ", text).strip()[:120]


def row_get(row: dict[str, object], name: str, index: int) -> object:
    return row.get(name, row.get(str(index), ""))


def distill(args: argparse.Namespace) -> None:
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=args.days)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    sql = (
        "SELECT id, provider, started_at_ms, metadata_json FROM sessions "
        "WHERE is_primary=1 "
        f"AND started_at_ms >= {cutoff_ms} "
        f"ORDER BY started_at_ms DESC LIMIT {args.limit}"
    )
    rows = run_ctx_sql(sql, max_rows=args.limit)
    path = drafts_dir() / f"distill-{today()}.md"
    if path.exists():
        fail(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)

    grouped: dict[str, list[str]] = {}
    for row in rows:
        session_id = str(row_get(row, "id", 0))
        provider = str(row_get(row, "provider", 1))
        started_at_ms = int(row_get(row, "started_at_ms", 2) or 0)
        metadata_json = row_get(row, "metadata_json", 3)
        workspace = metadata_workspace(provider, metadata_json)
        timestamp = dt.datetime.fromtimestamp(started_at_ms / 1000, dt.UTC).astimezone()
        snippet = first_user_snippet(session_id)
        heading = f"### {timestamp:%Y-%m-%d %H:%M} {provider}"
        if snippet:
            heading = f"{heading} — {snippet}"
        grouped.setdefault(workspace, []).append(
            f"{heading}\n\n"
            f"- session: `ctx show session {session_id}`\n"
            "- [ ] facts: (to be filled)\n"
        )

    lines = [
        f"# Distill digest {today()}",
        "",
        "<!-- DRAFT — not published. An agent replaces each stub below with",
        "TIL-worthy bullet facts (plain, specific, one line each), keeping the",
        "`ctx show session` reference. Chris reviews, edits, and publishes with:",
        "nix run .#note -- publish <file> -->",
        "",
    ]
    for workspace, stubs in grouped.items():
        lines.append(f"## {workspace}")
        lines.append("")
        lines.extend(stubs)
    path.write_text("\n".join(lines).rstrip() + "\n")
    slug = path.stem
    path.with_suffix(".toml").write_text(
        f'slug = "{slug}"\n'
        f'title = "Distill digest {today()}"\n'
        'description = "Unpublished distilled agent-session notes."\n'
        f'date = "{today()}"\n'
        'listed = false\n'
        'draft = true\n'
        'body_format = "markdown"\n'
    )
    print(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    new_parser = subparsers.add_parser("new")
    new_parser.add_argument("title")
    new_parser.add_argument("--slug")
    new_parser.set_defaults(func=new_note)

    drafts_parser = subparsers.add_parser("drafts")
    drafts_parser.set_defaults(func=list_drafts)

    publish_parser = subparsers.add_parser("publish")
    publish_parser.add_argument("name")
    publish_parser.set_defaults(func=publish)

    distill_parser = subparsers.add_parser("distill")
    distill_parser.add_argument("--days", type=int, default=7)
    distill_parser.add_argument("--limit", type=int, default=40)
    distill_parser.set_defaults(func=distill)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
