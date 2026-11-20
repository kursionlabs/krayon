"""End-to-end checks for a site built with Krayon's public CLI."""

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/hello-site"
KRAYON = Path(os.environ.get("KRAYON_TEST_BINARY", ROOT / "bin/krayon"))
KURSAL = Path(os.environ.get("KURSAL_COMPILER", ROOT / "../kursal/bin/kursal"))


class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("KRAYON_TEST_BINARY"):
            return
        (ROOT / "bin").mkdir(exist_ok=True)
        subprocess.run(
            [str(KURSAL), "build", "krayon", "-o", str(KRAYON)],
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

    def test_includes_share_page_site_and_loop_scope(self):
        components = self.site / "src/_includes/components"
        components.mkdir()
        (components / "row.html").write_text(
            '<a href="{{ entry.url }}">{{ entry.title }}</a>'
            '<small>{{ page.title }} · {{ site.title }}</small>')
        (components / "list.html").write_text(
            '{% for entry in collections.pages %}'
            '{% if entry.title %}{% include "components/row.html" %}{% endif %}'
            '{% endfor %}')
        (components / "shell.html").write_text('<div>{{ content | safe }}</div>')
        (self.site / "src/_includes/partial-layout.html").write_text(
            '+++\nlayout = "base.html"\n+++\n'
            '{% include "components/shell.html" %}')
        (self.site / "src/includes.html").write_text(
            '+++\nlayout = "partial-layout.html"\ntitle = "Included page"\n+++\n'
            '<section>{% include "components/list.html" %}</section>')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/includes/index.html").read_text()
        self.assertIn("<main><div><section>", html)
        self.assertIn('<a href="/">Home</a>'
                      '<small>Included page · Hello &amp; welcome</small>', html)
        self.assertIn('<a href="/guide/intro/">First note</a>'
                      '<small>Included page · Hello &amp; welcome</small>', html)

    def test_include_cycle_and_missing_file_fail_without_replacing_output(self):
        self.assertEqual(self.build().returncode, 0)
        previous = (self.site / "dist/index.html").read_bytes()
        (self.site / "src/_includes/a.html").write_text('{% include "b.html" %}')
        (self.site / "src/_includes/b.html").write_text('{% include "a.html" %}')
        (self.site / "src/cycle.html").write_text('{% include "a.html" %}')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cyclic include", result.stderr)
        self.assertEqual((self.site / "dist/index.html").read_bytes(), previous)

        (self.site / "src/cycle.html").write_text('{% include "missing.html" %}')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("include missing.html: cannot read file", result.stderr)

    def test_include_rejects_escape_and_ignores_inactive_branch(self):
        page = self.site / "src/partial.html"
        page.write_text('{% include "../secret.html" %}')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsafe path", result.stderr)

        outside = Path(self.temp.name) / "outside.html"
        outside.write_text("outside")
        (self.site / "src/_includes/linked.html").symlink_to(outside)
        page.write_text('{% include "linked.html" %}')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("path escapes layouts directory", result.stderr)

        page.write_text('{% if page.missing %}{% include "missing.html" %}'
                        '{% else %}inactive{% endif %}')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.site / "dist/partial/index.html").read_text(), "inactive")

    def test_include_uses_configured_layouts_directory(self):
        config = self.site / "krayon.toml"
        config.write_text(config.read_text().replace('layouts = "_includes"',
                                                    'layouts = "templates"'))
        (self.site / "src/_includes").rename(self.site / "src/templates")
        (self.site / "src/templates/part.html").write_text("Reusable")
        (self.site / "src/partial.html").write_text('{% include "part.html" %}')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.site / "dist/partial/index.html").read_text(), "Reusable")

    def test_template_error_locations_after_front_matter_and_in_loops(self):
        page = self.site / "src/located.html"
        page.write_text('+++\ntitle = "Located"\n+++\n<p>\n  {{ page.missing }}\n')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{page}:5:3: page.missing", result.stderr)

        page.write_text('é {{ page.missing }}')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{page}:1:3: page.missing", result.stderr)

        page.write_text('{% for entry in collections.pages %}\n'
                        '  {{ entry.missing }}\n{% endfor %}')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{page}:2:3: entry.missing", result.stderr)

        page.write_text('<p>\n {% if page.title %}')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{page}:2:2: unclosed if", result.stderr)

    def test_template_error_locations_in_layout_and_include_chain(self):
        layout = self.site / "src/_includes/located-layout.html"
        layout.write_text('+++\ntitle = "Layout"\n+++\n<div>\n {{ site.missing }}\n')
        page = self.site / "src/located.html"
        page.write_text('+++\nlayout = "located-layout.html"\n+++\nHello')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{layout}:5:2: site.missing", result.stderr)

        page.write_text('First\n{% include "a.html" %}')
        a = self.site / "src/_includes/a.html"
        b = self.site / "src/_includes/b.html"
        a.write_text('First\n{% include "b.html" %}')
        b.write_text('First\n  {{ site.missing }}')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{page}:2:1: include {a}:2:1: include {b}:2:3: site.missing",
                      result.stderr)

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

    def test_base_path_applies_to_template_and_markdown_links(self):
        config = self.site / "krayon.toml"
        config.write_text(config.read_text() + 'base_path = "/docs/v1"\n')
        archive = self.site / "src/archive.html"
        archive.write_text(archive.read_text().replace("{{ entry.url }}", "{{ entry.url | url }}"))
        layout = self.site / "src/_includes/base.html"
        layout.write_text(layout.read_text().replace('href="/"', 'href="{{ "/" | url }}"')
                          .replace('href="/assets/css/site.css"',
                                   'href="{{ "/assets/css/site.css" | url }}"'))
        (self.site / "src/links.md").write_text(
            "[Home](/) [Note](/guide/intro/?q=1&x=2) "
            "[Local](next/) [Parent](../guide/intro/) "
            "[Section](#part) [External](https://example.org/)\n"
            "\n## Part {#part}\n")
        (self.site / "src/links/next").mkdir(parents=True)
        (self.site / "src/links/next/index.md").write_text("# Next\n")
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/links/index.html").read_text()
        self.assertIn('href="/docs/v1/"', html)
        self.assertIn('href="/docs/v1/guide/intro/?q=1&amp;x=2"', html)
        self.assertIn('href="next/"', html)
        self.assertIn('href="../guide/intro/"', html)
        self.assertIn('href="#part"', html)
        self.assertIn('href="https://example.org/"', html)
        archive_html = (self.site / "dist/archive/index.html").read_text()
        self.assertIn('href="/docs/v1/guide/intro/"', archive_html)
        self.assertIn('href="/docs/v1/assets/css/site.css"', archive_html)
        self.assertIn('href="https://example.org/source', archive_html)

    def test_invalid_base_path_is_an_error(self):
        config = self.site / "krayon.toml"
        config.write_text(config.read_text() + 'base_path = "/docs/../private"\n')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsafe base_path", result.stderr)

    def test_kursal_fence_highlights_and_unknown_language_stays_plain(self):
        fence = chr(96) * 3
        (self.site / "src/code.md").write_text(
            f'{fence}kursal\nfn answer() -> usize {{ 42 }} // <note>\n'
            f'let text = "a&b"\n{fence}\n\n{fence}other\nfn <x>\n{fence}\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/code/index.html").read_text()
        self.assertIn('<span class="tok-keyword">fn</span> answer()', html)
        self.assertIn('<span class="tok-type">usize</span>', html)
        self.assertIn('<span class="tok-number">42</span>', html)
        self.assertIn('<span class="tok-comment">// &lt;note&gt;</span>', html)
        self.assertIn('<span class="tok-string">&quot;a&amp;b&quot;</span>', html)
        self.assertIn('<code class="language-other">fn &lt;x&gt;', html)

    def test_images_blockquotes_and_nested_lists(self):
        (self.site / "src/assets/diagram.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"></svg>\n')
        (self.site / "src/containers.md").write_text(
            '# Containers\n\n'
            '![A <B> & C](/assets/diagram.svg "Diagram & details")\n\n'
            '> First *quoted* line\n'
            '> second line\n'
            '>\n'
            '> ## Inside {#inside}\n'
            '> - quote item\n'
            '>   - nested quote item\n\n'
            '- parent\n'
            '  - first child\n'
            '  - second child\n'
            '- sibling\n\n'
            '1. first\n'
            '   1. inner\n'
            '2. second\n\n'
            '[Inside](#inside)\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/containers/index.html").read_text()
        self.assertIn('<img src="/assets/diagram.svg" alt="A &lt;B&gt; &amp; C" '
                      'title="Diagram &amp; details">', html)
        self.assertIn('<blockquote>\n<p>First <em>quoted</em> line second line</p>\n'
                      '<h2 id="inside">Inside</h2>\n', html)
        self.assertIn('<li>quote item<ul>\n<li>nested quote item</li>\n'
                      '</ul>\n</li>', html)
        self.assertIn('<li>parent<ul>\n<li>first child</li>\n'
                      '<li>second child</li>\n</ul>\n</li>\n<li>sibling</li>', html)
        self.assertIn('<li>first<ol>\n<li>inner</li>\n</ol>\n</li>\n'
                      '<li>second</li>', html)

    def test_image_uses_base_path_and_missing_image_fails(self):
        config = self.site / "krayon.toml"
        config.write_text(config.read_text() + 'base_path = "/docs"\n')
        layout = self.site / "src/_includes/base.html"
        layout.write_text(layout.read_text().replace('href="/"', 'href="{{ "/" | url }}"')
                          .replace('href="/assets/css/site.css"',
                                   'href="{{ "/assets/css/site.css" | url }}"'))
        archive = self.site / "src/archive.html"
        archive.write_text(archive.read_text().replace("{{ entry.url }}", "{{ entry.url | url }}"))
        image = self.site / "src/image.md"
        image.write_text("![Logo](/assets/css/site.css)\n")
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('<img src="/docs/assets/css/site.css" alt="Logo">',
                      (self.site / "dist/image/index.html").read_text())
        image.write_text("![Gone](/assets/missing.png)\n")
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("broken local link: /docs/assets/missing.png", result.stderr)

    def test_nested_quote_can_contain_code_and_heading_ids_are_page_wide(self):
        fence = chr(96) * 3
        page = self.site / "src/quote.md"
        page.write_text(
            "> > nested\n"
            ">\n"
            f"> {fence}kursal\n"
            "> fn answer() -> usize { 42 }\n"
            f"> {fence}\n"
            "> ## In quote {#shared}\n")
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/quote/index.html").read_text()
        self.assertIn("<blockquote>\n<blockquote>\n<p>nested</p>\n"
                      "</blockquote>\n", html)
        self.assertIn('<pre><code class="language-kursal">'
                      '<span class="tok-keyword">fn</span>', html)
        page.write_text(page.read_text() + "\n## Outside {#shared}\n")
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate heading ID", result.stderr)

    def test_broken_page_link_preserves_previous_output(self):
        self.assertEqual(self.build().returncode, 0)
        previous = (self.site / "dist/index.html").read_bytes()
        home = self.site / "src/index.md"
        home.write_text(home.read_text() + "\n[Missing](/does-not-exist/)\n")
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("index.md: broken local link: /does-not-exist/", result.stderr)
        self.assertEqual((self.site / "dist/index.html").read_bytes(), previous)
        self.assertEqual(list(self.site.glob("dist.krayon-*")), [])

    def test_broken_asset_and_fragment_links(self):
        layout = self.site / "src/_includes/base.html"
        layout.write_text(layout.read_text().replace("/assets/css/site.css",
                                                     "/assets/css/missing.css"))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("broken local link: /assets/css/missing.css", result.stderr)

        layout.write_text(layout.read_text().replace("/assets/css/missing.css",
                                                     "/assets/css/site.css"))
        home = self.site / "src/index.md"
        home.write_text(home.read_text() + "\n[Part](/guide/intro/#part)\n")
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("broken local link: /guide/intro/#part", result.stderr)

        note = self.site / "src/notes/first.md"
        note.write_text(note.read_text() + "\n## Part {#part}\n")
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_srcset_candidates_are_checked(self):
        assets = self.site / "src/assets"
        (assets / "small.png").write_bytes(b"small")
        (assets / "large.png").write_bytes(b"large")
        page = self.site / "src/responsive.html"
        page.write_text('<img srcset="/assets/small.png?x=1&amp;y=2 1x, '
                        '/assets/large.png 2x, data:image/gif;base64,abc 3x">')
        self.assertEqual(self.build().returncode, 0)

        page.write_text('<source SRCSET="/assets/small.png 1x, /assets/missing.png 2x">')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{page}: broken local link: /assets/missing.png", result.stderr)

    def test_css_urls_in_stylesheets_and_html_are_checked(self):
        assets = self.site / "src/assets"
        (assets / "image.png").write_bytes(b"image")
        (assets / "my image.png").write_bytes(b"image")
        sheet = assets / "css/site.css"
        sheet.write_text('/* url(../ignored.png) */\n'
                         '.label { content: "url(../ignored.png)"; }\n'
                         '.picture { background: URL("../image.png") }\n'
                         '.escaped { background: url(../my\\ image.png) }\n')
        page = self.site / "src/inline.html"
        page.write_text('<div style="background:url(/assets/image.png)"></div>\n'
                        '<style>.picture { background: url(../assets/image.png) }</style>')
        self.assertEqual(self.build().returncode, 0)

        sheet.write_text('.picture { background: url("../missing.png") }')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{sheet}: broken local link: ../missing.png", result.stderr)

        sheet.write_text('.picture { background: url("../image.png") }')
        page.write_text('<style>.picture { background: url(/assets/missing.png) }</style>')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{page}: broken local link: /assets/missing.png", result.stderr)

        page.write_text('<div style="background: url(/assets/missing.png)"></div>')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{page}: broken local link: /assets/missing.png", result.stderr)

    def test_base_path_applies_to_srcset_and_css_urls(self):
        shutil.rmtree(self.site / "src")
        assets = self.site / "src/assets"
        assets.mkdir(parents=True)
        (assets / "image.png").write_bytes(b"image")
        sheet = assets / "site.css"
        sheet.write_text('.picture { background: url(/docs/assets/image.png) }')
        page = self.site / "src/index.html"
        page.write_text('<img srcset="/docs/assets/image.png 1x">'
                        '<style>.picture { background: url(/docs/assets/image.png) }</style>')
        (self.site / "krayon.toml").write_text('base_path = "/docs"\n')
        self.assertEqual(self.build().returncode, 0)

        page.write_text('<img srcset="/assets/image.png 1x">')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("broken local link: /assets/image.png", result.stderr)

        page.write_text('<img srcset="/docs/assets/image.png 1x">')
        sheet.write_text('.picture { background: url(/assets/image.png) }')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{sheet}: broken local link: /assets/image.png", result.stderr)

    def test_link_scanner_ignores_comments_and_script_text(self):
        layout = self.site / "src/_includes/base.html"
        layout.write_text(layout.read_text() +
                          '<!-- <a href="/missing-comment/">hidden</a> -->\n'
                          '<script>const text = \'<a href="/missing-script/">\';</script>\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_html_entities_and_percent_encoded_fragments(self):
        (self.site / "src/a&b.md").write_text("# Ampersand\n")
        home = self.site / "src/index.md"
        home.write_text(home.read_text() +
                        '\n[Page](/a&b/) [Fragment](#a%26b)\n'
                        '<h2 id="a&amp;b">A and B</h2>\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_html_asset_with_fragment_is_a_valid_local_file(self):
        (self.site / "src/assets/help.html").write_text('<h1 id="intro">Intro</h1>\n')
        home = self.site / "src/index.md"
        home.write_text(home.read_text() + "\n[Help](/assets/help.html#intro)\n")
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unprefixed_link_fails_for_prefixed_site(self):
        config = self.site / "krayon.toml"
        config.write_text(config.read_text() + 'base_path = "/docs"\n')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("broken local link: /assets/css/site.css", result.stderr)

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
        home = self.site / "src/index.md"
        home.write_text(home.read_text().replace("Read the [first note](/guide/intro/).", "The note was removed."))
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
