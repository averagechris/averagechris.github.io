from __future__ import annotations

import pathlib
import json
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from averagechris_site.release_inventory import projected_releases  # noqa: E402
from averagechris_site import fleet  # noqa: E402


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

    def test_github_only_historical_tag_is_not_projected(self) -> None:
        releases = projected_releases(
            self.row, self.srht,
            {"tags": {"v0.7.0": "github-only", "v0.8.0": "old", "v0.8.1": "boundary"},
             "published": []},
        )
        self.assertNotIn("v0.7.0", [r["tag"] for r in releases])

    def test_no_boundary_keeps_published_github_behavior(self) -> None:
        releases = projected_releases(
            {"name": "gander", "provider": "github"}, None,
            {"tags": {"v0.8.1": "old", "v0.8.2": "new"}, "published": ["v0.8.2"]},
        )
        self.assertEqual([r["tag"] for r in releases], ["v0.8.2"])


class BareFleetReleaseInventoryTests(unittest.TestCase):
    @staticmethod
    def github_refs() -> str:
        return "\n".join([
            "history-commit\trefs/tags/v0.8.1",
            "future-lightweight\trefs/tags/v0.8.2",
            "future-tag\trefs/tags/v0.8.3",
            "future-commit\trefs/tags/v0.8.3^{}",
            "main\trefs/heads/main",
        ])

    @staticmethod
    def releases() -> str:
        return json.dumps([
            {"tag_name": "v0.8.3", "draft": False},
            {"tag_name": "v0.8.2", "draft": False},
        ])

    def test_boundary_preserves_lightweight_history_and_only_accepts_annotated_future(self) -> None:
        row = {"name": "gander", "provider": "github", "github_repo": "averagechris/gander",
               "srht_repo": "gander", "sourcehut_through": "v0.8.1"}
        sourcehut_refs = "history-commit\trefs/tags/v0.8.1\nsrht-main\trefs/heads/main\n"
        with mock.patch.object(fleet, "run_text", side_effect=[self.github_refs(), self.releases(), sourcehut_refs]):
            releases, main = fleet.release_inventory(row)
        self.assertEqual(main, "main")
        self.assertEqual([(r["tag"], r["provider"]) for r in releases],
                         [("v0.8.3", "github"), ("v0.8.1", "sourcehut")])
        self.assertEqual(releases[1]["tag_sha"], "history-commit")

    def test_no_boundary_rejects_published_lightweight_release(self) -> None:
        row = {"name": "gander", "provider": "github", "github_repo": "averagechris/gander"}
        with mock.patch.object(fleet, "run_text", side_effect=[self.github_refs(), self.releases()]):
            releases, _ = fleet.release_inventory(row)
        self.assertEqual([r["tag"] for r in releases], ["v0.8.3"])


if __name__ == "__main__":
    unittest.main()
