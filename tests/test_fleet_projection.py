from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from averagechris_site.fleet import acquire_fleet_data, load_fleet  # noqa: E402


class FleetProjectionTests(unittest.TestCase):
    def test_checked_in_projection_has_only_site_fields(self) -> None:
        fleet = load_fleet(ROOT)
        self.assertTrue(fleet)
        allowed = {"name", "pages_subdir", "srht_repo", "artifact_prefix", "binaries", "provider", "github_repo", "expected_platforms"}
        self.assertTrue(all(set(row) <= allowed for row in fleet.values()))

    def test_operational_field_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "fleet-site.toml").write_text(
                '[[repos]]\nname="x"\npages_subdir="x"\nsrht_repo="x"\nartifact_prefix="x"\nlocal="/secret/path"\n'
            )
            with self.assertRaises(SystemExit):
                load_fleet(root)

    def test_github_projection_without_srht_repo_acquires_optional_docs_and_wiki(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "fleet-site.toml").write_text(
                '[[repos]]\nname="gander"\npages_subdir="gander"\n'
                'artifact_prefix="gander"\nprovider="github"\n'
                'github_repo="averagechris/gander"\n'
                'expected_platforms=["aarch64-darwin","x86_64-linux"]\n'
            )
            fleet = load_fleet(root)
            self.assertEqual(fleet["gander"]["github_repo"], "averagechris/gander")
            self.assertNotIn("srht_repo", fleet["gander"])

            def fetched(url: str, *, soft: bool = False) -> bytes | None:
                if url.endswith("docs/pages/overview.html"):
                    return b"<h1>Overview</h1>"
                if url.endswith("docs/wiki/index.toml"):
                    return b'[[pages]]\nslug="guide"\ntitle="Guide"\ndescription="A guide"\nfile="guide.md"\n'
                if url.endswith("docs/wiki/guide.md"):
                    return b"# Guide"
                return None

            config = {
                "projects": [{"path": "gander", "downloads": True, "description": "Gander"}],
                "wiki": [],
            }
            with mock.patch("averagechris_site.fleet.ls_remote", return_value=({"v1.0.0": "tag-sha"}, "main-sha")), \
                 mock.patch("averagechris_site.fleet.fetch", side_effect=fetched):
                result = acquire_fleet_data(root, config, root / "site", "https://example.test")

            project = result["projects"]["gander"]
            self.assertEqual(project["docs"], ["overview.html"])
            self.assertEqual(project["wiki"][0]["body"], "# Guide")
            self.assertEqual(project["wiki"][0]["project"], {"name": "gander", "pages_subdir": "gander"})

    def test_migrated_page_links_use_github_and_shared_tracker(self) -> None:
        template = (ROOT / "renderers/zola/templates/page.html").read_text()
        self.assertIn('https://github.com/{{ item.project.github_repo }}', template)
        self.assertIn('https://github.com/averagechris/fleet/issues', template)


if __name__ == "__main__":
    unittest.main()
