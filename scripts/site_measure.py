"""Opt-in, no-secrets timing and counters for the Pages refresh path."""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from collections.abc import Iterator


ENABLED = os.environ.get("SITE_REFRESH_MEASURE") == "1"
_lock = threading.Lock()
_counts: dict[str, int] = {}


def count(name: str, amount: int = 1) -> None:
    """Increment a preselected operational counter; never record input values."""
    if not ENABLED:
        return
    with _lock:
        _counts[name] = _counts.get(name, 0) + amount


@contextlib.contextmanager
def stage(name: str) -> Iterator[None]:
    """Emit one compact monotonic duration record plus counters changed in it."""
    if not ENABLED:
        yield
        return
    with _lock:
        before = dict(_counts)
    started = time.monotonic()
    try:
        yield
    finally:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        with _lock:
            changed = {
                key: value - before.get(key, 0)
                for key, value in sorted(_counts.items())
                if value != before.get(key, 0)
            }
        record: dict[str, object] = {"stage": name, "duration_ms": elapsed_ms}
        if changed:
            record["counts"] = changed
        print("SITE_MEASURE " + json.dumps(record, separators=(",", ":")), flush=True)


@contextlib.contextmanager
def operation(count_name: str, duration_name: str) -> Iterator[None]:
    """Count and time a repeated network operation in monotonic milliseconds."""
    if not ENABLED:
        yield
        return
    count(count_name)
    started = time.monotonic()
    try:
        yield
    finally:
        count(duration_name, round((time.monotonic() - started) * 1000))
