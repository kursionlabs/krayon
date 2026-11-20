"""End-to-end checks for a site built with Krayon's public CLI."""

from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET


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

    def build(self, *flags):
        return subprocess.run(
            [str(KRAYON), "build", str(self.site), *flags],
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

    def test_markdown_excerpt_marker_in_page_collection(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        src.mkdir()
        (self.site / "krayon.toml").write_text('base_path = "/docs"\n')
        (src / "post.md").write_text('+++\ntitle = "Post"\n+++\n'
                                     'Intro **bold** and [other](/other/).\n\n'
                                     '<!-- more -->\n\nRest of the post.\n')
        (src / "other.md").write_text('# Other\n')
        (src / "code.md").write_text('+++\ntitle = "Code"\n+++\n'
                                     '```text\n<!-- more -->\n```\n')
        (src / "archive.html").write_text(
            '{% for entry in collections.pages %}'
            '{% if entry.excerpt %}<section>{{ entry.excerpt | safe }}</section>'
            '<pre>{{ entry.excerpt }}</pre>{% endif %}'
            '{% endfor %}')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        archive = (self.site / "dist/archive/index.html").read_text()
        self.assertIn('<section><p>Intro <strong>bold</strong> and '
                      '<a href="/docs/other/">other</a>.</p>\n</section>', archive)
        self.assertIn('&lt;p&gt;Intro &lt;strong&gt;bold&lt;/strong&gt;', archive)
        self.assertEqual(archive.count('<section>'), 1)
        post = (self.site / "dist/post/index.html").read_text()
        self.assertNotIn('<!-- more -->', post)
        self.assertIn('<p>Rest of the post.</p>', post)
        self.assertIn('&lt;!-- more --&gt;',
                      (self.site / "dist/code/index.html").read_text())

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

    def test_data_array_generates_pages_in_collections(self):
        data = self.site / "src/_data/site.toml"
        data.write_text(data.read_text() + '\n[[catalog.products]]\n'
                        'url = "/products/alpha/"\n'
                        'title = "Alpha"\n'
                        'description = "First product"\n'
                        'next = "/products/beta/"\n'
                        '\n[[catalog.products]]\n'
                        'url = "/products/beta/"\n'
                        'description = "Second product"\n'
                        'next = "/products/alpha/"\n')
        template = self.site / "src/product.html"
        template.write_text('+++\n'
                            'generate = "site.catalog.products"\n'
                            'layout = "base.html"\n'
                            'title = "Default title"\n'
                            'kind = "product"\n'
                            '+++\n'
                            '<h1>{{ page.title }}</h1><p>{{ page.description }}</p>'
                            '<a href="{{ page.next }}">Next</a>')
        listing = self.site / "src/catalog.html"
        listing.write_text('{% for item in collections.pages | where: "kind", "product" %}'
                           '<a href="{{ item.url }}">{{ item.title }}</a>{% endfor %}')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.site / "dist/product/index.html").exists())
        alpha = (self.site / "dist/products/alpha/index.html").read_text()
        beta = (self.site / "dist/products/beta/index.html").read_text()
        self.assertIn('<h1>Alpha</h1><p>First product</p>', alpha)
        self.assertIn('<h1>Default title</h1><p>Second product</p>', beta)
        self.assertIn('href="/products/beta/"', alpha)
        self.assertIn('href="/products/alpha/"', beta)
        self.assertIn('<a href="/products/alpha/">Alpha</a>'
                      '<a href="/products/beta/">Default title</a>',
                      (self.site / "dist/catalog/index.html").read_text())

    def test_generated_pages_validate_records_urls_and_collisions(self):
        data = self.site / "src/_data/site.toml"
        template = self.site / "src/product.html"
        template.write_text('+++\ngenerate = "site.products"\n+++\n{{ page.title }}')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("generate source is missing", result.stderr)

        data.write_text('products = [1]\n' + data.read_text())
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("generate item must be a table", result.stderr)
        self.assertIn("[item 1]", result.stderr)

        data.write_text(data.read_text().replace('products = [1]',
                                                 'products = [{title = "No URL"}]'))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("generate item needs a url", result.stderr)

        data.write_text(data.read_text().replace('products = [{title = "No URL"}]',
                                                 'products = [{url = "/../escape/", title = "Bad"}]'))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsafe URL", result.stderr)
        self.assertIn("product.html [item 1]", result.stderr)

        data.write_text(data.read_text().replace('/../escape/', '/'))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("output collision", result.stderr)

        data.write_text(data.read_text().replace('url = "/"', 'url = "/products/ok/"'))
        self.assertEqual(self.build().returncode, 0)
        previous = (self.site / "dist/products/ok/index.html").read_bytes()
        data.write_text(data.read_text().replace('/products/ok/', '/products/gone/'))
        template.write_text('+++\ngenerate = "site.products"\n+++\n'
                            '<a href="/missing/">Broken</a>')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("broken local link", result.stderr)
        self.assertEqual((self.site / "dist/products/ok/index.html").read_bytes(), previous)

    def test_generate_requires_html_array_and_item_urls(self):
        data = self.site / "src/_data/site.toml"
        page = self.site / "src/generated.md"
        page.write_text('+++\ngenerate = "site.products"\n+++\n# Generated')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("generate requires an HTML template", result.stderr)

        page.unlink()
        page = self.site / "src/generated.html"
        page.write_text('+++\ngenerate = "site.products"\npermalink = 4\n+++\nGenerated')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("permalink must be a string", result.stderr)

        page.write_text('+++\ngenerate = "site.products"\n+++\nGenerated')
        data.write_text('products = 1\n' + data.read_text())
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("generate source must be an array", result.stderr)

        data.write_text(data.read_text().replace('products = 1', 'products = []'))
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.site / "dist/generated/index.html").exists())

    def test_generated_permalink_pattern_and_explicit_url_override(self):
        data = self.site / "src/_data/site.toml"
        data.write_text(data.read_text() + '\n[[products]]\n'
                        'route = {slug = "alpha"}\n'
                        'title = "Alpha"\n'
                        '\n[[products]]\n'
                        'url = "/special/beta.html"\n'
                        'title = "Beta"\n')
        template = self.site / "src/product.html"
        template.write_text('+++\n'
                            'generate = "site.products"\n'
                            'permalink = "/products/{{ item.route.slug }}/"\n'
                            'kind = "product"\n'
                            '+++\n'
                            '<a href="{{ page.permalink }}">{{ page.title }}</a>')
        listing = self.site / "src/catalog.html"
        listing.write_text('{% for item in collections.pages | where: "kind", "product" %}'
                           '<a href="{{ item.url }}">{{ item.title }}</a>{% endfor %}')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('<a href="/products/alpha/">Alpha</a>',
                      (self.site / "dist/products/alpha/index.html").read_text())
        self.assertIn('<a href="/special/beta.html">Beta</a>',
                      (self.site / "dist/special/beta.html").read_text())
        self.assertFalse((self.site / "dist/products/beta/index.html").exists())
        self.assertIn('<a href="/products/alpha/">Alpha</a>'
                      '<a href="/special/beta.html">Beta</a>',
                      (self.site / "dist/catalog/index.html").read_text())

    def test_generated_permalink_pattern_errors(self):
        data = self.site / "src/_data/site.toml"
        original = data.read_text()
        template = self.site / "src/product.html"
        template.write_text('+++\ngenerate = "site.products"\n'
                            'permalink = "/products/{{ item.slug }}/"\n+++\nProduct')
        data.write_text('products = [{title = "Missing slug"}]\n' + original)
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing permalink field: item.slug", result.stderr)
        self.assertIn("[item 1]", result.stderr)

        data.write_text('products = [{slug = [1]}]\n' + original)
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("permalink field must be a string or integer", result.stderr)

        data.write_text('products = [{slug = ".."}]\n' + original)
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsafe URL", result.stderr)

        data.write_text('products = [{slug = "same"}, {slug = "same"}]\n' + original)
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("output collision", result.stderr)

        data.write_text('products = [{slug = "good"}]\n' + original)
        template.write_text('+++\ngenerate = "site.products"\n'
                            'permalink = "/products/{{ item.slug/"\n+++\nProduct')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unclosed permalink placeholder", result.stderr)

    def test_generated_permalink_pattern_accepts_integer_field(self):
        data = self.site / "src/_data/site.toml"
        data.write_text('products = [{id = 42}]\n' + data.read_text())
        template = self.site / "src/product.html"
        template.write_text('+++\ngenerate = "site.products"\n'
                            'permalink = "/products/{{ item.id }}/"\n+++\nNumbered')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.site / "dist/products/42/index.html").read_text(), "Numbered")

    def test_sort_by_query_orders_records_without_changing_source(self):
        data = self.site / "src/_data/site.toml"
        data.write_text('entries = [{name = "Two", rank = 2, date = 2026-01-02}, '
                        '{name = "Ten", rank = 10, date = 2026-01-10}, '
                        '{name = "One", rank = 1, date = 2026-01-01}]\n'
                        + data.read_text())
        page = self.site / "src/sort.html"
        page.write_text('{% for item in site.entries | sort_by: "rank", "desc" %}'
                        '{{ item.name }} {% endfor %}|'
                        '{% for item in site.entries | sort_by: "date" %}'
                        '{{ item.name }} {% endfor %}|'
                        '{% for item in site.entries %}{{ item.name }} {% endfor %}')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.site / "dist/sort/index.html").read_text(),
                         'Ten Two One |One Two Ten |Two Ten One ')

        previous = (self.site / "dist/sort/index.html").read_bytes()
        page.write_text('{% for item in site.entries | sort_by: "missing" %}'
                        '{{ item.name }}{% endfor %}')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('sort field is missing', result.stderr)
        self.assertEqual((self.site / "dist/sort/index.html").read_bytes(), previous)

    def test_paginate_sorting_applies_before_page_slicing(self):
        data = self.site / "src/_data/site.toml"
        data.write_text('entries = [{name = "First two", meta = {rank = 2}}, '
                        '{name = "Ten", meta = {rank = 10}}, '
                        '{name = "Second two", meta = {rank = 2}}, '
                        '{name = "One", meta = {rank = 1}}]\n' + data.read_text())
        page = self.site / "src/ranked.html"
        page.write_text('+++\npaginate = "site.entries"\npage_size = 2\n'
                        'sort_by = "meta.rank"\nsort_order = "desc"\n+++\n'
                        '{% for item in page.pagination.items %}{{ item.name }};{% endfor %}')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.site / "dist/ranked/index.html").read_text(),
                         'Ten;First two;')
        self.assertEqual((self.site / "dist/ranked/page/2/index.html").read_text(),
                         'Second two;One;')

        page.write_text(page.read_text().replace('sort_order = "desc"',
                                                 'sort_order = "reverse"'))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('sort_order must be asc or desc', result.stderr)

        page.write_text(page.read_text().replace('sort_order = "reverse"',
                                                 'sort_order = "desc"'))
        data.write_text(data.read_text().replace('meta = {rank = 1}',
                                                 'meta = {rank = "one"}'))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('sort fields must have the same type', result.stderr)

    def test_paginate_filters_before_sorting_and_slicing(self):
        data = self.site / "src/_data/site.toml"
        data.write_text('posts = ['
                        '{title = "Draft top", meta = {published = false, rank = 99}}, '
                        '{title = "Older", meta = {published = true, rank = 1}}, '
                        '{title = "Newest", meta = {published = true, rank = 10}}, '
                        '{title = "Middle", meta = {published = true, rank = 5}}, '
                        '{title = "Draft bottom", meta = {published = false, rank = 0}}]\n'
                        + data.read_text())
        template = self.site / "src/posts.html"
        template.write_text('+++\npaginate = "site.posts"\npage_size = 2\n'
                            'where = {field = "meta.published", equals = true}\n'
                            'sort_by = "meta.rank"\nsort_order = "desc"\n+++\n'
                            '<p>{{ page.pagination.number }}/{{ page.pagination.total_pages }}:'
                            '{{ page.pagination.total_items }}</p>'
                            '{% for post in page.pagination.items %}'
                            '{{ post.title }};{% endfor %}')
        (self.site / "src/selected.html").write_text(
            '{% for post in site.posts | where: "meta.published", "true" %}'
            '{{ post.title }};{% endfor %}')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.site / "dist/selected/index.html").read_text(),
                         'Older;Newest;Middle;')
        self.assertEqual((self.site / "dist/posts/index.html").read_text(),
                         '<p>1/2:3</p>Newest;Middle;')
        self.assertEqual((self.site / "dist/posts/page/2/index.html").read_text(),
                         '<p>2/2:3</p>Older;')
        self.assertFalse((self.site / "dist/posts/page/3/index.html").exists())

        template.write_text(template.read_text().replace('equals = true',
                                                         'equals = "no match"'))
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.site / "dist/posts/index.html").read_text(),
                         '<p>1/1:0</p>')
        self.assertFalse((self.site / "dist/posts/page/2/index.html").exists())

        template.write_text(template.read_text().replace('equals = "no match"',
                                                         'equals = true')
                            .replace('meta.published', 'missing'))
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.site / "dist/posts/index.html").read_text(),
                         '<p>1/1:0</p>')

        template.write_text(template.read_text().replace('where = {field = "missing", equals = true}',
                                                         'where = {field = "meta.published"}'))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('where requires equals', result.stderr)
        self.assertEqual((self.site / "dist/posts/index.html").read_text(),
                         '<p>1/1:0</p>')

    def test_paginate_page_collection_without_archive_feedback(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        src.mkdir()
        (src / "old.md").write_text('+++\nkind = "post"\ntitle = "Old"\n'
                                    'date = 2026-01-01\n+++\n# Old')
        (src / "new.md").write_text('+++\nkind = "post"\ntitle = "New"\n'
                                    'date = 2026-01-10\n+++\n# New')
        (src / "draft.md").write_text('+++\nkind = "post"\ntitle = "Draft"\n'
                                      'date = 2026-01-20\ndraft = true\n+++\n# Draft')
        (src / "blog.html").write_text(
            '+++\npaginate = "collections.pages"\npage_size = 2\n'
            'where = {field = "kind", equals = "post"}\n'
            'sort_by = "date"\nsort_order = "desc"\nkind = "archive"\n+++\n'
            '<p>{{ page.pagination.total_items }}/{{ page.pagination.total_pages }}</p>'
            '{% for post in page.pagination.items %}'
            '<a href="{{ post.url }}">{{ post.title }}</a>{% endfor %}')
        (src / "all.html").write_text(
            '+++\npaginate = "collections.pages"\npage_size = 10\n'
            'kind = "archive"\n+++\n{{ page.pagination.total_items }}')
        (src / "overview.html").write_text(
            '{% for item in collections.pages | where: "kind", "archive" %}'
            '{{ item.url }};{% endfor %}')

        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        blog = (self.site / "dist/blog/index.html").read_text()
        self.assertIn('<p>2/1</p><a href="/new/">New</a>'
                      '<a href="/old/">Old</a>', blog)
        self.assertFalse((self.site / "dist/blog/page/2/index.html").exists())
        self.assertEqual((self.site / "dist/all/index.html").read_text(), "3")
        self.assertEqual((self.site / "dist/overview/index.html").read_text(),
                         "/all/;/blog/;")

        result = self.build("--drafts")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('<p>3/2</p><a href="/draft/">Draft</a>'
                      '<a href="/new/">New</a>',
                      (self.site / "dist/blog/index.html").read_text())
        self.assertIn('<a href="/old/">Old</a>',
                      (self.site / "dist/blog/page/2/index.html").read_text())
        self.assertEqual((self.site / "dist/all/index.html").read_text(), "4")

        (src / "blog.html").write_text((src / "blog.html").read_text().replace(
            'collections.pages', 'collections.missing'))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('paginate must name a site data array or collections.pages', result.stderr)
        self.assertTrue((self.site / "dist/blog/page/2/index.html").exists())

    def test_tag_array_membership_filters_queries_and_pagination(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        src.mkdir()
        (src / "old.md").write_text('+++\ntitle = "Old"\n'
                                    'tags = ["kursal", "language"]\n'
                                    'date = 2026-01-01\n+++\n# Old')
        (src / "new.md").write_text('+++\ntitle = "New"\n'
                                    'tags = ["kursal"]\n'
                                    'date = 2026-01-10\n+++\n# New')
        (src / "other.md").write_text('+++\ntitle = "Other"\n'
                                      'tags = ["static"]\n'
                                      'date = 2026-01-15\n+++\n# Other')
        (src / "scalar.md").write_text('+++\ntitle = "Scalar"\n'
                                       'tags = "kursal"\n'
                                       'date = 2026-01-20\n+++\n# Scalar')
        (src / "untagged.md").write_text('# Untagged')
        archive = src / "tags.html"
        archive.write_text('+++\npaginate = "collections.pages"\npage_size = 1\n'
                           'where = {field = "tags", contains = "kursal"}\n'
                           'sort_by = "date"\nsort_order = "desc"\n+++\n'
                           '<p>{{ page.pagination.total_items }}/{{ page.pagination.total_pages }}</p>'
                           '{% for post in page.pagination.items %}'
                           '<a href="{{ post.url }}">{{ post.title }}</a>{% endfor %}')
        (src / "listing.html").write_text(
            '{% for post in collections.pages | contains: "tags", "kursal" %}'
            '{{ post.title }};{% endfor %}')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.site / "dist/listing/index.html").read_text(), 'New;Old;')
        self.assertIn('<p>2/2</p><a href="/new/">New</a>',
                      (self.site / "dist/tags/index.html").read_text())
        self.assertIn('<p>2/2</p><a href="/old/">Old</a>',
                      (self.site / "dist/tags/page/2/index.html").read_text())

        previous = (self.site / "dist/tags/index.html").read_bytes()
        archive.write_text(archive.read_text().replace('contains = "kursal"',
                                                     'contains = "kursal", equals = "kursal"'))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('where accepts either equals or contains', result.stderr)
        self.assertEqual((self.site / "dist/tags/index.html").read_bytes(), previous)

    def test_paginate_data_array_and_navigation(self):
        data = self.site / "src/_data/site.toml"
        data.write_text('posts = [{title = "One"}, {title = "Two"}, '
                        '{title = "Three"}, {title = "Four"}, {title = "Five"}]\n'
                        + data.read_text())
        template = self.site / "src/posts.html"
        template.write_text('+++\npaginate = "site.posts"\npage_size = 2\n'
                            'permalink = "/blog/"\nkind = "listing"\n+++\n'
                            '<p>{{ page.pagination.number }}/{{ page.pagination.total_pages }}:'
                            '{{ page.pagination.total_items }}</p>'
                            '{% for post in page.pagination.items %}'
                            '<span>{{ post.title }}</span>{% endfor %}'
                            '{% if page.pagination.previous %}'
                            '<a href="{{ page.pagination.previous | url }}">Previous</a>{% endif %}'
                            '{% if page.pagination.next %}'
                            '<a href="{{ page.pagination.next | url }}">Next</a>{% endif %}')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        first = (self.site / "dist/blog/index.html").read_text()
        second = (self.site / "dist/blog/page/2/index.html").read_text()
        third = (self.site / "dist/blog/page/3/index.html").read_text()
        self.assertIn('<p>1/3:5</p><span>One</span><span>Two</span>', first)
        self.assertIn('href="/blog/page/2/"', first)
        self.assertNotIn('>Previous</a>', first)
        self.assertIn('<p>2/3:5</p><span>Three</span><span>Four</span>', second)
        self.assertIn('href="/blog/"', second)
        self.assertIn('href="/blog/page/3/"', second)
        self.assertIn('<p>3/3:5</p><span>Five</span>', third)
        self.assertNotIn('>Next</a>', third)
        self.assertFalse((self.site / "dist/posts/index.html").exists())

        data.write_text(data.read_text().replace('{title = "Three"}, {title = "Four"}, '
                                                 '{title = "Five"}', ''))
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.site / "dist/blog/page/2/index.html").exists())
        self.assertFalse((self.site / "dist/blog/page/3/index.html").exists())

    def test_custom_numbered_page_permalinks_and_validation(self):
        data = self.site / "src/_data/site.toml"
        data.write_text('posts = [{title = "One"}, {title = "Two"}, '
                        '{title = "Three"}, {title = "Four"}, {title = "Five"}]\n'
                        + data.read_text())
        template = self.site / "src/posts.html"
        template.write_text('+++\npaginate = "site.posts"\npage_size = 2\n'
                            'permalink = "/blog/"\n'
                            'page_permalink = "/blog/p{{ page.pagination.number }}.html"\n+++\n'
                            '{{ page.permalink }}:'
                            '{% if page.pagination.previous %}'
                            '<a href="{{ page.pagination.previous }}">Previous</a>{% endif %}'
                            '{% if page.pagination.next %}'
                            '<a href="{{ page.pagination.next }}">Next</a>{% endif %}')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        first = (self.site / "dist/blog/index.html").read_text()
        second = (self.site / "dist/blog/p2.html").read_text()
        third = (self.site / "dist/blog/p3.html").read_text()
        self.assertIn('/blog/:<a href="/blog/p2.html">Next</a>', first)
        self.assertIn('/blog/p2.html:<a href="/blog/">Previous</a>'
                      '<a href="/blog/p3.html">Next</a>', second)
        self.assertIn('/blog/p3.html:<a href="/blog/p2.html">Previous</a>', third)
        self.assertFalse((self.site / "dist/blog/page/2/index.html").exists())

        previous = (self.site / "dist/blog/p2.html").read_bytes()
        template.write_text(template.read_text().replace(
            '{{ page.pagination.number }}.html', '{{ page.url }}.html'))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('page_permalink must contain {{ page.pagination.number }}', result.stderr)
        self.assertEqual((self.site / "dist/blog/p2.html").read_bytes(), previous)

        template.write_text(template.read_text().replace(
            '{{ page.url }}.html', '{{ page.pagination.number }}{{ page.pagination.number }}.html'))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('page_permalink accepts only one page number placeholder', result.stderr)

        template.write_text(template.read_text().replace(
            '/blog/p{{ page.pagination.number }}{{ page.pagination.number }}.html',
            '/blog/../p{{ page.pagination.number }}.html'))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unsafe URL', result.stderr)

        template.write_text(template.read_text().replace(
            '/blog/../p{{ page.pagination.number }}.html',
            '/blog/p{{ page.pagination.number }}.html'))
        (self.site / "src/collision.html").write_text(
            '+++\npermalink = "/blog/p2.html"\n+++\nCollision')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('output collision', result.stderr)
        self.assertEqual((self.site / "dist/blog/p2.html").read_bytes(), previous)

    def test_paginate_empty_array_drafts_and_invalid_configuration(self):
        data = self.site / "src/_data/site.toml"
        data.write_text('posts = []\n' + data.read_text())
        template = self.site / "src/posts.html"
        template.write_text('+++\npaginate = "site.posts"\npage_size = 2\n'
                            'draft = true\n+++\n'
                            '<p>{{ page.pagination.number }}:{{ page.pagination.total_items }}</p>')
        self.assertEqual(self.build().returncode, 0)
        self.assertFalse((self.site / "dist/posts/index.html").exists())
        result = self.build("--drafts")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.site / "dist/posts/index.html").read_text(), '<p>1:0</p>')

        template.write_text('+++\npaginate = "site.posts"\npage_size = 0\n+++\n')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('page_size must be a positive integer', result.stderr)

        template.write_text('+++\npaginate = "site.posts"\n+++\n')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('paginate requires page_size', result.stderr)

        template.write_text('+++\npaginate = "site.posts"\npage_size = 1\n'
                            'permalink = "/"\n+++\n')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('output collision', result.stderr)

    def test_xml_json_and_text_templates(self):
        value = 'A "quote" \\ path\nNext\t\x01'
        data = self.site / "src/_data/site.toml"
        data.write_text(f'json_title = {json.dumps(value)}\n' + data.read_text())
        (self.site / "src/_includes/url.xml").write_text(
            '<url><loc>{{ entry.url | url }}</loc></url>')
        (self.site / "src/_includes/xml-shell.xml").write_text(
            '<?xml version="1.0"?><root>{{ content | safe }}</root>')
        (self.site / "src/sitemap.xml").write_text(
            '+++\nlayout = "xml-shell.xml"\n+++\n'
            '<name>{{ site.title }}</name>'
            '{% for entry in collections.pages %}{% include "url.xml" %}{% endfor %}')
        (self.site / "src/_includes/json-shell.json").write_text(
            '{"title":"{{ site.json_title }}","pages":[{{ content | safe }}]}')
        (self.site / "src/_includes/page.json").write_text(
            '{"url":"{{ entry.url }}","index":"{{ loop.index }}",'
            '"last":{{ loop.last }}}')
        (self.site / "src/manifest.json").write_text(
            '+++\nlayout = "json-shell.json"\n+++\n'
            '{% for entry in collections.pages %}'
            '{% if loop.first %}{% else %},{% endif %}'
            '{% include "page.json" %}'
            '{% endfor %}')
        (self.site / "src/_includes/line.txt").write_text('Site: {{ site.title }}\n')
        (self.site / "src/robots.txt").write_text('{% include "line.txt" %}')
        (self.site / "src/references.html").write_text(
            '<a href="/sitemap.xml">Map</a><a href="/manifest.json">Data</a>'
            '<a href="/robots.txt">Robots</a>')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)

        root = ET.fromstring((self.site / "dist/sitemap.xml").read_text())
        self.assertEqual(root.find("name").text, "Hello & welcome")
        self.assertEqual(len(root.findall("url")), 4)
        manifest = json.loads((self.site / "dist/manifest.json").read_text())
        self.assertEqual(manifest["title"], value)
        self.assertEqual([p["index"] for p in manifest["pages"]], ["1", "2", "3", "4"])
        self.assertEqual([p["last"] for p in manifest["pages"]],
                         [False, False, False, True])
        self.assertEqual({p["url"] for p in manifest["pages"]},
                         {"/", "/archive/", "/guide/intro/", "/references/"})
        self.assertEqual((self.site / "dist/robots.txt").read_text(),
                         "Site: Hello & welcome\n")

        previous = (self.site / "dist/sitemap.xml").read_bytes()
        sitemap = self.site / "src/sitemap.xml"
        sitemap.write_text(sitemap.read_text().replace("{{ site.title }}",
                                                      "{{ site.json_title }}"))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("XML value contains an invalid control character", result.stderr)
        self.assertEqual((self.site / "dist/sitemap.xml").read_bytes(), previous)

    def test_generated_json_templates_and_drafts(self):
        data = self.site / "src/_data/site.toml"
        data.write_text('products = [{slug = "alpha", title = "A & B"}, '
                        '{slug = "beta", title = "B", draft = true}]\n' + data.read_text())
        template = self.site / "src/product.json"
        template.write_text('+++\ngenerate = "site.products"\n'
                            'permalink = "/data/{{ item.slug }}.json"\n+++\n'
                            '{"title":"{{ page.title }}"}')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.site / "dist/data/alpha.json").read_text()),
                         {"title": "A & B"})
        self.assertFalse((self.site / "dist/data/beta.json").exists())
        self.assertFalse((self.site / "dist/product.json").exists())

        result = self.build("--drafts")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.site / "dist/data/beta.json").read_text()),
                         {"title": "B"})

        previous = (self.site / "dist/data/alpha.json").read_bytes()
        template.write_text(template.read_text().replace('{"title":"{{ page.title }}"}',
                                                         '{"title":{{ page.title }}}'))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("generated JSON /data/alpha.json", result.stderr)
        self.assertEqual((self.site / "dist/data/alpha.json").read_bytes(), previous)

    def test_non_html_output_suffix_and_collision_checks(self):
        source = self.site / "src/feed.xml"
        source.write_text('+++\npermalink = "/feed.json"\n+++\n<feed/>')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("URL must end in .xml", result.stderr)

        source.write_text('+++\nlayout = "base.html"\n+++\n<feed/>')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("layout has the wrong suffix", result.stderr)

        source.write_text('{% include "part.html" %}')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("wrong suffix for template format", result.stderr)

        (self.site / "src/assets/feed.xml").write_text('<asset/>')
        source.write_text('+++\npermalink = "/assets/feed.xml"\n+++\n<feed/>')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("output collision", result.stderr)

    def test_json_filter_serializes_toml_values_and_collections(self):
        value = 'A "quote" \\ slash\nline\t\x01'
        data = self.site / "src/_data/site.toml"
        data.write_text(data.read_text() + '\n[json_payload]\n'
                        f'z = {json.dumps(value)}\n'
                        'when = 2026-11-20\n'
                        'values = [1, "two", {z = false, a = "x"}]\n'
                        'price = 1.25\n'
                        'enabled = true\n'
                        'a = -7\n')
        template = self.site / "src/payload.json"
        template.write_text('{"data":{{ site.json_payload | json }},'
                            '"pages":{{ collections.pages | json }},'
                            '"literal":{{ "hello" | json }}}')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        raw = (self.site / "dist/payload.json").read_text()
        parsed = json.loads(raw)
        self.assertEqual(parsed["data"], {
            "a": -7, "enabled": True, "price": 1.25,
            "values": [1, "two", {"a": "x", "z": False}],
            "when": "2026-11-20", "z": value,
        })
        self.assertLess(raw.index('"a":-7'), raw.index('"z":'))
        self.assertEqual(parsed["literal"], "hello")
        self.assertEqual([page["url"] for page in parsed["pages"]],
                         ["/", "/archive/", "/guide/intro/"])

        previous = (self.site / "dist/payload.json").read_bytes()
        data.write_text('bad = inf\n' + data.read_text())
        template.write_text('{"bad":{{ site.bad | json }}}')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("JSON cannot represent NaN or infinity", result.stderr)
        self.assertEqual((self.site / "dist/payload.json").read_bytes(), previous)

    def test_json_filter_chains_url_and_requires_json_template(self):
        shutil.rmtree(self.site / "src")
        (self.site / "src").mkdir()
        (self.site / "krayon.toml").write_text('base_path = "/docs"\n')
        template = self.site / "src/links.json"
        template.write_text('{"asset":{{ "/assets/app.css" | url | json }}}')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.site / "dist/links.json").read_text()),
                         {"asset": "/docs/assets/app.css"})

        template.unlink()
        html = self.site / "src/index.html"
        html.write_text('{{ "value" | json }}')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("json filter requires a JSON template", result.stderr)

    def test_generated_json_is_validated_before_output_install(self):
        template = self.site / "src/feed.json"
        template.write_text('{"title":"Café", "escaped":"\\uD83D\\uDE80",'
                            ' "items": [1, true, null, {"x": 2}]}')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        previous = (self.site / "dist/feed.json").read_bytes()
        self.assertEqual(json.loads(previous)["escaped"], "🚀")

        template.write_text('{"items": [1,\n 2,]}')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{template}: generated JSON /feed.json:2:4: trailing comma in JSON",
                      result.stderr)
        self.assertEqual((self.site / "dist/feed.json").read_bytes(), previous)

        template.write_text('{"title":"Café","x":}')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("generated JSON /feed.json:1:21: expected JSON value", result.stderr)
        self.assertEqual((self.site / "dist/feed.json").read_bytes(), previous)

    def test_generated_json_rejects_invalid_strings_and_numbers(self):
        template = self.site / "src/feed.json"
        cases = [
            ('{"x":"\\uD800"}', "high surrogate requires a low surrogate"),
            ('{"x":"\\q"}', "invalid string escape"),
            ('{"x":01}', "expected comma or closing bracket"),
            ('{"x":1e}', "expected exponent digit"),
            ('{"x":"a\nb"}', "unescaped control character in string"),
            ('{"x":true} false', "extra content after JSON value"),
        ]
        for body, message in cases:
            with self.subTest(body=body):
                template.write_text(body)
                result = self.build()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)

        template.write_bytes(b'{"x":"\xff"}')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid UTF-8 in string", result.stderr)

    def test_drafts_are_excluded_until_preview_build(self):
        draft = self.site / "src/draft.md"
        draft.write_text('+++\ntitle = "Draft"\ndraft = true\n+++\n# Draft\n')
        listing = self.site / "src/listing.html"
        listing.write_text('{% for item in collections.pages %}'
                           '<span>{{ item.url }}</span>{% endfor %}')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.site / "dist/draft/index.html").exists())
        self.assertNotIn('<span>/draft/</span>',
                         (self.site / "dist/listing/index.html").read_text())

        result = self.build("--drafts")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.site / "dist/draft/index.html").exists())
        self.assertIn('<span>/draft/</span>',
                      (self.site / "dist/listing/index.html").read_text())

        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.site / "dist/draft/index.html").exists())

    def test_generated_drafts_and_invalid_draft_values(self):
        data = self.site / "src/_data/site.toml"
        original = data.read_text()
        data.write_text('products = [{slug = "hidden"}, '
                        '{slug = "visible", draft = false}]\n' + original)
        template = self.site / "src/product.html"
        template.write_text('+++\ngenerate = "site.products"\n'
                            'permalink = "/products/{{ item.slug }}/"\n'
                            'draft = true\n+++\n{{ page.url }}')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.site / "dist/products/hidden/index.html").exists())
        self.assertTrue((self.site / "dist/products/visible/index.html").exists())

        result = self.build("--drafts")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.site / "dist/products/hidden/index.html").exists())

        data.write_text('products = [{slug = "bad", draft = "yes"}]\n' + original)
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("draft must be a boolean", result.stderr)
        self.assertIn("[item 1]", result.stderr)

    def test_published_links_to_drafts_fail_and_preview_accepts_them(self):
        draft = self.site / "src/draft.md"
        draft.write_text('+++\ndraft = true\n+++\n# Draft\n')
        public = self.site / "src/public.html"
        public.write_text('<a href="/draft/">Draft</a>')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("broken local link: /draft/", result.stderr)

        result = subprocess.run([str(KRAYON), "build", "--drafts", str(self.site)],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.site / "dist/draft/index.html").exists())

        draft.write_text('+++\ndraft = "true"\n+++\n# Draft\n')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("draft must be a boolean", result.stderr)

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

    def test_absolute_url_filter_uses_origin_and_base_path(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        src.mkdir()
        (self.site / "krayon.toml").write_text(
            'base_path = "/docs"\norigin = "https://example.org:8443/"\n')
        (src / "guide.md").write_text('# Guide\n')
        (src / "index.html").write_text(
            '<link rel="canonical" href="{{ page.url | absolute_url }}">'
            '<p>{{ site.origin }}</p>'
            '<span>{{ "https://other.example/x" | absolute_url }}</span>'
            '<span>{{ "//cdn.example/x" | absolute_url }}</span>'
            '<span>{{ "relative/x" | absolute_url }}</span>'
            '<span>{{ "#section" | absolute_url }}</span>')
        (src / "sitemap.xml").write_text(
            '<urlset><loc>{{ "/guide/?a=1&b=2" | absolute_url }}</loc></urlset>')
        (src / "feed.json").write_text(
            '{"guide":{{ "/guide/" | absolute_url | json }}}')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/index.html").read_text()
        self.assertIn('href="https://example.org:8443/docs/"', html)
        self.assertIn('<p>https://example.org:8443</p>', html)
        self.assertIn('<span>https://other.example/x</span>', html)
        self.assertIn('<span>//cdn.example/x</span>', html)
        self.assertIn('<span>relative/x</span>', html)
        self.assertIn('<span>#section</span>', html)
        self.assertEqual(ET.parse(self.site / "dist/sitemap.xml").find('.//loc').text,
                         'https://example.org:8443/docs/guide/?a=1&b=2')
        self.assertEqual(json.loads((self.site / "dist/feed.json").read_text()),
                         {"guide": "https://example.org:8443/docs/guide/"})

        previous = (self.site / "dist/index.html").read_bytes()
        (self.site / "krayon.toml").write_text('base_path = "/docs"\n')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('absolute_url requires origin in krayon.toml', result.stderr)
        self.assertEqual((self.site / "dist/index.html").read_bytes(), previous)

    def test_origin_config_rejects_non_origins(self):
        config = self.site / "krayon.toml"
        for value in ('ftp://example.org', 'https://example.org/path',
                      'https://user@example.org', 'https://example.org:0',
                      'https://example.org:99999', 'https://example.org//'):
            with self.subTest(origin=value):
                config.write_text(f'origin = "{value}"\n')
                result = self.build()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('invalid origin', result.stderr)

        config.write_text('origin = "http://[::1]:8080"\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)

        config.write_text('origin = ""\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)

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

    def test_broken_link_locations_in_html_srcset_and_css(self):
        page = self.site / "src/located-links.html"
        page.write_text('é <a href="/missing/">Missing</a>')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{page}: broken local link: /missing/ "
                      "(generated HTML line 1, column 12)", result.stderr)

        (self.site / "src/assets/existing.png").write_bytes(b"image")
        page.write_text('<img srcset="/assets/existing.png 1x,\n'
                        '  /assets/missing.png 2x">')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("broken local link: /assets/missing.png "
                      "(generated HTML line 2, column 3)", result.stderr)

        page.write_text('<div style="url(/assets/missing.png)"></div>')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("broken local link: /assets/missing.png "
                      "(generated HTML line 1, column 17)", result.stderr)

        page.write_text('<style>\nurl(/assets/missing.png)\n</style>')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("broken local link: /assets/missing.png "
                      "(generated HTML line 2, column 5)", result.stderr)

        page.unlink()
        sheet = self.site / "src/assets/location.css"
        sheet.write_text('/* CSS */\n.a { background: url(\n  ../missing.png\n) }')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{sheet}: broken local link: ../missing.png (line 3, column 3)",
                      result.stderr)

    def test_markdown_link_location_is_labeled_as_generated_html(self):
        page = self.site / "src/located.md"
        page.write_text('# Title\n\n[Missing](/missing/)\n')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{page}: broken local link: /missing/ "
                      "(generated HTML line 2, column 13)", result.stderr)

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
