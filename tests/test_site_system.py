from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from averagechris_site.data import SiteDataError, UNRESOLVED_MARKERS, load_site_data
from averagechris_site.zola import build_template_data, render_zola_site


FEATURED = ["dotfiles", "gander", "sideshow", "workctl", "rdny"]


def as_config(loaded):
    return {
        "site": dict(loaded.site),
        "home_body": loaded.home_body,
        "projects": loaded.projects,
        "pages": loaded.pages,
        "notes": loaded.notes,
        "wiki": loaded.wiki,
    }


class SiteFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.tmp.name)
        shutil.copytree(ROOT / "site-data", self.repo / "site-data")

    def tearDown(self):
        self.tmp.cleanup()

    def path(self, relative: str) -> pathlib.Path:
        return self.repo / "site-data" / relative

    def publish_now(self, body: str = "A fixture Now entry.\n", *, listed: bool = True) -> None:
        draft_meta = self.path("pages/_drafts/now.toml")
        draft_body = self.path("pages/_drafts/now.md")
        draft_body.write_text(body)
        meta = draft_meta.read_text().replace("draft = true", "draft = false")
        if listed:
            meta = meta.replace("listed = false", "listed = true")
        draft_meta.replace(self.path("pages/now.toml"))
        self.path("pages/now.toml").write_text(meta)
        draft_body.replace(self.path("pages/now.md"))


