from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from averagechris_site.release_inventory import projected_releases  # noqa: E402


class MixedReleaseInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.row = {"name": "gander", "provider": "github", "sourcehut_through": "v0.8.1"}
        self.srht = {"tags": {"v0.8.0": "old", "v0.8.1": "boundary"}}

    def test_zero_published_github_releases_keeps_history(self) -> None:
        releases = projected_releases(
            self.row, self.srht,
            {"tags": {"v0.8.0": "old", "v0.8.1": "boundary"}, "published": []},
        )
        self.assertEqual([(r["tag"], r["provider"]) for r in releases],
                         [("v0.8.1", "sourcehut"), ("v0.8.0", "sourcehut")])
        self.assertEqual(releases[0]["tag_sha"], "boundary")

    def test_future_published_release_is_github_and_window_can_mix(self) -> None:
        releases = projected_releases(
            self.row, self.srht,
            {"tags": {"v0.8.0": "old", "v0.8.1": "boundary", "v0.8.2": "new"},
             "published": ["v0.8.2"]},
        )
        self.assertEqual([(r["tag"], r["provider"]) for r in releases[:3]],
                         [("v0.8.2", "github"), ("v0.8.1", "sourcehut"), ("v0.8.0", "sourcehut")])

    def test_mismatched_historical_identity_fails_closed(self) -> None:
        with self.assertRaisesRegex(SystemExit, "do not match"):
            projected_releases(self.row, self.srht,
                               {"tags": {"v0.8.0": "different", "v0.8.1": "boundary"}, "published": []})

    def test_no_boundary_keeps_published_github_behavior(self) -> None:
        releases = projected_releases(
            {"name": "gander", "provider": "github"}, None,
            {"tags": {"v0.8.1": "old", "v0.8.2": "new"}, "published": ["v0.8.2"]},
        )
        self.assertEqual([r["tag"] for r in releases], ["v0.8.2"])


if __name__ == "__main__":
    unittest.main()
