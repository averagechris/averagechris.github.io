#!/usr/bin/env python3
"""Compatibility wrapper for ``python3 -m averagechris_site.data``."""

from averagechris_site.data import main


if __name__ == "__main__":
    raise SystemExit(main())
