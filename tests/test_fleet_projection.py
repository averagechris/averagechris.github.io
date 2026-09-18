from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from averagechris_site.fleet import load_fleet  # noqa: E402


class FleetProjectionTests(unittest.TestCase):
    def test_checked_in_projection_has_only_site_fields(self) -> None:
        fleet = load_fleet(ROOT)
        self.assertTrue(fleet)
        allowed = {"name", "pages_subdir", "srht_repo", "artifact_prefix", "binaries"}
        self.assertTrue(all(set(row) <= allowed for row in fleet.values()))

    def test_operational_field_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "fleet-site.toml").write_text(
                '[[repos]]\nname="x"\npages_subdir="x"\nsrht_repo="x"\nartifact_prefix="x"\nlocal="/secret/path"\n'
            )
            with self.assertRaises(SystemExit):
                load_fleet(root)


if __name__ == "__main__":
    unittest.main()