class LoaderContractTests(SiteFixture):
    def test_home_markdown_identity_social_and_featured_lifecycle(self):
        loaded = load_site_data(self.repo)
        self.assertIn("I'm Chris.", loaded.home_body)
        self.assertEqual("Chris Cummings", loaded.site["name"])
        self.assertEqual("Chris Cummings's personal workshop, software, notes, and guides.", loaded.site["description"])
        self.assertEqual(FEATURED, loaded.site["featured_projects"])
        self.assertEqual(["sourcehut", "github", "bluesky"], [link["label"] for link in loaded.site["profile_links"]])
        self.assertEqual(
            [
                "https://sr.ht/~averagechris/",
                "https://github.com/averagechris",
                "https://bsky.app/profile/averagechris.bsky.social",
            ],
            [link["url"] for link in loaded.site["profile_links"]],
        )

        by_path = {project["path"]: project for project in loaded.projects}
        self.assertTrue(all(by_path[path]["development"] == "active" for path in FEATURED))
        self.assertEqual("experimental", by_path["workctl"]["maturity"])
        self.assertNotIn("use", by_path["workctl"])
        self.assertEqual(
            ["workctl"],
            [project["path"] for project in loaded.projects if project.get("maturity") == "experimental"],
        )
        self.assertTrue(all(by_path[path]["use"] == "dogfooded" for path in FEATURED if path != "workctl"))
        self.assertTrue(all(project.get("maturity") != "stable" for project in loaded.projects))

    def test_lifecycle_values_are_checked(self):
        replacements = {
            "development": ('development = "active"', 'development = "retired"'),
            "maturity": ('maturity = "experimental"', 'maturity = "probably-fine"'),
            "use": ('use = "dogfooded"', 'use = "sometimes"'),
            "origin": ('origin = "original"', 'origin = "unknown"'),
        }
        projects = self.path("projects.toml")
        original = projects.read_text()
        for field, (valid, invalid) in replacements.items():
            with self.subTest(field=field):
                projects.write_text(original.replace(valid, invalid, 1))
                with self.assertRaisesRegex(SiteDataError, f"invalid {field}"):
                    load_site_data(self.repo)
        projects.write_text(original)

    def test_featured_references_are_unique_and_checked(self):
        site = self.path("site.toml")
        site.write_text(site.read_text().replace('"rdny"]', '"dotfiles"]'))
        with self.assertRaisesRegex(SiteDataError, "must not contain duplicates"):
            load_site_data(self.repo)

    def test_featured_count_is_editorial_not_schema(self):
        site = self.path("site.toml")
        site.write_text(site.read_text().replace(', "rdny"', ""))
        projects = self.path("projects.toml")
        projects.write_text(projects.read_text().replace('path = "rdny"\nname = "rdny"\ndescription = "Chrome automation CLI in Rust, deeply inspired by rodney."\nrepo = "https://git.sr.ht/~averagechris/rdny"\ndownloads = true\ntier = "featured"', 'path = "rdny"\nname = "rdny"\ndescription = "Chrome automation CLI in Rust, deeply inspired by rodney."\nrepo = "https://git.sr.ht/~averagechris/rdny"\ndownloads = true\ntier = "more"'))
        loaded = load_site_data(self.repo)
        self.assertEqual(FEATURED[:-1], loaded.site["featured_projects"])

    def test_legacy_featured_tier_must_match_editorial_selection(self):
        projects = self.path("projects.toml")
        projects.write_text(projects.read_text().replace('path = "rdny"\nname = "rdny"\ndescription = "Chrome automation CLI in Rust, deeply inspired by rodney."\nrepo = "https://git.sr.ht/~averagechris/rdny"\ndownloads = true\ntier = "featured"', 'path = "rdny"\nname = "rdny"\ndescription = "Chrome automation CLI in Rust, deeply inspired by rodney."\nrepo = "https://git.sr.ht/~averagechris/rdny"\ndownloads = true\ntier = "more"'))
        with self.assertRaisesRegex(SiteDataError, "tier=featured projects must exactly match"):
            load_site_data(self.repo)

    def test_optional_project_body_uses_markdown_and_description_fallback(self):
        projects = self.path("projects")
        (projects / "gander.md").write_text("Approved **editorial** copy.\n")
        loaded = load_site_data(self.repo)
        by_path = {project["path"]: project for project in loaded.projects}
        self.assertEqual("Approved **editorial** copy.\n", by_path["gander"]["body"])
        self.assertNotIn("body", by_path["dotfiles"])

        data = build_template_data(as_config(loaded), "https://example.test", {})
        gander = next(project for project in data["featured_projects"] if project["path"] == "gander")
        self.assertEqual(by_path["gander"]["description"], gander["description"])

        home_template = (ROOT / "renderers/zola/templates/section.html").read_text()
        page_template = (ROOT / "renderers/zola/templates/page.html").read_text()
        software_branch = page_template.split('{% elif page.extra.kind == "tools" %}', 1)[1].split('{% elif page.extra.kind == "project" %}', 1)[0]
        self.assertNotIn("project.body", home_template)
        self.assertNotIn("project.body", software_branch)
        self.assertIn("item.project.body", page_template)

    def test_home_ctas_and_status_are_structured_and_quiet(self):
        template = (ROOT / "renderers/zola/templates/section.html").read_text()
        self.assertNotIn('project.path == "dotfiles"', template)
        self.assertIn("project.downloads", template)
        self.assertIn("project.extra_links", template)
        self.assertNotIn("project.development", template)
        self.assertNotIn("project.use", template)
        self.assertIn("project.maturity", template)

    def test_reserved_authored_page_slugs_are_rejected(self):
        meta = self.path("pages/uses.toml")
        original = meta.read_text()
        for slug in ("404", "notes", "tools", "wiki"):
            with self.subTest(slug=slug):
                meta.write_text(original.replace('slug = "uses"', f'slug = "{slug}"'))
                with self.assertRaisesRegex(SiteDataError, "reserved by a generated route"):
                    load_site_data(self.repo)
        meta.write_text(original)

    def test_authored_page_project_route_collision_is_rejected(self):
        meta = self.path("pages/uses.toml")
        meta.write_text(meta.read_text().replace('slug = "uses"', 'slug = "gander"'))
        with self.assertRaisesRegex(SiteDataError, "project paths collide with pages: gander"):
            load_site_data(self.repo)


