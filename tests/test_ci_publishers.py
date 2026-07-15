import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class PublisherManifestTests(unittest.TestCase):
    def test_only_pages_manifest_automatically_publishes_main(self) -> None:
        automatic = []
        for manifest in (ROOT / ".builds").glob("*.yml"):
            text = manifest.read_text()
            if re.search(r"^submitter:\s*$", text, re.MULTILINE) and re.search(
                r"^\s+- refs/heads/main\s*$", text, re.MULTILINE
            ):
                automatic.append(manifest.name)

        self.assertEqual(automatic, ["pages.yml"])

        pages = (ROOT / ".builds" / "pages.yml").read_text()
        refresh = (ROOT / "builds/refresh-pages.yml").read_text()

        self.assertIn("nix run .#refresh-pages -- --force", pages)
        self.assertIn("nix run .#refresh-pages", refresh)

    def test_benchmarks_cannot_publish_or_receive_secrets(self) -> None:
        forbidden = ("oauth:", "secrets:", "pages publish", "artifact upload", "builds submit", "submitter:")
        manifests = sorted((ROOT / "builds").glob("benchmark-*.yml"))
        self.assertEqual([manifest.name for manifest in manifests], ["benchmark-cold.yml", "benchmark-warm.yml"])
        for manifest in manifests:
            text = manifest.read_text()
            for pattern in forbidden:
                self.assertNotIn(pattern, text, f"{manifest.name} contains {pattern}")
            for line in text.splitlines():
                if "nix run .#refresh-pages" in line:
                    self.assertIn("--no-publish", line)


if __name__ == "__main__":
    unittest.main()
