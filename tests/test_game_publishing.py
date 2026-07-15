from __future__ import annotations

from contextlib import nullcontext
import hashlib
import io
import json
import os
import pathlib
import shutil
import tarfile
import tempfile
import unittest
from unittest import mock

from averagechris_site.data import Game, SiteDataError, _load_games
from averagechris_site.fleet import acquire_game, ls_remote, parse_checksum, safe_extract_game
from averagechris_site.zola import build_template_data, render_zola_site
import refresh_pages


def write_tar(path: pathlib.Path, entries: list[tuple[str, bytes | None, str]]) -> None:
    with tarfile.open(path, "w") as archive:
        for name, body, kind in entries:
            info = tarfile.TarInfo(name)
            if kind == "dir":
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            elif kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = "index.html"
                archive.addfile(info)
            else:
                assert body is not None
                info.size = len(body)
                archive.addfile(info, io.BytesIO(body))


class GamesDataTests(unittest.TestCase):
    def test_loads_canonical_game(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "games.toml").write_text(
                '[[games]]\nslug="palabra"\nname="Palabra"\ndescription="Words"\n'
                'repo="https://git.sr.ht/~averagechris/palabra"\nsrht_repo="palabra"\n'
                'artifact_prefix="palabra"\nentrypoint="index.html"\nlisted=true\n'
            )
            game = _load_games(root)[0]
            self.assertEqual(game.slug, "palabra")
            self.assertEqual(game.entrypoint, "index.html")

    def test_rejects_unsafe_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "games.toml").write_text(
                '[[games]]\nslug="x"\nname="X"\ndescription="X"\nrepo="x"\n'
                'srht_repo="x"\nartifact_prefix="x"\nentrypoint="../index.html"\n'
            )
            with self.assertRaises(SiteDataError):
                _load_games(root)


class BundleTests(unittest.TestCase):
    def test_extracts_single_root_and_arbitrary_nested_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            archive = root / "game.tar"
            write_tar(archive, [
                ("palabra-v1.2.3-web/index.html", b"play", "file"),
                ("palabra-v1.2.3-web/pkg/palabra.js", b"js", "file"),
                ("palabra-v1.2.3-web/assets/data/words.json", b"[]", "file"),
            ])
            destination = root / "site" / "games" / "palabra"
            safe_extract_game(archive, destination, "index.html")
            self.assertEqual((destination / "index.html").read_text(), "play")
            self.assertEqual((destination / "assets/data/words.json").read_text(), "[]")

    def test_rejects_traversal_links_duplicates_and_missing_entrypoint(self) -> None:
        cases = [
            [("../index.html", b"x", "file")],
            [("/index.html", b"x", "file")],
            [("index.html", b"x", "file"), ("link", None, "symlink")],
            [("index.html", b"x", "file"), ("index.html", b"y", "file")],
            [("assets/game.js", b"x", "file")],
        ]
        for index, entries in enumerate(cases):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as tmp:
                root = pathlib.Path(tmp)
                archive = root / "bad.tar"
                write_tar(archive, entries)
                with self.assertRaises(SystemExit):
                    safe_extract_game(archive, root / "out", "index.html")

    def test_rejects_special_files_and_expanded_size_bombs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            special = root / "special.tar"
            with tarfile.open(special, "w") as archive:
                info = tarfile.TarInfo("index.html")
                info.type = tarfile.CHRTYPE
                archive.addfile(info)
            with self.assertRaises(SystemExit):
                safe_extract_game(special, root / "special-out", "index.html")

            oversized = root / "oversized.tar"
            write_tar(oversized, [("index.html", b"too large", "file")])
            with mock.patch("averagechris_site.fleet.MAX_GAME_BYTES", 1), self.assertRaises(SystemExit):
                safe_extract_game(oversized, root / "oversized-out", "index.html")

    def test_checksum_is_strict_and_names_artifact(self) -> None:
        digest = "a" * 64
        self.assertEqual(parse_checksum(f"{digest}  game.tar.gz\n".encode(), "game.tar.gz", "test"), digest)
        with self.assertRaises(SystemExit):
            parse_checksum(f"{digest}  other.tar.gz\n".encode(), "game.tar.gz", "test")
        with self.assertRaises(SystemExit):
            parse_checksum(b"not-a-digest\n", "game.tar.gz", "test")

    def test_acquires_verified_latest_semver_bundle_into_owned_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            archive_buffer = io.BytesIO()
            with tarfile.open(fileobj=archive_buffer, mode="w") as archive:
                body = b"play"
                info = tarfile.TarInfo("index.html")
                info.size = len(body)
                archive.addfile(info, io.BytesIO(body))
            archive_data = archive_buffer.getvalue()
            checksum = hashlib.sha256(archive_data).hexdigest()
            game = Game(
                slug="palabra", name="Palabra", description="Words", repo="repo",
                srht_repo="palabra", artifact_prefix="palabra", entrypoint="index.html", listed=True,
            )

            def fetched(url: str, *, soft: bool = False) -> bytes:
                if url.endswith(".sha256"):
                    return f"{checksum}  palabra-v1.2.3-web.tar.gz\n".encode()
                return archive_data

            with mock.patch("averagechris_site.fleet.ls_remote", return_value=(
                {"v1.1.0": "old", "v1.2.3": "tag-sha"}, "main-sha"
            )), mock.patch("averagechris_site.fleet.fetch", side_effect=fetched):
                result = acquire_game(root, game, root / "site")

            self.assertEqual(result["release"]["version"], "v1.2.3")
            self.assertEqual(result["state"]["tag_sha"], "tag-sha")
            self.assertEqual((root / "site/games/palabra/index.html").read_bytes(), b"play")


