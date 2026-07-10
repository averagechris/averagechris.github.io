#!/usr/bin/env python3
"""Shared todo.sr.ht tracker label helpers for fleet tooling."""

from __future__ import annotations

import json
import pathlib
import re
import subprocess

UMBRELLA_TRACKER_URL = "https://todo.sr.ht/~averagechris/projects"
UMBRELLA_TRACKER = "~averagechris/projects"
REPO_LABEL_COLOR = "#268bd2"


def repo_label(name: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
        raise ValueError(f"invalid repo label name source: {name!r}")
    return f"repo:{name}"


def label_names_from_json(text: str) -> set[str]:
    payload = json.loads(text or "[]")
    if isinstance(payload, dict):
        for key in ("items", "results", "labels", "data"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        raise ValueError("srht labels JSON was not a list or known envelope")
    names: set[str] = set()
    for item in payload:
        if isinstance(item, str):
            names.add(item)
        elif isinstance(item, dict) and isinstance(item.get("name"), str):
            names.add(item["name"])
    return names


def list_tracker_labels(*, srht_bin: str = "srht", tracker: str = UMBRELLA_TRACKER) -> set[str]:
    result = subprocess.run(
        [srht_bin, "todo", "labels", "list", "--json", "--all", "--tracker", tracker],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "srht todo labels list failed")
    return label_names_from_json(result.stdout)


def ensure_repo_label(
    name: str,
    *,
    srht_bin: str = "srht",
    tracker: str = UMBRELLA_TRACKER,
    dry_run: bool = False,
) -> tuple[bool, str]:
    """Ensure repo:<name> exists. Returns (created, label)."""

    label = repo_label(name)
    existing = list_tracker_labels(srht_bin=srht_bin, tracker=tracker)
    if label in existing:
        return False, label
    if dry_run:
        return False, label
    result = subprocess.run(
        [srht_bin, "todo", "labels", "create", "--tracker", tracker, "--color", REPO_LABEL_COLOR, label],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        # Idempotency guard for races: if another process created it between list and create, accept it.
        if label in list_tracker_labels(srht_bin=srht_bin, tracker=tracker):
            return False, label
        raise RuntimeError(result.stderr.strip() or "srht todo labels create failed")
    return True, label


def load_label_fixture(path: pathlib.Path) -> set[str]:
    return label_names_from_json(path.read_text())
