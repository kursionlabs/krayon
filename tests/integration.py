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
            "index.html", "guide/intro/index.html", "assets/css/site.css"
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


if __name__ == "__main__":
    unittest.main()
