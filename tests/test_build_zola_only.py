from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from averagechris_site import build  # noqa: E402


class BuildRendererArgumentTests(unittest.TestCase):
    def test_rejects_renderer_option_with_separate_value(self) -> None:
        with self.assertRaisesRegex(SystemExit, "--renderer python is obsolete"):
            build.reject_obsolete_renderer_args(["--renderer", "python"])

    def test_rejects_renderer_option_with_equals_value(self) -> None:
        with self.assertRaisesRegex(SystemExit, "--renderer=zola is obsolete"):
            build.reject_obsolete_renderer_args(["--renderer=zola"])


if __name__ == "__main__":
    unittest.main()
