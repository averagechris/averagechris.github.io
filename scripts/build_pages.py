#!/usr/bin/env python3
"""Compatibility wrapper for ``python3 -m averagechris_site.build``."""

from averagechris_site.build import main


if __name__ == "__main__":
    raise SystemExit(main())
