#!/usr/bin/env python3
"""Compatibility wrapper for ``python3 -m averagechris_site.compare``."""

import sys

from averagechris_site.compare import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