class PublicationBoundaryTests(SiteFixture):
    def test_all_exact_markers_block_published_home(self):
        for marker in UNRESOLVED_MARKERS:
            with self.subTest(marker=marker):
                home = self.path("home.md")
                original = home.read_text()
                home.write_text(original + f"\n{marker}\n")
                with self.assertRaisesRegex(SiteDataError, "unresolved marker"):
                    load_site_data(self.repo)
                home.write_text(original)

    def test_markers_are_allowed_in_proper_draft_locations(self):
        loaded = load_site_data(self.repo)
        now = next(page for page in loaded.pages if page.slug == "now")
        self.assertTrue(now.draft)
        self.assertFalse(now.listed)
        self.assertIn("CHRIS:", now.body)

        draft_project = self.path("projects/_drafts/gander.md")
        draft_project.write_text("CHRIS: add an example.\nUNVERIFIED FACT\n")
        load_site_data(self.repo)

    def test_markers_are_allowed_in_draft_metadata(self):
        now_meta = self.path("pages/_drafts/now.toml")
        now_meta.write_text(now_meta.read_text().replace('title = "Now"', 'title = "CHRIS: choose a title"').replace('description = "Current notes from Chris."', 'description = "UNVERIFIED FACT"'))
        load_site_data(self.repo)

    def test_marker_blocks_now_when_promoted(self):
        self.publish_now("CHRIS: replace this prompt.\n")
        with self.assertRaisesRegex(SiteDataError, "unresolved marker 'CHRIS:'"):
            load_site_data(self.repo)

    def test_marker_blocks_published_project_editorial(self):
        self.path("projects/gander.md").write_text("UNVERIFIED FACT\n")
        with self.assertRaisesRegex(SiteDataError, "unresolved marker 'UNVERIFIED FACT'"):
            load_site_data(self.repo)

    def test_markers_block_publishable_site_and_link_metadata(self):
        site = self.path("site.toml")
        original = site.read_text()
        replacements = {
            "name": ('name = "Chris Cummings"', 'name = "CHRIS: public name"'),
            "description": ("description = \"Chris Cummings's personal workshop, software, notes, and guides.\"", 'description = "UNVERIFIED FACT"'),
            "tagline": ('tagline = "computers · gardens · bicycles — Los Angeles"', 'tagline = "PLACEHOLDER: Chris should edit this"'),
            "profile label": ('label = "sourcehut"', 'label = "CHRIS: profile label"'),
        }
        for field, (valid, invalid) in replacements.items():
            with self.subTest(field=field):
                site.write_text(original.replace(valid, invalid, 1))
                with self.assertRaisesRegex(SiteDataError, "unresolved marker"):
                    load_site_data(self.repo)
        site.write_text(original)

    def test_markers_block_project_and_extra_link_metadata(self):
        projects = self.path("projects.toml")
        original = projects.read_text()
        replacements = {
            "name": ('name = "gander"', 'name = "CHRIS: project name"'),
            "description": ('description = "Take a gander at your jj changes: a fast review TUI with durable viewed-state, comments, and exportable review artifacts."', 'description = "UNVERIFIED FACT"'),
            "extra link": ('label = "uses"', 'label = "PLACEHOLDER: Chris should edit this"'),
        }
        for field, (valid, invalid) in replacements.items():
            with self.subTest(field=field):
                projects.write_text(original.replace(valid, invalid, 1))
                with self.assertRaisesRegex(SiteDataError, "unresolved marker"):
                    load_site_data(self.repo)
        projects.write_text(original)

    def test_markers_block_published_page_note_and_wiki_metadata(self):
        cases = (
            ("pages/uses.toml", 'title = "Uses"', 'title = "CHRIS: page title"'),
            ("pages/uses.toml", 'description = "Current machines, editor, terminal, Nix, jj, and small CLI setup."', 'description = "UNVERIFIED FACT"'),
            ("notes/2026-07-03-sccache-rust-ate-my-mac.toml", 'title = "sccache, or: Rust ate my Mac in one workday"', 'title = "CHRIS: note title"'),
            ("notes/2026-07-03-sccache-rust-ate-my-mac.toml", 'description = "A note about setting up sccache after Rust builds filled a Mac."', 'description = "PLACEHOLDER: Chris should edit this"'),
            ("wiki/about-this-wiki.toml", 'title = "About this wiki"', 'title = "CHRIS: guide title"'),
            ("wiki/about-this-wiki.toml", 'description = "What belongs in the averagechris.srht.site wiki."', 'description = "UNVERIFIED FACT"'),
        )
        for relative, valid, invalid in cases:
            with self.subTest(path=relative, field=valid.split(" = ", 1)[0]):
                path = self.path(relative)
                original = path.read_text()
                path.write_text(original.replace(valid, invalid, 1))
                with self.assertRaisesRegex(SiteDataError, "unresolved marker"):
                    load_site_data(self.repo)
                path.write_text(original)

    def test_public_urls_require_https_or_safe_root_relative_paths(self):
        site = self.path("site.toml")
        site.write_text(site.read_text().replace("https://sr.ht/~averagechris/", "http://sr.ht/~averagechris/", 1))
        with self.assertRaisesRegex(SiteDataError, "must be HTTPS or root-relative"):
            load_site_data(self.repo)


