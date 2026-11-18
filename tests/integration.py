"""End-to-end checks for a site built with Krayon's public CLI."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/hello-site"
KRAYON = ROOT / "bin/krayon"


class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / "bin").mkdir(exist_ok=True)
        subprocess.run(
            [str(ROOT / "../kursal/bin/kursal"), "build", "krayon", "-o", str(KRAYON)],
            cwd=ROOT,
            check=True,
        )

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.site = Path(self.temp.name) / "site"
        shutil.copytree(EXAMPLE, self.site, ignore=shutil.ignore_patterns("dist"))

    def build(self):
        return subprocess.run(
            [str(KRAYON), "build", str(self.site)],
            text=True,
            capture_output=True,
        )

    def test_nested_pages_layouts_data_and_assets(self):
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        files = {p.relative_to(self.site / "dist").as_posix()
                 for p in (self.site / "dist").rglob("*") if p.is_file()}
        self.assertEqual(files, {
            "index.html", "archive/index.html", "guide/intro/index.html", "assets/css/site.css"
        })
        home = (self.site / "dist/index.html").read_text()
        note = (self.site / "dist/guide/intro/index.html").read_text()
        self.assertIn("<h1>Welcome</h1>", home)
        self.assertIn("Hello &amp; welcome", home)
        self.assertIn("<main><article>", note)
        self.assertIn("<em>italic</em>", note)
        self.assertIn("<ol>", note)
        self.assertIn("https://example.org/source?a=1&amp;b=2", note)
        self.assertEqual((self.site / "dist/assets/css/site.css").read_text(),
                         "body { font-family: sans-serif; }\n")

    def test_collections_and_nested_loops(self):
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        archive = (self.site / "dist/archive/index.html").read_text()
        self.assertLess(archive.index('href="/">Home'), archive.index('href="/archive/">Archive'))
        self.assertLess(archive.index('href="/archive/">Archive'),
                        archive.index('href="/guide/intro/">First note'))
        self.assertIn("<span>Kursal</span><span>Krayon</span><span>Static</span>", archive)

    def test_page_queries_and_record_groups(self):
        (self.site / "src/child.md").write_text('+++' '\nparent = "/archive/"\ntitle = "Child"\n+++' '\n# Child\n')
        (self.site / "src/shared.md").write_text('+++' '\nparents = ["/", "/archive/"]\ntitle = "Shared"\n+++' '\n# Shared\n')
        archive = self.site / "src/archive.html"
        archive.write_text('+++' '\nlayout = "base.html"\ntitle = "Archive"\n'
                           'nav_items = [{name = "Alpha", kind = "fn"}, '
                           '{name = "Beta", kind = "type"}, '
                           '{name = "Gamma", kind = "fn"}]\n+++' '\n'
                           '{% for child in collections.pages | children_of: page.url %}'
                           '<a href="{{ child.url }}">{{ child.title }}</a>{% endfor %}'
                           '{% for item in page.nav_items | where: "kind", "fn" %}'
                           '<b>{{ item.name }}</b>{% endfor %}'
                           '{% for group in page.nav_items | group_by: "kind" %}'
                           '<h2>{{ group.key }}</h2>'
                           '{% for item in group.items %}<i>{{ item.name }}</i>{% endfor %}'
                           '{% endfor %}')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/archive/index.html").read_text()
        self.assertIn('<a href="/child/">Child</a>', html)
        self.assertIn('<a href="/shared/">Shared</a>', html)
        self.assertNotIn('<a href="/">Home</a>', html)
        self.assertIn('<b>Alpha</b><b>Gamma</b>', html)
        self.assertIn('<h2>fn</h2><i>Alpha</i><i>Gamma</i><h2>type</h2><i>Beta</i>', html)

    def test_explicit_heading_attributes(self):
        (self.site / "src/heading.md").write_text(
            "### Fetch & update {#api-fetch .item-heading .kind-fn}\n")
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.site / "dist/heading/index.html").read_text(),
                         '<h3 id="api-fetch" class="item-heading kind-fn">Fetch &amp; update</h3>\n')

    def test_duplicate_heading_id_is_an_error(self):
        (self.site / "src/heading.md").write_text("# One {#same}\n## Two {#same}\n")
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate heading ID", result.stderr)

    def test_missing_loop_source_is_an_error(self):
        archive = self.site / "src/archive.html"
        archive.write_text(archive.read_text().replace("collections.pages", "collections.missing"))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("collections.missing", result.stderr)

    def test_unclosed_loop_is_an_error(self):
        archive = self.site / "src/archive.html"
        archive.write_text(archive.read_text().replace("{% endfor %}", "", 1))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unclosed for", result.stderr)

    def test_output_collision_is_an_error(self):
        (self.site / "src/duplicate.md").write_text(
            '+++\npermalink = "/guide/intro/"\n+++\nDuplicate\n'
        )
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("output collision", result.stderr)

    def test_unknown_template_variable_is_an_error(self):
        layout = self.site / "src/_includes/base.html"
        layout.write_text(layout.read_text() + "{{ site.missing }}\n")
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("site.missing", result.stderr)
        self.assertFalse((self.site / "dist").exists())

    def test_unsafe_permalink_is_an_error(self):
        note = self.site / "src/notes/first.md"
        note.write_text(note.read_text().replace("/guide/intro/", "/../escape/"))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsafe URL", result.stderr)

    def test_invalid_front_matter_is_an_error(self):
        note = self.site / "src/notes/first.md"
        note.write_text("+++\nlayout = [\n+++\nBody\n")
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("first.md", result.stderr)

    def test_output_inside_input_is_an_error(self):
        config = self.site / "krayon.toml"
        config.write_text(config.read_text().replace('output = "dist"', 'output = "src/dist"'))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("output must be outside input", result.stderr)

    def test_unknown_config_key_is_an_error(self):
        config = self.site / "krayon.toml"
        config.write_text(config.read_text() + 'layouts_dir = "other"\n')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown config key", result.stderr)

    def test_default_config(self):
        (self.site / "krayon.toml").unlink()
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.site / "dist/index.html").is_file())

    def test_minimal_site_needs_no_data_assets_or_layouts(self):
        minimal = Path(self.temp.name) / "minimal"
        (minimal / "src/docs").mkdir(parents=True)
        (minimal / "src/docs/first.md").write_text("# First\n\nA page.\n")
        result = subprocess.run(
            [str(KRAYON), "build", str(minimal)], text=True, capture_output=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((minimal / "dist/docs/first/index.html").read_text(),
                         "<h1>First</h1>\n<p>A page.</p>\n")

    def test_false_condition_uses_else_branch(self):
        data = self.site / "src/_data/site.toml"
        data.write_text(data.read_text().replace('subtitle = "A small Krayon site"\n', ""))
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("A site", (self.site / "dist/index.html").read_text())

    def test_rebuild_replaces_output_and_removes_stale_pages(self):
        self.assertEqual(self.build().returncode, 0)
        (self.site / "dist/stale.txt").write_text("old output")
        (self.site / "src/notes/first.md").unlink()
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.site / "dist/guide").exists())
        self.assertFalse((self.site / "dist/stale.txt").exists())
        self.assertEqual(list(self.site.glob("dist.krayon-*")), [])

    def test_failed_rebuild_preserves_previous_output(self):
        self.assertEqual(self.build().returncode, 0)
        original = (self.site / "dist/index.html").read_bytes()
        layout = self.site / "src/_includes/base.html"
        layout.write_text(layout.read_text() + "{{ site.unknown }}\n")
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.site / "dist/index.html").read_bytes(), original)
        self.assertEqual(list(self.site.glob("dist.krayon-*")), [])

    def test_cleanup_does_not_follow_output_symlinks(self):
        self.assertEqual(self.build().returncode, 0)
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        sentinel = outside / "keep.txt"
        sentinel.write_text("untouched")
        (self.site / "dist/external").symlink_to(outside, target_is_directory=True)
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sentinel.read_text(), "untouched")
        self.assertFalse((self.site / "dist/external").exists())

    def test_output_symlink_is_refused(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("untouched")
        (self.site / "dist").symlink_to(outside, target_is_directory=True)
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("output may not be a symlink", result.stderr)
        self.assertEqual((outside / "keep.txt").read_text(), "untouched")

    def test_output_parent_symlink_into_input_is_refused(self):
        (self.site / "linked").symlink_to(self.site / "src", target_is_directory=True)
        config = self.site / "krayon.toml"
        config.write_text(config.read_text().replace('output = "dist"',
                                                    'output = "linked/dist"'))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("output must be outside input", result.stderr)


if __name__ == "__main__":
    unittest.main()
