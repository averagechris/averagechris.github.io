from __future__ import annotations

import pathlib


def repo_root() -> pathlib.Path:
    """Return the repository root from inside the scripts package."""

    return pathlib.Path(__file__).resolve().parents[2]