class RefreshTests(unittest.TestCase):
    def test_fingerprint_uses_only_canonical_site_projects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "site-data").mkdir()
            (root / "fleet.toml").write_text(
                '[[repos]]\nname="shown"\npages_subdir="shown"\nsrht_repo="shown"\n'
                '[[repos]]\nname="fleet-only"\npages_subdir="fleet-only"\nsrht_repo="fleet-only"\n'
            )
            (root / "site-data/projects.toml").write_text(
                '[[projects]]\npath="shown"\ndownloads=true\n'
            )
            (root / "site-data/games.toml").write_text("games=[]\n")
            refs = (["v1.0.0"], "v1.0.0", "main", {"v1.0.0": "tag"}, {})
            with mock.patch.object(refresh_pages, "publisher_revision", return_value="publisher"), \
                 mock.patch.object(refresh_pages, "ls_refs", return_value=refs) as ls_refs, \
                 mock.patch.object(refresh_pages, "probe", return_value=False):
                fingerprint, _ = refresh_pages.fingerprint(root)
            self.assertEqual(set(fingerprint), {"_publisher", "shown"})
            self.assertEqual([call.args[0] for call in ls_refs.call_args_list], ["shown"])

    def test_comparison_classifies_exact_palabra_main_sha_mismatch(self) -> None:
        current = {
            "_publisher": {"main_sha": "site"},
            "games/palabra": {"tag": "v1.0.0", "main_sha": "new", "artifacts": []},
        }
        live = refresh_pages.benchmark_live_fingerprint(current, "palabra-main-sha-mismatch")
        self.assertEqual(refresh_pages.classify_comparison(current, current), "unchanged")
        self.assertEqual(
            refresh_pages.classify_comparison(current, live),
            "games.palabra.main_sha-only",
        )

    def test_controlled_live_state_cannot_enable_publication(self) -> None:
        with mock.patch.object(refresh_pages, "fingerprint") as fingerprint, \
             self.assertRaises(SystemExit):
            refresh_pages.main(["--benchmark-live-state", "unchanged"])
        fingerprint.assert_not_called()

    def test_only_controlled_no_publish_benchmark_can_use_candidate_revision(self) -> None:
        fingerprint = {
            "_publisher": {"main_sha": "candidate"},
            "games/palabra": {"tag": "v1.0.0", "main_sha": "new", "artifacts": []},
        }
        refs = {"palabra": {"tags": {"v1.0.0": "tag"}, "main_sha": "new"}}
        with mock.patch.dict(os.environ, {"BENCH_EXPECTED_REVISION": "a" * 40}), \
             mock.patch.object(refresh_pages, "wait_for_trigger"), \
             mock.patch.object(refresh_pages, "fingerprint", return_value=(fingerprint, refs)) as fingerprint_call, \
             mock.patch.object(refresh_pages.site_measure, "stage", side_effect=lambda _name: nullcontext()):
            refresh_pages.main(["--no-publish", "--benchmark-live-state", "unchanged"])
        fingerprint_call.assert_called_once_with(
            mock.ANY,
            publisher_sha_override="a" * 40,
        )

    def test_controlled_mismatch_keeps_before_build_after_checks_and_cannot_publish(self) -> None:
        fingerprint = {
            "_publisher": {"main_sha": "site"},
            "games/palabra": {"tag": "v1.0.0", "main_sha": "new", "artifacts": []},
        }
        refs = {"palabra": {"tags": {"v1.0.0": "tag"}, "main_sha": "new"}}
        with mock.patch.dict(os.environ, {"BENCH_EXPECTED_REVISION": "a" * 40}), \
             mock.patch.object(refresh_pages, "wait_for_trigger"), \
             mock.patch.object(refresh_pages, "fingerprint", side_effect=[(fingerprint, refs), (fingerprint, refs)]) as fingerprint_call, \
             mock.patch.object(refresh_pages, "write_refs_json", return_value=pathlib.Path("refs.json")), \
             mock.patch.object(refresh_pages, "run") as run, \
             mock.patch.object(refresh_pages.site_measure, "stage", side_effect=lambda _name: nullcontext()):
            refresh_pages.main(["--no-publish", "--benchmark-live-state", "palabra-main-sha-mismatch"])
        self.assertEqual(fingerprint_call.call_count, 2)
        self.assertEqual(run.call_count, 1)
        self.assertIn("build_pages.py", run.call_args.args[0][1])

    def test_ls_refs_keeps_annotated_tag_object_and_peeled_commit(self) -> None:
        output = "main\trefs/heads/main\ntag-object\trefs/tags/v1.2.3\ncommit\trefs/tags/v1.2.3^{}\n"
        with mock.patch("refresh_pages.subprocess.check_output", return_value=output):
            refs = refresh_pages.ls_refs("palabra")
        self.assertEqual(refs[3]["v1.2.3"], "tag-object")
        self.assertEqual(refs[4]["v1.2.3"], "commit")

    def test_acquisition_uses_pinned_refresh_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            refs = pathlib.Path(tmp) / "refs.json"
            refs.write_text(json.dumps({"palabra": {"tags": {"v1.2.3": "tag-sha"}, "main_sha": "main-sha"}}))
            with mock.patch.dict(os.environ, {"FLEET_REFS_JSON": str(refs)}), \
                 mock.patch("averagechris_site.fleet.run_text") as run_text:
                self.assertEqual(ls_remote("palabra"), ({"v1.2.3": "tag-sha"}, "main-sha"))
            run_text.assert_not_called()

    def test_acquisition_never_falls_back_from_incomplete_pins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            refs = pathlib.Path(tmp) / "refs.json"
            refs.write_text("{}")
            with mock.patch.dict(os.environ, {"FLEET_REFS_JSON": str(refs)}), \
                 mock.patch("averagechris_site.fleet.run_text") as run_text, \
                 self.assertRaises(SystemExit):
                ls_remote("palabra")
            run_text.assert_not_called()

    def test_live_fingerprint_includes_game_namespace(self) -> None:
        state = {
            "publisher_sha": "site-main",
            "projects": {},
            "games": {"palabra": {"tag": "v1.2.3", "main_sha": "abc", "artifacts": [
                {"name": "palabra-v1.2.3-web.tar.gz", "version": "v1.2.3", "sha256": "a" * 64}
            ]}},
        }
        with mock.patch.object(refresh_pages, "live_state", return_value=state):
            self.assertEqual(
                refresh_pages.live_fingerprint("example.test")["games/palabra"]["artifacts"],
                [{"name": "palabra-v1.2.3-web.tar.gz", "sha256": "a" * 64}],
            )
            self.assertEqual(refresh_pages.live_fingerprint("example.test")["games/palabra"]["tag_sha"], "")
            self.assertEqual(refresh_pages.live_fingerprint("example.test")["_publisher"], {"main_sha": "site-main"})

    def test_publisher_revision_rejects_stale_checkout(self) -> None:
        with mock.patch.object(refresh_pages.subprocess, "check_output", return_value="local\n"), \
             mock.patch.object(refresh_pages, "ls_refs", return_value=([], "", "remote", {}, {})), \
             self.assertRaisesRegex(SystemExit, "is not current main"):
            refresh_pages.publisher_revision(pathlib.Path("."))

    def test_trigger_waits_for_game_artifact_and_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "fleet.toml").write_text("repos=[]\n")
            (root / "site-data").mkdir()
            (root / "site-data/games.toml").write_text(
                '[[games]]\nslug="palabra"\nsrht_repo="palabra"\nartifact_prefix="palabra"\n'
            )
            env = {"TRIGGER_PROJECT": "palabra", "TRIGGER_TAG": "v1.0.0", "TRIGGER_SHA": "commit"}
            with mock.patch.dict(os.environ, env, clear=False), \
                 mock.patch.object(refresh_pages, "ls_refs", return_value=(["v1.0.0"], "v1.0.0", "main", {"v1.0.0": "tag"}, {"v1.0.0": "commit"})), \
                 mock.patch.object(refresh_pages, "probe", return_value=True) as probe, \
                 mock.patch.object(refresh_pages, "checksum", return_value="a" * 64) as checksum:
                refresh_pages.wait_for_trigger(root)
            self.assertEqual(probe.call_count, 1)
            self.assertEqual(checksum.call_count, 1)

    def test_trigger_rejects_wrong_peeled_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "fleet.toml").write_text("repos=[]\n")
            (root / "site-data").mkdir()
            (root / "site-data/games.toml").write_text('[[games]]\nslug="palabra"\nsrht_repo="palabra"\nartifact_prefix="palabra"\n')
            env = {"TRIGGER_PROJECT": "palabra", "TRIGGER_TAG": "v1.0.0", "TRIGGER_SHA": "expected"}
            refs = (["v1.0.0"], "v1.0.0", "main", {"v1.0.0": "tag"}, {"v1.0.0": "wrong"})
            with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(refresh_pages, "ls_refs", return_value=refs), self.assertRaises(SystemExit):
                refresh_pages.wait_for_trigger(root)

    def test_trigger_requires_commit_pin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            with mock.patch.dict(os.environ, {"TRIGGER_PROJECT": "palabra", "TRIGGER_TAG": "v1.0.0"}, clear=True), self.assertRaises(SystemExit):
                refresh_pages.wait_for_trigger(root)