class TemplateDataTests(SiteFixture):
    def test_now_is_omitted_until_published_and_navigation_has_no_dead_link(self):
        loaded = load_site_data(self.repo)
        config = as_config(loaded)
        data = build_template_data(config, "https://example.test", {})
        self.assertIsNone(data["now"])
        self.assertEqual(["software", "notes", "guides", "uses"], [item["label"] for item in data["primary_nav"]])

        writes = []

        def capture(_content, rel, title, desc, canonical, **kwargs):
            writes.append(rel)

        with tempfile.TemporaryDirectory() as out, mock.patch("averagechris_site.zola.write_page", side_effect=capture), mock.patch("averagechris_site.zola.subprocess.run"):
            render_zola_site(ROOT, config, pathlib.Path(out), "https://example.test", {})
        self.assertNotIn("/now/", writes)

    def test_unlisted_non_draft_now_is_not_published(self):
        self.publish_now(listed=False)
        loaded = load_site_data(self.repo)
        config = as_config(loaded)
        data = build_template_data(config, "https://example.test", {})
        self.assertIsNone(data["now"])
        self.assertNotIn("now", [item["label"] for item in data["primary_nav"]])

        writes = []

        def capture(_content, rel, title, desc, canonical, **kwargs):
            writes.append(rel)

        with tempfile.TemporaryDirectory() as out, mock.patch("averagechris_site.zola.write_page", side_effect=capture), mock.patch("averagechris_site.zola.subprocess.run"):
            render_zola_site(ROOT, config, pathlib.Path(out), "https://example.test", {})
        self.assertNotIn("/now/", writes)

    def test_published_now_has_one_canonical_body_date_and_route(self):
        self.publish_now("A single canonical fixture body.\n")
        loaded = load_site_data(self.repo)
        config = as_config(loaded)
        data = build_template_data(config, "https://example.test", {})
        self.assertEqual("A single canonical fixture body.\n", data["now"]["body"])
        self.assertEqual("2026-07-05", data["now"]["date"])
        self.assertEqual("/now/", data["primary_nav"][-1]["url"])

        writes = []

        def capture(_content, rel, title, desc, canonical, **kwargs):
            writes.append((rel, title, desc, canonical, kwargs))

        with tempfile.TemporaryDirectory() as out, mock.patch("averagechris_site.zola.write_page", side_effect=capture), mock.patch("averagechris_site.zola.subprocess.run"):
            render_zola_site(ROOT, config, pathlib.Path(out), "https://example.test", {})
        now_writes = [write for write in writes if write[0] == "/now/"]
        self.assertEqual(1, len(now_writes))
        self.assertEqual("Current notes from Chris.", now_writes[0][2])
        self.assertEqual("A single canonical fixture body.\n", now_writes[0][4]["body"])

    def test_complete_software_and_exact_featured_order(self):
        loaded = load_site_data(self.repo)
        data = build_template_data(as_config(loaded), "https://example.test", {})
        self.assertEqual(FEATURED, [project["path"] for project in data["featured_projects"]])
        self.assertEqual(12, len(data["projects"]))
        self.assertEqual(
            {project["path"] for project in loaded.projects},
            {item["path"] for item in data["project_details"]},
        )
        self.assertIn("dotfiles", {item["path"] for item in data["project_details"]})

    def test_page_specific_descriptions_reach_front_matter(self):
        loaded = load_site_data(self.repo)
        writes = []

        def capture(_content, rel, title, desc, canonical, **kwargs):
            writes.append((rel, desc))

        with tempfile.TemporaryDirectory() as out, mock.patch("averagechris_site.zola.write_page", side_effect=capture), mock.patch("averagechris_site.zola.subprocess.run"):
            render_zola_site(ROOT, as_config(loaded), pathlib.Path(out), "https://example.test", {})
        descriptions = dict(writes)
        self.assertEqual("Current machines, editor, terminal, Nix, jj, and small CLI setup.", descriptions["/uses/"])
        self.assertEqual("A note about setting up sccache after Rust builds filled a Mac.", descriptions["/notes/sccache-rust-ate-my-mac/"])
        self.assertEqual("What belongs in the averagechris.srht.site wiki.", descriptions["/wiki/about-this-wiki/"])
        self.assertEqual("All software projects, source links, and available downloads.", descriptions["/tools/"])


if __name__ == "__main__":
    unittest.main()