class RendererTests(unittest.TestCase):
    def test_game_index_uses_generated_release_contract(self) -> None:
        config = {
            "site": {"title": "Site", "about": "About."},
            "projects": [], "pages": [], "notes": [], "wiki": [],
        }
        game = {
            "slug": "palabra", "name": "Palabra", "description": "Words",
            "repo": "https://example.test/palabra", "listed": True,
            "published": True, "version": "v1.2.3", "play_url": "/games/palabra/",
        }
        data = build_template_data(config, "https://example.test", {"games": [game]})
        self.assertEqual(data["games"][0]["play_url"], "/games/palabra/")
        self.assertEqual(data["games"][0]["version"], "v1.2.3")

    @unittest.skipUnless(shutil.which("zola"), "zola is not on PATH")
    def test_zola_owns_index_but_not_extracted_game_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            site_dir = root / "site"
            route = site_dir / "games" / "palabra"
            route.mkdir(parents=True)
            (route / "index.html").write_text("game-owned")
            config = {
                "site": {"title": "Site", "name": "Chris", "about": "About.", "links": []},
                "projects": [], "pages": [], "notes": [], "wiki": [],
            }
            fleet = {"games": [{
                "slug": "palabra", "name": "Palabra", "description": "Words",
                "repo": "https://example.test/palabra", "listed": True,
                "published": True, "version": "v1.2.3", "play_url": "/games/palabra/",
            }]}
            render_zola_site(pathlib.Path(__file__).parents[1], config, site_dir, "https://example.test", fleet)
            self.assertIn("Palabra", (site_dir / "games/index.html").read_text())
            self.assertEqual((route / "index.html").read_text(), "game-owned")


if __name__ == "__main__":
    unittest.main()
