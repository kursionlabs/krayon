"""End-to-end checks for a site built with Krayon's public CLI."""

from pathlib import Path
from html.parser import HTMLParser
import hashlib
import json
import os
import select
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen


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

    def routes(self, *flags):
        return subprocess.run(
            [str(KRAYON), "routes", str(self.site), *flags],
            text=True,
            capture_output=True,
        )

    def check(self, *flags):
        return subprocess.run(
            [str(KRAYON), "check", str(self.site), *flags],
            text=True,
            capture_output=True,
        )

    def test_check_validates_without_installing_output(self):
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.site / "dist").exists())
        self.assertEqual(list(self.site.glob("dist.krayon-*")), [])

        self.assertEqual(self.build().returncode, 0)
        previous = (self.site / "dist/index.html").read_bytes()
        (self.site / "dist/sentinel.txt").write_text("keep\n")
        home = self.site / "src/index.md"
        home.write_text(home.read_text() + "\nNew content.\n")
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.site / "dist/index.html").read_bytes(), previous)
        self.assertEqual((self.site / "dist/sentinel.txt").read_text(), "keep\n")
        self.assertEqual(list(self.site.glob("dist.krayon-*")), [])

        home.write_text(home.read_text() + "\n[Broken](/missing/)\n")
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("broken local link: /missing/", result.stderr)
        self.assertEqual((self.site / "dist/index.html").read_bytes(), previous)
        self.assertEqual(list(self.site.glob("dist.krayon-*")), [])

    def test_source_overlay_merges_pages_and_preserves_output_on_failure(self):
        overlay = Path(self.temp.name) / "generated"
        overlay.mkdir()
        home = overlay / "index.md"
        home.write_text((self.site / "src/index.md").read_text().replace(
            "# Welcome", "# Overlay home") + "\n[Generated](/generated/)\n")
        (overlay / "generated").mkdir()
        generated = overlay / "generated/index.md"
        generated.write_text("# Generated page\n")
        (overlay / "assets").mkdir()
        (overlay / "assets/generated.txt").write_text("generated asset\n")

        result = self.routes("--json", "--overlay", str(overlay))
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(result.stdout)
        self.assertIn({"source": "generated/index.md", "url": "/generated/",
                       "output": "generated/index.html"}, manifest["pages"])
        self.assertIn({"source": "assets/generated.txt", "url": "/assets/generated.txt",
                       "outputs": ["assets/generated.txt"]}, manifest["assets"])
        self.assertFalse((self.site / "dist").exists())

        result = self.check("--overlay", str(overlay))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.site / "dist").exists())
        result = self.build("--overlay", str(overlay))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Overlay home", (self.site / "dist/index.html").read_text())
        self.assertTrue((self.site / "dist/generated/index.html").is_file())
        self.assertEqual((self.site / "dist/assets/generated.txt").read_text(),
                         "generated asset\n")
        self.assertIn("# Welcome", (self.site / "src/index.md").read_text())
        previous = (self.site / "dist/index.html").read_bytes()

        generated.write_text("# Generated page\n\n[Missing](/missing/)\n")
        result = self.build("--overlay", str(overlay))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("broken local link", result.stderr)
        self.assertEqual((self.site / "dist/index.html").read_bytes(), previous)
        self.assertEqual(list(self.site.glob(".krayon-overlay*")), [])

        generated.write_text("# Generated page\n")
        (overlay / "escape.md").symlink_to(self.site / "src/index.md")
        result = self.check("--overlay", str(overlay))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("overlay source may not contain symlinks", result.stderr)
        self.assertEqual(list(self.site.glob(".krayon-overlay*")), [])

        result = self.routes("--overlay", str(self.site / "src"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("overlay must be outside input", result.stderr)
        self.assertEqual(result.stdout, "")

        result = self.build("--overlay")
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage:", result.stderr)

    def test_blog_example_builds_with_archives_drafts_and_base_path(self):
        blog = Path(self.temp.name) / "blog"
        shutil.copytree(ROOT / "examples/blog-site", blog,
                        ignore=shutil.ignore_patterns("dist"))

        def build_blog(*flags):
            return subprocess.run([str(KRAYON), "build", str(blog), *flags],
                                  text=True, capture_output=True)

        result = build_blog()
        self.assertEqual(result.returncode, 0, result.stderr)
        home = (blog / "dist/index.html").read_text()
        self.assertLess(home.index("/posts/third-post/"), home.index("/posts/second-post/"))
        self.assertLess(home.index("/posts/second-post/"), home.index("/posts/first-post/"))
        self.assertNotIn("/posts/next-idea/", home)
        self.assertFalse((blog / "dist/posts/next-idea/index.html").exists())
        self.assertIn("/posts/first-post/",
                      (blog / "dist/archive/page/2/index.html").read_text())
        self.assertIn("Newer: Browsing the archive",
                      (blog / "dist/posts/second-post/index.html").read_text())
        self.assertNotIn("/posts/third-post/",
                         (blog / "dist/topics/notes/index.html").read_text())
        atom_ns = {"atom": "http://www.w3.org/2005/Atom"}
        atom = ET.parse(blog / "dist/atom.xml").getroot()
        entries = atom.findall("atom:entry", atom_ns)
        self.assertEqual([entry.find("atom:title", atom_ns).text for entry in entries],
                         ["Browsing the archive", "A reusable layout", "Starting a small blog"])
        self.assertEqual(atom.find("atom:updated", atom_ns).text,
                         "2025-03-19T00:00:00Z")
        self.assertEqual(entries[0].find("atom:link", atom_ns).attrib["href"],
                         "https://example.com/posts/third-post/")
        sitemap_ns = {"map": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        sitemap = ET.parse(blog / "dist/sitemap.xml").getroot()
        locations = {entry.text for entry in sitemap.findall("map:url/map:loc", sitemap_ns)}
        self.assertIn("https://example.com/archive/page/2/", locations)
        self.assertNotIn("https://example.com/posts/next-idea/", locations)

        config = blog / "krayon.toml"
        config.write_text('base_path = "/journal"\n' + config.read_text())
        result = build_blog("--drafts")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((blog / "dist/posts/next-idea/index.html").exists())
        self.assertIn('href="/journal/posts/next-idea/"',
                      (blog / "dist/index.html").read_text())
        self.assertIn('href="/journal/archive/"',
                      (blog / "dist/about/index.html").read_text())
        atom = ET.parse(blog / "dist/atom.xml").getroot()
        self.assertEqual(atom.find("atom:updated", atom_ns).text,
                         "2025-04-01T00:00:00Z")
        self.assertEqual(len(atom.findall("atom:entry", atom_ns)), 4)
        sitemap = ET.parse(blog / "dist/sitemap.xml").getroot()
        locations = {entry.text for entry in sitemap.findall("map:url/map:loc", sitemap_ns)}
        self.assertIn("https://example.com/journal/posts/next-idea/", locations)
        self.assertIn("https://example.com/journal/archive/page/2/", locations)

    def test_portfolio_example_generates_project_pages(self):
        portfolio = Path(self.temp.name) / "portfolio"
        shutil.copytree(ROOT / "examples/portfolio-site", portfolio,
                        ignore=shutil.ignore_patterns("dist"))
        config = portfolio / "krayon.toml"
        config.write_text('base_path = "/studio"\n' + config.read_text())
        result = subprocess.run([str(KRAYON), "build", str(portfolio)],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        home = (portfolio / "dist/index.html").read_text()
        self.assertIn('href="/studio/work/field-guide/"', home)
        self.assertIn('href="/studio/work/open-shelf/"', home)
        self.assertIn('href="/studio/work/signal-notes/"', home)
        self.assertLess(home.index('id="group-Web"'), home.index('id="group-Writing"'))
        detail = (portfolio / "dist/work/field-guide/index.html").read_text()
        self.assertIn('<h1>Field Guide</h1>', detail)
        self.assertIn('<li>Kursal</li>', detail)
        self.assertIn('href="/studio/"', detail)
        self.assertIn('href="/studio/assets/css/site.css"', detail)

    def test_handbook_example_queries_navigation_and_builds_alias(self):
        handbook = Path(self.temp.name) / "handbook"
        shutil.copytree(ROOT / "examples/handbook-site", handbook,
                        ignore=shutil.ignore_patterns("dist"))
        config = handbook / "krayon.toml"
        config.write_text('base_path = "/handbook"\n' + config.read_text())
        result = subprocess.run([str(KRAYON), "build", str(handbook)],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        setup = (handbook / "dist/guide/setup/index.html").read_text()
        self.assertLess(setup.index('>Set up a project</a>'),
                        setup.index('>Write pages</a>'))
        self.assertLess(setup.index('>Write pages</a>'),
                        setup.index('>Publish the site</a>'))
        self.assertIn('<h1 id="setup" class="guide-heading">Set up a project</h1>', setup)
        self.assertIn('href="/handbook/guide/writing/"', setup)
        self.assertIn('<pre><code>input = &quot;src&quot;\noutput = &quot;dist&quot;\n</code></pre>', setup)
        writing = (handbook / "dist/guide/writing/index.html").read_text()
        self.assertIn('<table>\n<thead>\n<tr>\n<th align="left">Source</th>', writing)
        self.assertIn('<td align="left"><code>guide/writing.md</code></td>', writing)
        alias = (handbook / "dist/start/index.html").read_text()
        self.assertIn('/handbook/guide/setup/', alias)
        home = (handbook / "dist/index.html").read_text()
        self.assertIn('href="/handbook/guide/"', home)

    def test_preview_serves_drafts_and_overlay_without_replacing_output(self):
        self.site = Path(self.temp.name) / "preview site"
        (self.site / "src").mkdir(parents=True)
        (self.site / "src/index.md").write_text("# Preview home\n")
        (self.site / "krayon.toml").write_text('base_path = "/preview/blog"\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        dist = self.site / "dist"
        published = (dist / "index.html").read_bytes()
        (dist / "sentinel.txt").write_text("existing output")
        (self.site / "src/draft.md").write_text(
            '+++\ntitle = "Draft"\ndraft = true\n+++\nDraft preview text.\n')
        overlay = Path(self.temp.name) / "generated pages"
        overlay.mkdir()
        (overlay / "generated.md").write_text("# Overlay page\n")
        temporary = Path(self.temp.name) / "preview-workspaces"
        temporary.mkdir()
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        command = [str(KRAYON), "preview", str(self.site), "--drafts", "--overlay", str(overlay),
                   "--port", str(port)]
        env = os.environ | {"TMPDIR": str(temporary)}

        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, env=env) as process:
            try:
                ready, _, _ = select.select([process.stdout], [], [], 10)
                self.assertTrue(ready, "preview did not announce its address")
                announcement = process.stdout.readline()
                self.assertTrue(announcement.startswith("Preview at "), announcement)
                url = announcement.removeprefix("Preview at ").strip()
                self.assertEqual(urlsplit(url).hostname, "127.0.0.1")
                self.assertEqual(urlsplit(url).port, port)
                self.assertEqual(urlsplit(url).path, "/preview/blog/")
                with urlopen(url, timeout=5) as response:
                    self.assertEqual(response.headers.get("Accept-Ranges"), "bytes")
                    self.assertEqual(response.read(), published)
                for page, text in (("draft/", b"Draft preview text."),
                                   ("generated/", b"Overlay page")):
                    with urlopen(urljoin(url, page), timeout=5) as response:
                        self.assertIn(text, response.read())
                with self.assertRaises(HTTPError) as error:
                    urlopen(urljoin(url, "/"), timeout=5)
                with error.exception as response:
                    self.assertEqual(response.code, 404)
                self.assertFalse((dist / "draft").exists())
                self.assertFalse((dist / "generated").exists())
                self.assertEqual((dist / "sentinel.txt").read_text(), "existing output")
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    _, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                    raise
            self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(list(temporary.iterdir()), [])

    def test_preview_rejects_invalid_ports(self):
        for flags in (["--port"], ["--port", "-1"], ["--port", "65536"],
                      ["--port", "abc"], ["--port", "0", "--port", "1"]):
            with self.subTest(flags=flags):
                result = subprocess.run([str(KRAYON), "preview", str(self.site), *flags],
                                        text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertIn("--port", result.stderr)

    def test_preview_reports_occupied_port(self):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            reservation.listen()
            port = reservation.getsockname()[1]
            result = subprocess.run([str(KRAYON), "preview", str(self.site), "--port", str(port)],
                                    text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn(f"cannot bind preview on port {port}", result.stderr)

    def test_preview_validation_failure_cleans_up(self):
        temporary = Path(self.temp.name) / "preview-workspaces"
        temporary.mkdir()
        home = self.site / "src/index.md"
        home.write_text(home.read_text() + "\n[Broken preview link](/missing/)\n")
        result = subprocess.run([str(KRAYON), "preview", str(self.site)],
                                env=os.environ | {"TMPDIR": str(temporary)},
                                text=True, capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("/missing/", result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertFalse((self.site / "dist").exists())
        self.assertEqual(list(temporary.iterdir()), [])

    def test_documentation_site_builds_with_base_path(self):
        docs = Path(self.temp.name) / "docs"
        shutil.copytree(ROOT / "docs", docs,
                        ignore=shutil.ignore_patterns("dist"))

        def build_docs(command):
            return subprocess.run([str(KRAYON), command, str(docs)],
                                  text=True, capture_output=True)

        def build_full_docs():
            return subprocess.run([sys.executable, str(ROOT / "scripts/build_docs.py"),
                                   "--site", str(docs), "--krayon", str(KRAYON),
                                   "--kursal", str(KURSAL)],
                                  text=True, capture_output=True)

        result = build_full_docs()
        self.assertEqual(result.returncode, 0, result.stderr)
        home = (docs / "dist/index.html").read_text()
        self.assertIn('href="/start/"', home)
        self.assertIn('href="/blog/"', home)
        self.assertIn('href="/assets/css/docs.css"', home)
        self.assertIn('src="/assets/js/theme.js"', home)
        self.assertIn("krayon-docs-theme", home)
        self.assertTrue((docs / "dist/templates/index.html").is_file())
        self.assertTrue((docs / "dist/validation/index.html").is_file())
        self.assertIn('href="/api/"', home)
        self.assertFalse((docs / "dist/api/krayon").exists())
        self.assertTrue((docs / "dist/api/site/index.html").is_file())
        self.assertTrue((docs / "dist/api/search-index.json").is_file())
        owned = {path.parent.name for path in (ROOT / "lib").glob("*/kur.toml")}
        api_root = docs / "dist/api"
        self.assertEqual({path.name for path in api_root.iterdir() if path.is_dir()}
                         - {"assets", "src"}, owned)
        self.assertEqual({path.name for path in (api_root / "src").iterdir()
                          if path.is_dir()}, owned)
        search_entries = json.loads((api_root / "search-index.json").read_text())
        self.assertTrue(search_entries)
        self.assertTrue(all(entry["u"].lstrip("/").split("/")[0] in owned
                            for entry in search_entries))
        api = (docs / "dist/api/index.html").read_text()
        self.assertIn('content="/api/"', api)
        self.assertIn('href="/">Guides</a>', api)
        self.assertIn("Packages · Krayon Docs", api)
        self.assertIn('class="site-header api-header"', api)
        self.assertIn('class="docs-content api-content docs-home"', api)
        self.assertIn('class="theme-toggle"', api)
        self.assertIn("krayon-docs-theme", api)
        self.assertIn('href="/assets/css/docs.css"', api)
        self.assertIn('href="/assets/api/site.css"', api)
        self.assertIn('src="/assets/js/theme.js"', api)
        self.assertEqual((docs / "dist/assets/css/docs.css").read_text(),
                         (docs / "src/assets/css/docs.css").read_text())
        self.assertEqual((docs / "dist/assets/js/theme.js").read_text(),
                         (docs / "src/assets/js/theme.js").read_text())
        self.assertTrue((docs / "dist/assets/api/search.js").is_file())
        module = (api_root / "site/index.html").read_text()
        self.assertIn('class="tree-current" aria-current="page" href="/api/site/"',
                      module)
        config_page = (api_root / "site/struct.Config.html").read_text()
        self.assertIn('href="/api/site/struct.Config.html" aria-current="page"',
                      config_page)
        self.assertIn('class="tree-current" aria-current="location" href="/api/site/"',
                      config_page)
        self.assertIn('/assets/api/nav.js', config_page)
        for dependency in ("std", "core", "alloc", "libc", "toml"):
            self.assertNotIn(f'href="{dependency}/"', api)
            self.assertFalse((api_root / dependency).exists())

        class LocalLinks(HTMLParser):
            def __init__(self):
                super().__init__()
                self.hrefs = []

            def handle_starttag(self, tag, attrs):
                self.hrefs.extend(value for key, value in attrs
                                  if key in {"href", "src"} and value)

        for page in api_root.rglob("*.html"):
            links = LocalLinks()
            links.feed(page.read_text())
            page_url = "https://krayon.invalid/api/" + page.relative_to(api_root).as_posix()
            for href in links.hrefs:
                target = urlsplit(urljoin(page_url, href))
                if target.netloc != "krayon.invalid" or not target.path.startswith("/api/"):
                    continue
                output = api_root / target.path.removeprefix("/api/")
                if output.is_dir():
                    output /= "index.html"
                self.assertTrue(output.is_file(), f"{page}: broken API link {href}")

        config = docs / "krayon.toml"
        config.write_text('base_path = "/krayon"\n' + config.read_text())
        result = build_docs("check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((docs / "dist/index.html").read_text(), home)
        result = build_full_docs()
        self.assertEqual(result.returncode, 0, result.stderr)
        home = (docs / "dist/index.html").read_text()
        self.assertIn('href="/krayon/start/"', home)
        self.assertIn('href="/krayon/assets/css/docs.css"', home)
        self.assertIn('href="/krayon/templates/"', home)
        self.assertIn('href="/krayon/api/"', home)
        api = (docs / "dist/api/index.html").read_text()
        self.assertIn('content="/krayon/api/"', api)
        self.assertIn('href="/krayon/assets/css/docs.css"', api)
        self.assertIn('href="/krayon/assets/api/site.css"', api)
        self.assertIn('src="/krayon/assets/js/theme.js"', api)
        self.assertIn('href="/krayon/">Guides</a>', api)
        config_page = (docs / "dist/api/site/struct.Config.html").read_text()
        self.assertIn('href="/krayon/api/site/struct.Config.html" aria-current="page"',
                      config_page)

        previous = (docs / "dist/api/index.html").read_bytes()
        layout = docs / "api-theme/src/_includes/api-page.html"
        layout.write_text(layout.read_text().replace(
            '<div class="site-shell api-shell">',
            '<div class="site-shell api-shell"><a href="{{ "/api/std/" | url }}">Removed dependency</a>'))
        result = build_full_docs()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("broken local link", result.stderr)
        self.assertEqual((docs / "dist/api/index.html").read_bytes(), previous)

    def test_check_accepts_drafts_and_reports_template_errors(self):
        draft = self.site / "src/draft.md"
        draft.write_text('+++\ndraft = true\n+++\n# Draft\n')
        home = self.site / "src/index.md"
        home.write_text(home.read_text() + "\n[Draft](/draft/)\n")
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("broken local link: /draft/", result.stderr)
        result = self.check("--drafts")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.site / "dist").exists())
        self.assertEqual(list(self.site.glob("dist.krayon-*")), [])

        layout = self.site / "src/_includes/base.html"
        layout.write_text(layout.read_text() + "{{ site.unknown }}\n")
        result = self.check("--drafts")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("site.unknown", result.stderr)
        self.assertFalse((self.site / "dist").exists())
        self.assertEqual(list(self.site.glob("dist.krayon-*")), [])

    def test_optional_asset_fingerprinting_and_asset_url_filter(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        (src / "assets/css").mkdir(parents=True)
        (src / "assets/js").mkdir()
        (src / "assets/img").mkdir()
        (src / "posts").mkdir()
        config = self.site / "krayon.toml"
        config.write_text('base_path = "/docs"\n')
        (src / "assets/css/site.css").write_text(
            'body { background: url("../img/logo.png"); }\n')
        (src / "assets/js/app.js").write_text('console.log("one");\n')
        (src / "assets/img/logo.png").write_bytes(b"image one\n")
        (src / "index.html").write_text(
            '<link rel="stylesheet" href="{{ "/assets/css/site.css" | asset_url }}">'
            '<script src="{{ "/assets/js/app.js" | asset_url }}"></script>'
            '<img src="{{ "/assets/img/logo.png" | asset_url }}" alt="Logo">')
        (src / "manifest.json").write_text(
            '{{ "/assets/js/app.js?mode=1#run" | asset_url | json }}')
        (src / "posts/article.md").write_text(
            '# Article\n\n'
            '![Root](/assets/img/logo.png?size=1#view)\n\n'
            '<!-- more -->\n\n'
            '![External](https://example.org/image.png)\n\n'
            '[CSS](/assets/css/site.css)\n')
        (src / "excerpts.html").write_text(
            '{% for entry in collections.pages %}'
            '{% if entry.url == "/posts/article/" %}{{ entry.excerpt | safe }}{% endif %}'
            '{% endfor %}')

        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('href="/docs/assets/css/site.css"',
                      (self.site / "dist/index.html").read_text())
        self.assertEqual(list((self.site / "dist/assets/css").glob("site.*.css")), [])
        self.assertIn('<img src="/docs/assets/img/logo.png?size=1#view" alt="Root">',
                      (self.site / "dist/posts/article/index.html").read_text())

        config.write_text('base_path = "/docs"\nfingerprint_assets = true\n')
        article_source = src / "posts/article.md"
        article_source.write_text(article_source.read_text().replace(
            '![Root]', '![Relative](../assets/img/logo.png)\n\n![Root]'))
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.site / "dist"
        css = list((output / "assets/css").glob("site.*.css"))
        js = list((output / "assets/js").glob("app.*.js"))
        image = list((output / "assets/img").glob("logo.*.png"))
        self.assertEqual([len(paths) for paths in (css, js, image)], [1, 1, 1])
        html = (output / "index.html").read_text()
        self.assertIn(f'href="/docs/assets/css/{css[0].name}"', html)
        self.assertIn(f'src="/docs/assets/js/{js[0].name}"', html)
        self.assertIn(f'src="/docs/assets/img/{image[0].name}"', html)
        article = (output / "posts/article/index.html").read_text()
        self.assertIn(f'<img src="/docs/assets/img/{image[0].name}" alt="Relative">', article)
        self.assertIn(f'<img src="/docs/assets/img/{image[0].name}?size=1#view" alt="Root">', article)
        self.assertIn('<img src="https://example.org/image.png" alt="External">', article)
        self.assertIn(f'<a href="/docs/assets/css/{css[0].name}">CSS</a>', article)
        self.assertIn(f'<img src="/docs/assets/img/{image[0].name}" alt="Relative">',
                      (output / "excerpts/index.html").read_text())
        self.assertEqual(json.loads((output / "manifest.json").read_text()),
                         f'/docs/assets/js/{js[0].name}?mode=1#run')
        self.assertEqual((output / "assets/css/site.css").read_text(),
                         'body { background: url("../img/logo.png"); }\n')
        self.assertIn(f'url("/docs/assets/img/{image[0].name}")',
                      css[0].read_text())
        self.assertEqual(css[0].name,
                         f'site.{hashlib.sha256(css[0].read_bytes()).hexdigest()}.css')
        self.assertEqual(js[0].read_bytes(), (output / "assets/js/app.js").read_bytes())
        self.assertEqual(image[0].read_bytes(), (output / "assets/img/logo.png").read_bytes())

        (src / "assets/js/app.js").write_text('console.log("two");\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        changed_js = list((output / "assets/js").glob("app.*.js"))
        self.assertEqual(len(changed_js), 1)
        self.assertNotEqual(changed_js[0].name, js[0].name)
        self.assertEqual(list((output / "assets/css").glob("site.*.css"))[0].name, css[0].name)

        (src / "assets/img/logo.png").write_bytes(b"image two\n")
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        changed_css = list((output / "assets/css").glob("site.*.css"))
        changed_image = list((output / "assets/img").glob("logo.*.png"))
        self.assertEqual(len(changed_css), 1)
        self.assertEqual(len(changed_image), 1)
        self.assertNotEqual(changed_css[0].name, css[0].name)
        self.assertNotEqual(changed_image[0].name, image[0].name)
        self.assertIn(f'url("/docs/assets/img/{changed_image[0].name}")',
                      changed_css[0].read_text())
        self.assertIn(f'href="/docs/assets/css/{changed_css[0].name}"',
                      (output / "index.html").read_text())
        self.assertEqual((output / "assets/css/site.css").read_text(),
                         'body { background: url("../img/logo.png"); }\n')

        (src / "index.html").write_text('{{ "/assets/missing.css" | asset_url }}')
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('asset_url', result.stderr)
        self.assertEqual(changed_js[0].read_text(), 'console.log("two");\n')

        config.write_text('fingerprint_assets = "yes"\n')
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('fingerprint_assets must be a boolean', result.stderr)
        self.assertEqual(changed_js[0].read_text(), 'console.log("two");\n')

    def test_fingerprinted_css_rewrites_only_local_asset_urls(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        (src / "assets/css").mkdir(parents=True)
        (src / "assets/img").mkdir()
        (self.site / "krayon.toml").write_text(
            'base_path = "/docs"\nfingerprint_assets = true\n')
        (src / "assets/img/my image.png").write_bytes(b"spaced image")
        (src / "assets/img/logo.png").write_bytes(b"logo")
        sheet = src / "assets/css/site.css"
        original = (
            '/* url(../img/ignored.png) */\n'
            '.label { content: "url(../img/ignored.png)"; }\n'
            '.space { background: url(../img/my\\ image.png) }\n'
            '.root { background: url("/docs/assets/img/logo.png?size=1#view") }\n'
            '.remote { background: url(https://example.org/photo.png) }\n'
            '.data { background: url(data:image/png;base64,AAAA) }\n'
        )
        sheet.write_text(original)
        (src / "index.html").write_text(
            '<link rel="stylesheet" href="{{ "/assets/css/site.css" | asset_url }}">')

        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.site / "dist/assets"
        hashed_css = list((output / "css").glob("site.*.css"))
        spaced = list((output / "img").glob("my image.*.png"))
        logo = list((output / "img").glob("logo.*.png"))
        self.assertEqual([len(items) for items in (hashed_css, spaced, logo)], [1, 1, 1])
        rewritten = hashed_css[0].read_text()
        self.assertIn(f'url(/docs/assets/img/{spaced[0].name.replace(" ", "%20")})', rewritten)
        self.assertIn(f'url("/docs/assets/img/{logo[0].name}?size=1#view")', rewritten)
        self.assertIn('/* url(../img/ignored.png) */', rewritten)
        self.assertIn('content: "url(../img/ignored.png)"', rewritten)
        self.assertIn('url(https://example.org/photo.png)', rewritten)
        self.assertIn('url(data:image/png;base64,AAAA)', rewritten)
        self.assertEqual((output / "css/site.css").read_text(), original)

    def test_css_fingerprints_follow_imports_and_report_cycles(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        (src / "assets/css").mkdir(parents=True)
        (src / "assets/img").mkdir()
        (self.site / "krayon.toml").write_text('fingerprint_assets = true\n')
        image = src / "assets/img/logo.png"
        image.write_bytes(b"first")
        child = src / "assets/css/child.css"
        child.write_text('.child { background: url(../img/logo.png) }\n')
        parent = src / "assets/css/parent.css"
        parent.write_text('@import url(child.css);\n')
        (src / "index.html").write_text(
            '<link rel="stylesheet" href="{{ "/assets/css/parent.css" | asset_url }}">')

        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.site / "dist"
        first_parent = list((output / "assets/css").glob("parent.*.css"))[0]
        first_child = list((output / "assets/css").glob("child.*.css"))[0]
        first_image = list((output / "assets/img").glob("logo.*.png"))[0]
        self.assertIn(f'url(/assets/css/{first_child.name})', first_parent.read_text())
        self.assertIn(f'url(/assets/img/{first_image.name})', first_child.read_text())

        image.write_bytes(b"second")
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        second_parent = list((output / "assets/css").glob("parent.*.css"))[0]
        second_child = list((output / "assets/css").glob("child.*.css"))[0]
        self.assertNotEqual(second_parent.name, first_parent.name)
        self.assertNotEqual(second_child.name, first_child.name)
        self.assertIn(f'url(/assets/css/{second_child.name})', second_parent.read_text())
        previous = (output / "index.html").read_bytes()

        child.write_text('@import url(parent.css);\n')
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('CSS dependency cycle', result.stderr)
        self.assertEqual((output / "index.html").read_bytes(), previous)

    def test_quoted_css_imports_are_rewritten_checked_and_follow_dependencies(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        (src / "assets/css").mkdir(parents=True)
        (src / "assets/img").mkdir()
        (self.site / "krayon.toml").write_text(
            'base_path = "/docs"\nfingerprint_assets = true\n')
        image = src / "assets/img/logo.png"
        image.write_bytes(b"first")
        grand = src / "assets/css/grand.css"
        grand.write_text('.icon { background: url(../img/logo.png) }\n')
        child = src / "assets/css/child.css"
        child.write_text("@import 'grand.css' layer(base);\n")
        parent = src / "assets/css/parent.css"
        original = (
            '/* @import "missing-comment.css"; */\n'
            '@import /* note */ "child.css?version=1" screen;\n'
            '@IMPORT "ch\\69ld.css";\n'
            '@import "https://elsewhere.example/remote.css";\n'
            '@imported "missing-name.css";\n'
            '.label { content: "@import \'missing-string.css\'"; }\n'
            '.custom { --raw: @import "missing-declaration.css"; }\n'
        )
        parent.write_text(original)
        (src / "index.html").write_text(
            '<link rel="stylesheet" href="{{ "/assets/css/parent.css" | asset_url }}">'
            '<div style=\'--raw: @import "missing-style.css";\'></div>')

        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.site / "dist"
        css = output / "assets/css"
        first_parent = list(css.glob("parent.*.css"))[0]
        first_child = list(css.glob("child.*.css"))[0]
        first_grand = list(css.glob("grand.*.css"))[0]
        first_image = list((output / "assets/img").glob("logo.*.png"))[0]
        rewritten = first_parent.read_text()
        self.assertIn(f'@import /* note */ "/docs/assets/css/{first_child.name}?version=1" screen;',
                      rewritten)
        self.assertIn(f'@IMPORT "/docs/assets/css/{first_child.name}";', rewritten)
        self.assertIn(f"@import '/docs/assets/css/{first_grand.name}' layer(base);",
                      first_child.read_text())
        self.assertIn(f'url(/docs/assets/img/{first_image.name})', first_grand.read_text())
        self.assertIn('@import "missing-comment.css"', rewritten)
        self.assertIn("@import 'missing-string.css'", rewritten)
        self.assertIn('@import "https://elsewhere.example/remote.css"', rewritten)
        self.assertEqual((css / "parent.css").read_text(), original)

        image.write_bytes(b"second")
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        second_parent = list(css.glob("parent.*.css"))[0]
        second_child = list(css.glob("child.*.css"))[0]
        second_grand = list(css.glob("grand.*.css"))[0]
        self.assertNotEqual(second_parent.name, first_parent.name)
        self.assertNotEqual(second_child.name, first_child.name)
        self.assertNotEqual(second_grand.name, first_grand.name)
        previous = (output / "index.html").read_bytes()

        grand.write_text("@import 'parent.css';\n")
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('CSS dependency cycle', result.stderr)
        self.assertEqual((output / "index.html").read_bytes(), previous)

        grand.write_text('.icon { background: url(../img/logo.png) }\n')
        parent.write_text('@import "missing.css";\n')
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f'{parent}: broken local link: missing.css', result.stderr)
        self.assertEqual((output / "index.html").read_bytes(), previous)

        parent.write_text(original)
        (src / "index.html").write_text('<style>@import "missing.css";</style>')
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f'{src / "index.html"}: broken local link: missing.css', result.stderr)
        self.assertEqual((output / "index.html").read_bytes(), previous)

    def test_markdown_asset_links_use_fingerprints_and_page_links_keep_routes(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        (src / "assets/docs").mkdir(parents=True)
        (src / "posts").mkdir()
        (self.site / "krayon.toml").write_text(
            'base_path = "/docs"\nfingerprint_assets = true\n')
        (src / "assets/docs/manual.pdf").write_bytes(b"%PDF example")
        (src / "assets/docs/notes.md").write_text("# Downloadable notes\n")
        (src / "guide.md").write_text(
            '+++\npermalink = "/manual/"\n+++\n# Setup\n')
        article = src / "posts/article.md"
        article.write_text(
            '# Article\n\n'
            '[Download](../assets/docs/manual.pdf?version=1#file)\n\n'
            '[Notes](/assets/docs/notes.md)\n\n'
            '[Guide](../guide.md#setup)\n\n'
            '[External](https://example.org/manual.pdf)\n\n'
            '<!-- more -->\n')
        (src / "excerpts.html").write_text(
            '{% for entry in collections.pages %}'
            '{% if entry.url == "/posts/article/" %}{{ entry.excerpt | safe }}{% endif %}'
            '{% endfor %}')

        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.site / "dist"
        pdf = list((output / "assets/docs").glob("manual.*.pdf"))
        notes = list((output / "assets/docs").glob("notes.*.md"))
        self.assertEqual([len(pdf), len(notes)], [1, 1])
        html = (output / "posts/article/index.html").read_text()
        self.assertIn(f'href="/docs/assets/docs/{pdf[0].name}?version=1#file"', html)
        self.assertIn(f'href="/docs/assets/docs/{notes[0].name}"', html)
        self.assertIn('href="/docs/manual/#setup"', html)
        self.assertIn('href="https://example.org/manual.pdf"', html)
        excerpt = (output / "excerpts/index.html").read_text()
        self.assertIn(f'href="/docs/assets/docs/{pdf[0].name}?version=1#file"', excerpt)

        previous = (output / "posts/article/index.html").read_bytes()
        article.write_text(article.read_text() + '[Missing](/assets/docs/missing.pdf)\n')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('broken local link: /docs/assets/docs/missing.pdf', result.stderr)
        self.assertEqual((output / "posts/article/index.html").read_bytes(), previous)

    def test_asset_fingerprints_match_sha256_for_binary_and_padding_boundaries(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        (src / "assets/files").mkdir(parents=True)
        (self.site / "krayon.toml").write_text('fingerprint_assets = true\n')
        (src / "index.html").write_text("Ready")
        vectors = {
            "empty.bin": b"",
            "abc.bin": b"abc",
            "55.bin": b"a" * 55,
            "56.bin": b"a" * 56,
            "63.bin": b"a" * 63,
            "64.bin": b"a" * 64,
            "65.bin": b"a" * 65,
            "binary.bin": bytes(range(256)),
        }
        known = {
            "empty.bin": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "abc.bin": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        }
        for name, payload in vectors.items():
            (src / "assets/files" / name).write_bytes(payload)

        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.site / "dist/assets/files"
        for name, payload in vectors.items():
            stem, suffix = name.rsplit(".", 1)
            digest = known.get(name, hashlib.sha256(payload).hexdigest())
            self.assertEqual((output / f"{stem}.{digest}.{suffix}").read_bytes(), payload)

    def test_large_binary_asset_streams_with_matching_fingerprint(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        (src / "assets/media").mkdir(parents=True)
        (self.site / "krayon.toml").write_text('fingerprint_assets = true\n')
        (src / "index.html").write_text(
            '<a href="{{ "/assets/media/video.bin" | asset_url }}">Video</a>')
        payload = bytes(range(256)) * 4096 + b"end"
        (src / "assets/media/video.bin").write_bytes(payload)

        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        digest = hashlib.sha256(payload).hexdigest()
        output = self.site / "dist/assets/media"
        self.assertEqual((output / "video.bin").read_bytes(), payload)
        self.assertEqual((output / f"video.{digest}.bin").read_bytes(), payload)
        self.assertIn(f'/assets/media/video.{digest}.bin',
                      (self.site / "dist/index.html").read_text())
        self.assertEqual(list(self.site.glob("dist.krayon-*")), [])

        (self.site / "krayon.toml").write_text('fingerprint_assets = false\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((output / "video.bin").read_bytes(), payload)
        self.assertFalse((output / f"video.{digest}.bin").exists())

    def test_init_creates_buildable_site_and_refuses_existing_content(self):
        target = Path(self.temp.name) / "nested/new-site"
        result = subprocess.run(
            [str(KRAYON), "init", str(target)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "Krayon site created\n")
        self.assertEqual((target / ".gitignore").read_text(), "/dist/\n")
        self.assertTrue((target / "krayon.toml").is_file())
        self.assertTrue((target / "src/index.md").is_file())
        self.assertTrue((target / "src/_includes/base.html").is_file())
        self.assertFalse((target / "dist").exists())

        result = subprocess.run(
            [str(KRAYON), "build", str(target)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Welcome to Krayon", (target / "dist/index.html").read_text())

        original = (target / "src/index.md").read_bytes()
        result = subprocess.run(
            [str(KRAYON), "init", str(target)], text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("directory is not empty", result.stderr)
        self.assertEqual((target / "src/index.md").read_bytes(), original)

    def test_init_accepts_empty_directory_and_rejects_invalid_arguments(self):
        target = Path(self.temp.name) / "empty"
        target.mkdir()
        result = subprocess.run(
            [str(KRAYON), "init"], cwd=target, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((target / "src/index.md").exists())

        for argument in ("--drafts", ""):
            result = subprocess.run(
                [str(KRAYON), "init", argument], cwd=self.temp.name,
                text=True, capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("usage:", result.stderr)

    def test_routes_list_discovered_pages_and_aliases_without_writing(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        (src / "_data").mkdir(parents=True)
        (self.site / "krayon.toml").write_text(
            'base_path = "/docs"\nexclude = ["private.md"]\n')
        (src / "_data/site.toml").write_text(
            'items = [{slug = "a"}, {slug = "b", draft = true}]\n')
        (src / "index.md").write_text('# Home\n')
        (src / "new.md").write_text(
            '+++\npermalink = "/latest/"\naliases = ["/old/"]\n+++\n# New\n')
        (src / "draft.md").write_text('+++\ndraft = true\n+++\n# Draft\n')
        (src / "private.md").write_text('# Private\n')
        (src / "item.json").write_text(
            '+++\ngenerate = "site.items"\n'
            'permalink = "/data/{{ item.slug }}.json"\n+++\n{}\n')
        (src / "archive.html").write_text(
            '+++\npaginate = "collections.pages"\npage_size = 1\n+++\nArchive\n')

        result = self.routes()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout,
                         'page\tindex.md\t/docs/\n'
                         'page\tarchive.html [page 1]\t/docs/archive/\n'
                         'page\tarchive.html [page 2]\t/docs/archive/page/2/\n'
                         'page\titem.json [item 1]\t/docs/data/a.json\n'
                         'page\tnew.md\t/docs/latest/\n'
                         'alias\t/docs/old/\t/docs/latest/\n')
        self.assertFalse((self.site / "dist").exists())
        self.assertEqual(list(self.site.glob("dist.krayon-*")), [])

        result = self.routes("--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "pages": [
                {"source": "index.md", "url": "/docs/", "output": "index.html"},
                {"source": "archive.html [page 1]", "url": "/docs/archive/",
                 "output": "archive/index.html"},
                {"source": "archive.html [page 2]", "url": "/docs/archive/page/2/",
                 "output": "archive/page/2/index.html"},
                {"source": "item.json [item 1]", "url": "/docs/data/a.json",
                 "output": "data/a.json"},
                {"source": "new.md", "url": "/docs/latest/", "output": "latest/index.html"},
            ],
            "aliases": [{"url": "/docs/old/", "target": "/docs/latest/",
                         "output": "old/index.html"}],
            "assets": [],
        })
        self.assertTrue(result.stdout.endswith("\n"))
        self.assertFalse((self.site / "dist").exists())

        result = self.routes("--drafts")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('page\tdraft.md\t/docs/draft/\n', result.stdout)
        self.assertIn('page\titem.json [item 2]\t/docs/data/b.json\n', result.stdout)
        self.assertNotIn('private.md', result.stdout)
        self.assertFalse((self.site / "dist").exists())

        result = self.routes("--json", "--drafts")
        self.assertEqual(result.returncode, 0, result.stderr)
        pages = json.loads(result.stdout)["pages"]
        self.assertIn({"source": "draft.md", "url": "/docs/draft/",
                       "output": "draft/index.html"}, pages)
        self.assertIn({"source": "item.json [item 2]", "url": "/docs/data/b.json",
                       "output": "data/b.json"}, pages)
        self.assertNotIn("private.md", [page["source"] for page in pages])

        (self.site / "dist").mkdir()
        (self.site / "dist/sentinel.txt").write_text("keep\n")
        result = self.routes()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.site / "dist/sentinel.txt").read_text(), "keep\n")

    def test_routes_fail_without_partial_listing_or_output_changes(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        src.mkdir()
        (src / "one.md").write_text('+++\naliases = ["/two/"]\n+++\n# One\n')
        (src / "two.md").write_text('# Two\n')
        result = self.routes()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn('output collision', result.stderr)
        self.assertFalse((self.site / "dist").exists())

        result = self.routes("--json")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn('output collision', result.stderr)

    def test_routes_json_escapes_paths_and_rejects_invalid_flags(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        (src / "assets").mkdir(parents=True)
        (self.site / "krayon.toml").write_text('output = "public"\n')
        (src / "index.md").write_text("# Home\n")
        name = 'say"hello\tworld.txt'
        (src / "assets" / name).write_text("hello")
        result = self.routes("--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(result.stdout)
        self.assertEqual(manifest["pages"],
                         [{"source": "index.md", "url": "/", "output": "index.html"}])
        self.assertEqual(manifest["assets"],
                         [{"source": f"assets/{name}", "url": f"/assets/{name}",
                           "outputs": [f"assets/{name}"]}])
        self.assertIn('say\\"hello\\tworld.txt', result.stdout)
        self.assertFalse((self.site / "public").exists())

        for command in ("build", "check"):
            result = subprocess.run([str(KRAYON), command, str(self.site), "--json"],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("usage:", result.stderr)
        result = self.routes("--json", "--json")
        self.assertEqual(result.returncode, 2)

    def test_routes_include_sorted_asset_mappings_without_writing(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        (src / "assets").mkdir(parents=True)
        (self.site / "krayon.toml").write_text(
            'base_path = "/docs"\nfingerprint_assets = true\n')
        (src / "index.md").write_text("# Home\n")
        data = b"binary asset\x00\xff"
        (src / "assets/a.bin").write_bytes(data)
        css_source = 'body { background: url(a.bin) }\n'
        (src / "assets/z.css").write_text(css_source)
        data_hash = hashlib.sha256(data).hexdigest()
        css_rewritten = f'body {{ background: url(/docs/assets/a.{data_hash}.bin) }}\n'
        css_hash = hashlib.sha256(css_rewritten.encode()).hexdigest()

        result = self.routes()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout,
                         'page\tindex.md\t/docs/\n'
                         f'asset\tassets/a.bin\t/docs/assets/a.{data_hash}.bin\n'
                         f'asset\tassets/z.css\t/docs/assets/z.{css_hash}.css\n')
        self.assertFalse((self.site / "dist").exists())
        self.assertEqual(list(self.site.glob("dist.krayon-*")), [])

        result = self.routes("--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["assets"], [
            {"source": "assets/a.bin", "url": f"/docs/assets/a.{data_hash}.bin",
             "outputs": ["assets/a.bin", f"assets/a.{data_hash}.bin"]},
            {"source": "assets/z.css", "url": f"/docs/assets/z.{css_hash}.css",
             "outputs": ["assets/z.css", f"assets/z.{css_hash}.css"]},
        ])

        (self.site / "krayon.toml").write_text('base_path = "/docs"\n')
        result = self.routes()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout,
                         'page\tindex.md\t/docs/\n'
                         'asset\tassets/a.bin\t/docs/assets/a.bin\n'
                         'asset\tassets/z.css\t/docs/assets/z.css\n')
        self.assertFalse((self.site / "dist").exists())

        result = self.routes("--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["assets"], [
            {"source": "assets/a.bin", "url": "/docs/assets/a.bin",
             "outputs": ["assets/a.bin"]},
            {"source": "assets/z.css", "url": "/docs/assets/z.css",
             "outputs": ["assets/z.css"]},
        ])

    def test_routes_json_output_paths_match_emitted_files(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        (src / "assets").mkdir(parents=True)
        (self.site / "krayon.toml").write_text(
            'base_path = "/docs"\nfingerprint_assets = true\n')
        (src / "index.md").write_text('# Home\n')
        (src / "guide.md").write_text(
            '+++\naliases = ["/old/"]\n+++\n# Guide\n')
        (src / "assets/app.css").write_text('body { color: navy }\n')
        (src / "assets/logo.bin").write_bytes(b'logo')

        result = self.routes("--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(result.stdout)
        self.assertFalse((self.site / "dist").exists())
        paths = {item["output"] for item in manifest["pages"] + manifest["aliases"]}
        for asset in manifest["assets"]:
            paths.update(asset["outputs"])
        self.assertEqual(len(paths), 7)

        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        emitted = {path.relative_to(self.site / "dist").as_posix()
                   for path in (self.site / "dist").rglob("*") if path.is_file()}
        self.assertEqual(paths, emitted)

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
        self.assertIn('<h1 id="welcome">Welcome</h1>', home)
        self.assertIn("Hello &amp; welcome", home)
        self.assertIn("<main><article>", note)
        self.assertIn("<em>italic</em>", note)
        self.assertIn("<ol>", note)
        self.assertIn("https://example.org/source?a=1&amp;b=2", note)
        self.assertEqual((self.site / "dist/assets/css/site.css").read_text(),
                         "body { font-family: sans-serif; }\n")

    def test_directory_defaults_inherit_and_pages_override_them(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        (src / "posts/deep").mkdir(parents=True)
        (src / "products").mkdir()
        (src / "drafts").mkdir()
        (src / "_includes").mkdir()
        (src / "_data").mkdir()
        (src / "_includes/base.html").write_text(
            '<main>{{ page.kind }}:{{ page.title }}:{% if page.tags %}tagged{% endif %}'
            '{{ content | safe }}</main>')
        (src / "_defaults.toml").write_text(
            'layout = "base.html"\nkind = "root"\ntitle = "Untitled"\n')
        (src / "posts/_defaults.toml").write_text(
            'kind = "post"\ntitle = "Post"\n')
        (src / "posts/deep/_defaults.toml").write_text('tags = ["deep"]\n')
        (src / "products/_defaults.toml").write_text('kind = "product"\n')
        (src / "drafts/_defaults.toml").write_text('draft = true\n')
        (src / "_data/site.toml").write_text('[[items]]\nslug = "widget"\ntitle = "Widget"\n')
        (src / "root.md").write_text('# Root\n')
        (src / "posts/one.md").write_text('# One\n')
        (src / "posts/deep/two.md").write_text(
            '+++\nkind = "special"\ntitle = "Two"\nlayout = ""\n+++\n# Two\n')
        (src / "posts/deep/three.md").write_text('# Three\n')
        (src / "drafts/hidden.md").write_text('# Hidden\n')
        (src / "drafts/visible.md").write_text('+++\ndraft = false\n+++\n# Visible\n')
        (src / "about.html").write_text('<p>About</p>')
        (src / "products/product.html").write_text(
            '+++\ngenerate = "site.items"\n'
            'permalink = "/products/{{ item.slug }}/"\n+++\n<p>Generated</p>')

        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('<main>root:Untitled:', (self.site / "dist/root/index.html").read_text())
        self.assertIn('<main>post:Post:', (self.site / "dist/posts/one/index.html").read_text())
        self.assertIn('<main>post:Post:tagged', (self.site / "dist/posts/deep/three/index.html").read_text())
        self.assertEqual((self.site / "dist/posts/deep/two/index.html").read_text(),
                         '<h1 id="two">Two</h1>\n')
        self.assertIn('<main>root:Untitled:', (self.site / "dist/about/index.html").read_text())
        self.assertIn('<main>product:Widget:',
                      (self.site / "dist/products/widget/index.html").read_text())
        self.assertFalse((self.site / "dist/drafts/hidden/index.html").exists())
        self.assertTrue((self.site / "dist/drafts/visible/index.html").exists())
        self.assertFalse((self.site / "dist/_defaults.toml").exists())

        result = self.build('--drafts')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.site / "dist/drafts/hidden/index.html").exists())

    def test_source_discovery_exclusions_leave_assets_alone(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        (src / "internal/deep").mkdir(parents=True)
        (src / "notes").mkdir()
        (src / "assets").mkdir()
        (self.site / "krayon.toml").write_text(
            'exclude = ["internal/", "notes/private.md", "assets/"]\n')
        (src / "internal/_defaults.toml").write_text('layout = [\n')
        (src / "internal/deep/broken.md").write_text('+++\ntitle = [\n+++\nBroken')
        (src / "notes/private.md").write_text('# Private\n')
        (src / "notes/public.md").write_text('# Public\n')
        (src / "assets/logo.txt").write_text('asset\n')
        index = src / "index.html"
        index.write_text('{% for entry in collections.pages %}{{ entry.url }};{% endfor %}')

        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.site / "dist/index.html").read_text(),
                         '/;/notes/public/;')
        self.assertFalse((self.site / "dist/internal").exists())
        self.assertFalse((self.site / "dist/notes/private").exists())
        self.assertEqual((self.site / "dist/assets/logo.txt").read_text(), 'asset\n')
        result = self.build('--drafts')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.site / "dist/notes/private").exists())

        index.write_text('<a href="/notes/private/">Private</a>')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('broken local link: /notes/private/', result.stderr)
        self.assertEqual((self.site / "dist/index.html").read_text(),
                         '/;/notes/public/;')

    def test_exclude_globs_match_segments_and_directory_subtrees(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        (src / "posts/deep").mkdir(parents=True)
        (src / "notes/deep").mkdir(parents=True)
        (src / "sections/private").mkdir(parents=True)
        (src / "sections/deep/private").mkdir(parents=True)
        (self.site / "krayon.toml").write_text(
            'exclude = ["**/*.draft.md", "notes/*.md", "sections/**/private/"]\n')
        for name in [
            'root.draft.md', 'root.keep.md',
            'posts/a.draft.md', 'posts/a.keep.md',
            'posts/deep/b.draft.md', 'posts/deep/b.keep.md',
            'notes/one.md', 'notes/deep/two.md',
            'sections/deep/public.md',
        ]:
            (src / name).write_text('# Page\n')
        (src / 'sections/private/_defaults.toml').write_text('layout = [\n')
        (src / 'sections/deep/private/_defaults.toml').write_text('layout = [\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        for path in [
            'root.keep/index.html', 'posts/a.keep/index.html',
            'posts/deep/b.keep/index.html', 'notes/deep/two/index.html',
            'sections/deep/public/index.html',
        ]:
            self.assertTrue((self.site / 'dist' / path).exists(), path)
        for path in [
            'root.draft/index.html', 'posts/a.draft/index.html',
            'posts/deep/b.draft/index.html', 'notes/one/index.html',
            'sections/private', 'sections/deep/private',
        ]:
            self.assertFalse((self.site / 'dist' / path).exists(), path)

    def test_invalid_source_exclusions_preserve_output(self):
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        original = (self.site / "dist/index.html").read_text()
        config = self.site / "krayon.toml"
        for contents, message in [
            ('exclude = "notes/"\n', 'exclude must be an array'),
            ('exclude = [42]\n', 'exclude entry must be a string'),
            ('exclude = ["../outside"]\n', 'invalid exclude path'),
            ('exclude = ["/absolute"]\n', 'invalid exclude path'),
            ('exclude = ["notes/foo**bar.md"]\n', 'invalid exclude path'),
            ('exclude = ["notes/what?.md"]\n', 'invalid exclude path'),
            ('exclude = ["notes//private.md"]\n', 'invalid exclude path'),
        ]:
            config.write_text(contents)
            result = self.build()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(message, result.stderr)
            self.assertEqual((self.site / "dist/index.html").read_text(), original)

    def test_invalid_directory_defaults_preserve_output(self):
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        original = (self.site / "dist/index.html").read_text()
        defaults = self.site / "src/_defaults.toml"
        for contents, message in [
            ('layout = [\n', '_defaults.toml'),
            ('permalink = "/same/"\n', 'field cannot be a directory default: permalink'),
            ('paginate = "site.posts"\n', 'field cannot be a directory default: paginate'),
        ]:
            defaults.write_text(contents)
            result = self.build()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(message, result.stderr)
            self.assertEqual((self.site / "dist/index.html").read_text(), original)

    def test_directory_permalink_patterns_and_page_overrides(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        (src / "posts/deep").mkdir(parents=True)
        (src / "feeds").mkdir()
        (src / "_data").mkdir()
        (self.site / "krayon.toml").write_text('base_path = "/docs"\n')
        (src / "posts/_defaults.toml").write_text(
            'kind = "post"\npermalink_pattern = "/journal/{{ page.slug }}/"\n')
        (src / "posts/deep/_defaults.toml").write_text(
            'permalink_pattern = "/deep/{{ page.date }}/{{ page.slug }}/"\n')
        (src / "feeds/_defaults.toml").write_text(
            'permalink_pattern = "/rss/{{ page.slug }}.xml"\n')
        (src / "posts/first.md").write_text('# First\n\n[Second](second.md)\n')
        (src / "posts/second.md").write_text(
            '+++\nslug = "custom"\n+++\n# Second\n')
        (src / "posts/manual.md").write_text(
            '+++\npermalink = "/manual/"\n+++\n# Manual\n')
        (src / "posts/normal.md").write_text(
            '+++\npermalink_pattern = ""\n+++\n# Normal\n')
        (src / "posts/deep/child.html").write_text(
            '+++\ndate = 2026-11-20\n+++\n{{ page.kind }}:{{ page.slug }}')
        (src / "feeds/news.xml").write_text('<feed/>')
        (src / "_data/site.toml").write_text('[[items]]\nslug = "widget"\n')
        (src / "posts/product.html").write_text(
            '+++\ngenerate = "site.items"\n'
            'permalink = "/products/{{ item.slug }}/"\n+++\nGenerated')
        (src / "links.html").write_text(
            '<a href="{{ "posts/first.md" | page_url }}">First</a>')

        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('href="/docs/journal/custom/"',
                      (self.site / "dist/journal/first/index.html").read_text())
        self.assertTrue((self.site / "dist/journal/custom/index.html").exists())
        self.assertTrue((self.site / "dist/manual/index.html").exists())
        self.assertTrue((self.site / "dist/posts/normal/index.html").exists())
        self.assertEqual((self.site / "dist/deep/2026-11-20/child/index.html").read_text(),
                         'post:child')
        self.assertEqual((self.site / "dist/rss/news.xml").read_text(), '<feed/>')
        self.assertEqual((self.site / "dist/products/widget/index.html").read_text(), 'Generated')
        self.assertIn('href="/docs/journal/first/"',
                      (self.site / "dist/links/index.html").read_text())

    def test_page_aliases_create_redirects_without_collection_entries(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        src.mkdir()
        (self.site / "krayon.toml").write_text('base_path = "/docs"\n')
        (src / "new.md").write_text(
            '+++\npermalink = "/latest/"\n'
            'aliases = ["/old/", "/legacy.html"]\n+++\n# New\n')
        (src / "draft.md").write_text(
            '+++\ndraft = true\naliases = ["/draft-old/"]\n+++\n# Draft\n')
        (src / "index.html").write_text(
            '<a href="/docs/old/">Old link</a>'
            '{% for entry in collections.pages %}{{ entry.url }};{% endfor %}')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.site / "dist/index.html").read_text(),
                         '<a href="/docs/old/">Old link</a>/;/latest/;')
        for path in ("old/index.html", "legacy.html"):
            redirect = (self.site / "dist" / path).read_text()
            self.assertIn('content="0; url=/docs/latest/"', redirect)
            self.assertIn('href="/docs/latest/"', redirect)
            self.assertIn('content="noindex"', redirect)
        self.assertFalse((self.site / "dist/draft-old/index.html").exists())
        result = self.build('--drafts')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('href="/docs/draft/"',
                      (self.site / "dist/draft-old/index.html").read_text())

    def test_invalid_page_aliases_preserve_output(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        src.mkdir()
        (src / "page.md").write_text('# Page\n')
        (src / "other.md").write_text('# Other\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        original = (self.site / "dist/page/index.html").read_text()
        for contents, message in [
            ('+++\naliases = "/old/"\n+++\n# Page\n', 'aliases must be an array'),
            ('+++\naliases = [42]\n+++\n# Page\n', 'alias must be a string'),
            ('+++\naliases = ["/../old/"]\n+++\n# Page\n', 'unsafe URL'),
            ('+++\naliases = ["/other/"]\n+++\n# Page\n', 'output collision'),
            ('+++\naliases = ["/page/"]\n+++\n# Page\n', 'output collision'),
        ]:
            (src / "page.md").write_text(contents)
            result = self.build()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(message, result.stderr)
            self.assertEqual((self.site / "dist/page/index.html").read_text(), original)

        (src / "page.md").write_text('# Page\n')
        (src / "feed.xml").write_text('+++\naliases = ["/old/"]\n+++\n<feed/>')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('aliases require an HTML page', result.stderr)
        self.assertEqual((self.site / "dist/page/index.html").read_text(), original)

        (src / "feed.xml").unlink()
        (src / "_defaults.toml").write_text('aliases = ["/old/"]\n')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('field cannot be a directory default: aliases', result.stderr)
        (src / "_defaults.toml").unlink()

        (src / "archive.html").write_text(
            '+++\npaginate = "collections.pages"\npage_size = 1\n'
            'aliases = ["/old/"]\n+++\nArchive')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('aliases require an ordinary page', result.stderr)
        (src / "archive.html").unlink()
        (src / "_data").mkdir()
        (src / "_data/site.toml").write_text(
            '[[items]]\nslug = "one"\naliases = ["/old/"]\n')
        (src / "generate.html").write_text(
            '+++\ngenerate = "site.items"\n'
            'permalink = "/items/{{ item.slug }}/"\n+++\nItem')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('aliases require an ordinary page', result.stderr)

    def test_invalid_directory_permalink_patterns_preserve_output(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        src.mkdir()
        (src / "_defaults.toml").write_text('permalink_pattern = "/posts/{{ page.slug }}/"\n')
        (src / "a.md").write_text('# A\n')
        (src / "b.md").write_text('# B\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        original = (self.site / "dist/posts/a/index.html").read_text()
        for contents, message in [
            ('permalink_pattern = 7\n', 'permalink_pattern must be a string'),
            ('permalink_pattern = ""\n', 'permalink_pattern must not be empty'),
            ('permalink_pattern = "/posts/{{ item.slug }}/"\n',
             'permalink placeholders must use page.<field>'),
            ('permalink_pattern = "/posts/{{ page.missing }}/"\n',
             'missing permalink field: page.missing'),
            ('permalink_pattern = "/posts/../{{ page.slug }}/"\n', 'unsafe URL'),
            ('permalink_pattern = "/same/"\n', 'output collision'),
        ]:
            (src / "_defaults.toml").write_text(contents)
            result = self.build()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(message, result.stderr)
            self.assertEqual((self.site / "dist/posts/a/index.html").read_text(), original)

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
        self.assertIn("permalink field must be a string, integer, or date", result.stderr)

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
        self.assertIn('paginate source is missing', result.stderr)
        self.assertTrue((self.site / "dist/blog/page/2/index.html").exists())

    def test_named_page_collections_feed_templates_and_pagination(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        src.mkdir()
        (self.site / "krayon.toml").write_text(
            '[collections.posts]\n'
            'where = { field = "kind", equals = "post" }\n'
            'sort_by = "date"\n'
            'sort_order = "desc"\n'
            '[collections.chronological]\n'
            'where = { field = "kind", equals = "post" }\n'
            'sort_by = "date"\n')
        (src / "_includes").mkdir()
        (src / "_includes/nav.html").write_text(
            '{% if page.collection_navigation.posts.previous %}'
            '<a href="{{ page.collection_navigation.posts.previous.url }}">'
            '{{ page.collection_navigation.posts.previous.title }}</a>{% endif %}'
            '<b>{{ content | safe }}</b>'
            '{% if page.collection_navigation.posts.next %}'
            '<a href="{{ page.collection_navigation.posts.next.url }}">'
            '{{ page.collection_navigation.posts.next.title }}</a>{% endif %}'
            '{% if page.collection_navigation.chronological.previous %}'
            '<i>{{ page.collection_navigation.chronological.previous.title }}</i>{% endif %}'
            '{% if page.collection_navigation.chronological.next %}'
            '<i>{{ page.collection_navigation.chronological.next.title }}</i>{% endif %}')
        for name, date, draft in [
            ("old", "2024-01-01", False),
            ("new", "2025-01-01", False),
            ("draft", "2026-01-01", True),
        ]:
            (src / f"{name}.md").write_text(
                f'+++\ntitle = "{name}"\nkind = "post"\n'
                f'date = {date}\ndraft = {str(draft).lower()}\n'
                f'layout = "nav.html"\n+++\n# {name}\n')
        (src / "other.md").write_text('+++\nkind = "other"\nlayout = "nav.html"\n+++\n# Other\n')
        (src / "archive.html").write_text(
            '+++\npaginate = "collections.posts"\npage_size = 1\n'
            'kind = "post"\n+++\n'
            '{{ page.pagination.total_items }}:'
            '{% for item in page.pagination.items %}{{ item.title }}{% endfor %}')
        (src / "listing.html").write_text(
            '{% for item in collections.posts %}{{ item.title }};{% endfor %}')
        (src / "feed.json").write_text(
            '{{ collections.posts | json }}')

        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.site / "dist/listing/index.html").read_text(), 'new;old;')
        self.assertEqual((self.site / "dist/archive/index.html").read_text(), '2:new')
        self.assertEqual((self.site / "dist/archive/page/2/index.html").read_text(), '2:old')
        feed = json.loads((self.site / "dist/feed.json").read_text())
        self.assertEqual([item['title'] for item in feed], ['new', 'old'])
        self.assertIn('<a href="/old/">old</a>', (self.site / "dist/new/index.html").read_text())
        self.assertIn('<i>old</i>', (self.site / "dist/new/index.html").read_text())
        self.assertIn('<a href="/new/">new</a>', (self.site / "dist/old/index.html").read_text())
        self.assertIn('<i>new</i>', (self.site / "dist/old/index.html").read_text())
        self.assertNotIn('<a ', (self.site / "dist/other/index.html").read_text())

        result = self.build('--drafts')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.site / "dist/listing/index.html").read_text(), 'draft;new;old;')
        self.assertEqual((self.site / "dist/archive/index.html").read_text(), '3:draft')
        self.assertEqual((self.site / "dist/archive/page/3/index.html").read_text(), '3:old')
        self.assertIn('<a href="/draft/">draft</a>', (self.site / "dist/new/index.html").read_text())
        self.assertIn('<a href="/new/">new</a>', (self.site / "dist/draft/index.html").read_text())

        (self.site / "krayon.toml").write_text(
            '[collections.posts]\nwhere = { field = "kind", equals = "missing" }\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.site / "dist/listing/index.html").read_text(), '')
        self.assertEqual((self.site / "dist/archive/index.html").read_text(), '0:')
        self.assertFalse((self.site / "dist/archive/page/2/index.html").exists())

    def test_collection_navigation_front_matter_is_reserved(self):
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        original = (self.site / "dist/index.html").read_text()
        index = self.site / "src/index.md"
        index.write_text(index.read_text().replace(
            'title = "Home"', 'title = "Home"\ncollection_navigation = {}'))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('collection_navigation is a reserved page field', result.stderr)
        self.assertEqual((self.site / "dist/index.html").read_text(), original)

    def test_named_collection_rejects_invalid_definitions(self):
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        original = (self.site / "dist/index.html").read_text()
        for config, message in [
            ('[collections.pages]\n', 'invalid collection name'),
            ('[collections."bad-name"]\n', 'invalid collection name'),
            ('[collections]\nposts = true\n', 'collection must be a table'),
            ('[collections.posts]\nsort_order = "desc"\n', 'sort_order requires sort_by'),
            ('[collections.posts]\nunknown = true\n', 'unknown collection rule'),
            ('[collections.posts]\nsort_by = "missing"\n', 'sort_by:'),
        ]:
            (self.site / "krayon.toml").write_text(config)
            result = self.build()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(message, result.stderr)
            self.assertEqual((self.site / "dist/index.html").read_text(), original)

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

        sitemap.write_text(sitemap.read_text().replace("{{ site.json_title }}",
                                                      "{{ site.title }}"))
        shell = self.site / "src/_includes/xml-shell.xml"
        shell.write_text(shell.read_text().replace('</root>', '</wrong>'))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('generated XML /sitemap.xml', result.stderr)
        self.assertIn('mismatched XML closing tag', result.stderr)
        self.assertEqual((self.site / "dist/sitemap.xml").read_bytes(), previous)

    def test_generated_xml_sitemap_locations_use_local_link_checks(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        src.mkdir()
        (self.site / "krayon.toml").write_text('base_path = "/docs"\n')
        (src / "index.md").write_text("# Home\n")
        (src / "guide.md").write_text("# Part\n")
        (src / "data.xml").write_text('<root><loc>not a URL</loc></root>')
        sitemap = src / "sitemap.xml"
        sitemap.write_text(
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            '<url><loc>/docs/</loc></url>\n'
            '<url><loc>/docs/guide/?a=1&amp;b=2#part</loc></url>\n'
            '<url><loc><![CDATA[/docs/guide/]]></loc></url>\n'
            '<url><loc>https://example.org/external/</loc></url>\n'
            '</urlset>\n')
        (src / "sitemap-index.xml").write_text(
            '<s:sitemapindex xmlns:s="http://www.sitemaps.org/schemas/sitemap/0.9">'
            '<s:sitemap><s:loc>/docs/sitemap.xml</s:loc></s:sitemap>'
            '</s:sitemapindex>')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        previous = (self.site / "dist/sitemap.xml").read_bytes()

        sitemap.write_text(sitemap.read_text().replace(
            '/docs/guide/?a=1&amp;b=2#part', '\n  /docs/missing/?a=1&amp;b=2'))
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f'{sitemap}: broken local link: /docs/missing/?a=1&b=2',
                      result.stderr)
        self.assertIn('generated XML line 4, column 3', result.stderr)
        self.assertEqual((self.site / "dist/sitemap.xml").read_bytes(), previous)

        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.site / "dist/sitemap.xml").read_bytes(), previous)

        sitemap.write_text(sitemap.read_text().replace(
            '/docs/missing/?a=1&amp;b=2', '/docs/guide/#missing'))
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('broken local link: /docs/guide/#missing', result.stderr)

        sitemap.write_bytes(previous)
        index = src / "sitemap-index.xml"
        index.write_text(index.read_text().replace('/docs/sitemap.xml', '/docs/absent.xml'))
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f'{index}: broken local link: /docs/absent.xml', result.stderr)

    def test_generated_atom_and_rss_links_use_local_link_checks(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        src.mkdir()
        (self.site / "krayon.toml").write_text(
            'base_path = "/docs"\norigin = "https://example.org:8443"\n')
        (src / "index.md").write_text('# Home\n')
        (src / "article.md").write_text('# Part {#part}\n')
        (src / "data.xml").write_text('<root><link href="/docs/ignored/">data</link></root>')
        (src / "other-feed.xml").write_text(
            '<feed xmlns="urn:other"><link href="/docs/ignored/"/></feed>')
        atom = src / "atom.xml"
        atom.write_text(
            '<feed xmlns="http://www.w3.org/2005/Atom">\n'
            '<link rel="self" href="/docs/atom.xml"/>\n'
            '<entry><link href="https://example.org:8443/docs/article/?a=1&amp;b=2#part"/></entry>\n'
            '<entry><link href="article/#part"/></entry>\n'
            '<entry><link href="https://other.example/missing/"/></entry>\n'
            '</feed>\n')
        prefixed = src / "prefixed.xml"
        prefixed.write_text(
            '<a:feed xmlns:a="http://www.w3.org/2005/Atom">'
            '<a:link href="/docs/article/"/>'
            '<x:link xmlns:x="urn:custom" href="/docs/ignored/"/>'
            '</a:feed>')
        rss = src / "rss.xml"
        rss.write_text(
            '<rss version="2.0" xmlns:x="urn:custom"><channel>\n'
            '<link>https://example.org:8443/docs/</link>\n'
            '<item><link><![CDATA[/docs/article/#part]]></link></item>\n'
            '<item><link>article/#part</link></item>\n'
            '<image><link>/docs/ignored/</link></image>\n'
            '<item><x:link>/docs/ignored/</x:link></item>\n'
            '</channel></rss>')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        previous_atom = (self.site / "dist/atom.xml").read_bytes()
        previous_rss = (self.site / "dist/rss.xml").read_bytes()

        atom.write_text(atom.read_text().replace('/docs/article/?a=1&amp;b=2#part',
                                                 '/docs/missing/?a=1&amp;b=2'))
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f'{atom}: broken local link: https://example.org:8443/docs/missing/?a=1&b=2',
                      result.stderr)
        self.assertIn('generated XML line 3', result.stderr)
        self.assertEqual((self.site / "dist/atom.xml").read_bytes(), previous_atom)
        atom.write_bytes(previous_atom)

        rss.write_text(rss.read_text().replace('/docs/article/#part', '/docs/article/#absent'))
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f'{rss}: broken local link: /docs/article/#absent', result.stderr)
        self.assertEqual((self.site / "dist/rss.xml").read_bytes(), previous_rss)
        rss.write_bytes(previous_rss)

        prefixed.write_text(prefixed.read_text().replace('/docs/article/', '/docs/absent/'))
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f'{prefixed}: broken local link: /docs/absent/', result.stderr)

    def test_atom_xml_base_resolves_inherited_nested_and_link_scopes(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        (src / "articles").mkdir(parents=True)
        (src / "archive").mkdir()
        (self.site / "krayon.toml").write_text(
            'base_path = "/docs"\norigin = "https://example.org"\n')
        (src / "articles/one.md").write_text('# Intro {#intro}\n')
        (src / "archive/two.md").write_text('# Two\n')
        feed = src / "feed.xml"
        feed.write_text(
            '<feed xmlns="http://www.w3.org/2005/Atom" xml:base="/docs/articles/">\n'
            '<link href="one/"/>\n'
            '<entry xml:base="../archive/"><link href="two/"/>'
            '<link xml:base="../articles/" href="one/#intro"/></entry>\n'
            '<entry xml:base="https://example.org/docs/articles/">'
            '<link href="one/"/></entry>\n'
            '<entry xml:base=".."><link href="articles/one/"/></entry>\n'
            '<entry xml:base="https://example.org/docs/articles/one/?q=1">'
            '<link href="#intro"/></entry>\n'
            '<entry xml:base="/docs/arti&#99;les/one/">'
            '<link href="?q=2#intro"/></entry>\n'
            '<entry xml:base="//example.org/docs/articles/">'
            '<link href="one/"/></entry>\n'
            '<entry xml:base="https://elsewhere.example/">'
            '<link href="missing/"/></entry>\n'
            '</feed>\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        previous = (self.site / "dist/feed.xml").read_bytes()

        source = feed.read_text()
        feed.write_text(source.replace('<link href="one/"/>',
                                       '<link href="missing/"/>', 1))
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f'{feed}: broken local link: missing/', result.stderr)
        self.assertIn('generated XML line 2', result.stderr)
        self.assertEqual((self.site / "dist/feed.xml").read_bytes(), previous)

        feed.write_text(source.replace('xml:base="../archive/"',
                                       'xml:base="../missing/"'))
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f'{feed}: broken local link: two/', result.stderr)
        self.assertEqual((self.site / "dist/feed.xml").read_bytes(), previous)

    def test_generated_xml_is_validated_before_output_install(self):
        template = self.site / "src/feed.xml"
        template.write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                            '<?feed mode="test"?>\n'
                            '<feed xmlns:x="urn:items" note="Café &amp; tea">'
                            '<!-- entries --><x:item id="1">'
                            '<![CDATA[<raw>&text]]>&#x1F680;'
                            '</x:item></feed>')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        previous = (self.site / "dist/feed.xml").read_bytes()
        root = ET.fromstring(previous)
        self.assertEqual(root.attrib['note'], 'Café & tea')
        self.assertIn('🚀', root[0].text)

        template.write_text('<feed>é<item></feed>')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f'{template}: generated XML /feed.xml:1:14: '
                      'mismatched XML closing tag', result.stderr)
        self.assertEqual((self.site / "dist/feed.xml").read_bytes(), previous)

    def test_generated_xml_rejects_invalid_markup_and_entities(self):
        template = self.site / "src/feed.xml"
        cases = [
            ('<root>a & b</root>', 'invalid XML reference'),
            ('<root>&unknown;</root>', 'unknown XML entity'),
            ('<root a="1" a="2"/>', 'duplicate XML attribute'),
            ('<root a="<"/>', 'unescaped < in attribute value'),
            ('<root><!-- bad -- comment --></root>', '-- is not allowed'),
            ('<root/><other/>', 'multiple XML root elements'),
            ('<root>&#0;</root>', 'invalid XML character reference'),
            ('<root>]]></root>', ']]> is not allowed in XML text'),
            ('<root><![CDATA[never closed</root>', 'unterminated CDATA section'),
            ('<!DOCTYPE root><root/>', 'DTD declarations are not supported'),
            ('<?xml version="1.1"?><root/>', 'only XML 1.0 is supported'),
            ('<?XML version="1.0"?><root/>', 'XML declaration must be first'),
            ('<?xml version="1.0" standalone="yes" encoding="UTF-8"?><root/>',
             'invalid XML declaration field order'),
        ]
        for body, message in cases:
            with self.subTest(body=body):
                template.write_text(body)
                result = self.build()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)

        template.write_bytes(b'<root>\xff</root>')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('invalid UTF-8 in XML', result.stderr)

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

    def test_markdown_headings_are_available_to_layouts(self):
        (self.site / "src/target.md").write_text('# Target\n')
        (self.site / "src/_includes/toc.html").write_text(
            '<nav>{% for heading in page.headings %}'
            '<a href="#{{ heading.id }}">{{ heading.level }}:{{ heading.text }}</a>'
            '{% endfor %}</nav>{{ content | safe }}')
        (self.site / "src/toc.md").write_text(
            '+++\nlayout = "toc.html"\n+++\n'
            '# Hello *Krayon*\n'
            '## [Read me](/target/) & `tools`\n'
            '## Hello Krayon\n'
            '> ### Quoted {#quote}\n'
            '## Hello Krayon\n'
            '## !!!\n'
            '```text\n# Hidden\n```\n'
            '<h2 id="raw">Raw</h2>\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/toc/index.html").read_text()
        self.assertIn('<a href="#hello-krayon">1:Hello Krayon</a>', html)
        self.assertIn('<a href="#read-me-tools">2:Read me &amp; tools</a>', html)
        self.assertIn('<a href="#hello-krayon-2">2:Hello Krayon</a>', html)
        self.assertIn('<a href="#quote">3:Quoted</a>', html)
        self.assertIn('<a href="#hello-krayon-3">2:Hello Krayon</a>', html)
        self.assertIn('<a href="#section">2:!!!</a>', html)
        self.assertIn('<h1 id="hello-krayon">Hello <em>Krayon</em></h1>', html)
        self.assertIn('<h2 id="read-me-tools">', html)
        self.assertNotIn('Hidden</a>', html)
        self.assertNotIn('Raw</a>', html)

        page = self.site / "src/toc.md"
        page.write_text(page.read_text().replace('layout = "toc.html"',
                                                'layout = "toc.html"\nheadings = []'))
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('headings is a reserved Markdown page field', result.stderr)
        self.assertEqual((self.site / "dist/toc/index.html").read_text(), html)

    def test_setext_headings_share_ids_and_heading_metadata(self):
        (self.site / "src/target.md").write_text('# Target\n')
        (self.site / "src/_includes/setext-toc.html").write_text(
            '<nav>{% for heading in page.headings %}'
            '<a href="#{{ heading.id }}">{{ heading.level }}:{{ heading.text }}</a>'
            '{% endfor %}</nav>{{ content | safe }}')
        (self.site / "src/setext.md").write_text(
            '+++\nlayout = "setext-toc.html"\n+++\n'
            'Hello *Krayon*\n'
            '===\n\n'
            'First line\n'
            '[second line](/target/) {#custom .special}\n'
            '---\n\n'
            '# Hello Krayon\n\n'
            '> Quoted title\n'
            '> ===\n\n'
            '- List title\n'
            '  ---\n\n'
            '[Jump](#custom)\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/setext/index.html").read_text()
        self.assertIn('<h1 id="hello-krayon">Hello <em>Krayon</em></h1>', html)
        self.assertIn('<h2 id="custom" class="special">First line '
                      '<a href="/target/">second line</a></h2>', html)
        self.assertIn('<h1 id="hello-krayon-2">Hello Krayon</h1>', html)
        self.assertIn('<blockquote>\n<h1 id="quoted-title">Quoted title</h1>', html)
        self.assertIn('<li><h2 id="list-title">List title</h2>\n</li>', html)
        self.assertIn('<a href="#hello-krayon">1:Hello Krayon</a>', html)
        self.assertIn('<a href="#custom">2:First line second line</a>', html)
        self.assertIn('<a href="#hello-krayon-2">1:Hello Krayon</a>', html)
        self.assertIn('<a href="#quoted-title">1:Quoted title</a>', html)
        self.assertIn('<a href="#list-title">2:List title</a>', html)

    def test_setext_underline_precedes_thematic_break_and_keeps_source_locations(self):
        page = self.site / "src/setext.md"
        page.write_text('Title\n---\n\n---\n\nFirst\nsecond\n===\n\n'
                        'Short one\n=\n\nShort two\n  --\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/setext/index.html").read_text()
        self.assertIn('<h2 id="title">Title</h2>\n<hr>\n'
                      '<h1 id="first-second">First second</h1>', html)
        self.assertIn('<h1 id="short-one">Short one</h1>\n'
                      '<h2 id="short-two">Short two</h2>', html)

        page.write_text('First\n[Missing](/missing/)\n---\n')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('broken local link: /missing/ (line 2, column 1)', result.stderr)

        page.write_text('Title {#same}\n---\n# Other {#same}\n')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('duplicate heading ID', result.stderr)

    def test_duplicate_heading_id_is_an_error(self):
        (self.site / "src/heading.md").write_text("# One {#same}\n## Two {#same}\n")
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate heading ID", result.stderr)
        (self.site / "src/heading.md").write_text("# Same\n## Another {#same}\n")
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

    def test_same_origin_absolute_links_are_checked(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        src.mkdir()
        (self.site / "krayon.toml").write_text(
            'base_path = "/docs"\norigin = "https://example.org:8443"\n')
        (src / "index.md").write_text('# Home {#home}\n')
        (src / "guide.md").write_text('# Part {#part}\n')
        html = src / "links.html"
        html.write_text(
            '<a href="https://EXAMPLE.org:8443/docs/guide/?q=1#part">Guide</a>'
            '<a href="https://example.org:8443/docs?x=1#home">Home</a>'
            '<a href="https://example.org:8444/docs/missing/">Other port</a>'
            '<a href="https://example.org.evil/docs/missing/">Other host</a>'
            '<a href="//example.org:8443/docs/missing/">Protocol relative</a>')
        sitemap = src / "sitemap.xml"
        sitemap.write_text(
            '<urlset><url><loc>https://example.org:8443/docs/guide/</loc></url>'
            '<url><loc>https://elsewhere.example/missing/</loc></url></urlset>')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        previous = (self.site / 'dist/sitemap.xml').read_bytes()

        sitemap.write_text(sitemap.read_text().replace('/docs/guide/', '/docs/absent/'))
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f'{sitemap}: broken local link: https://example.org:8443/docs/absent/',
                      result.stderr)
        self.assertEqual((self.site / 'dist/sitemap.xml').read_bytes(), previous)

        sitemap.write_text(sitemap.read_text().replace('/docs/absent/', '//absent/'))
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('broken local link: https://example.org:8443//absent/', result.stderr)

        sitemap.write_bytes(previous)
        html.write_text(html.read_text().replace('/docs/guide/?q=1#part',
                                                '/docs/guide/#absent'))
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f'{html}: broken local link: https://EXAMPLE.org:8443/docs/guide/#absent',
                      result.stderr)

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

        sitemap = src / "sitemap.xml"
        sitemap_source = sitemap.read_text()
        previous_sitemap = (self.site / "dist/sitemap.xml").read_bytes()
        sitemap.write_text(sitemap_source.replace('/guide/?a=1&b=2', '/missing/?a=1&b=2'))
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('broken local link: https://example.org:8443/docs/missing/?a=1&b=2',
                      result.stderr)
        self.assertEqual((self.site / "dist/sitemap.xml").read_bytes(), previous_sitemap)
        sitemap.write_text(sitemap_source)

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

    def test_fenced_code_requires_matching_marker_and_sufficient_length(self):
        tick = chr(96)
        (self.site / "src/fences.md").write_text(
            f'{tick * 4}text\n'
            f'{tick * 3}\n'
            f'{tick * 4} trailing text\n'
            'content\n'
            f'{tick * 5}  \n'
            'After fence.\n\n'
            '~~~kursal\n'
            'fn answer() -> usize { 42 }\n'
            f'{tick * 3}\n'
            '~~~~\n\n'
            '  ~~~text\n'
            '  first\n'
            ' second\n'
            '   ~~~\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/fences/index.html").read_text()
        self.assertIn('<pre><code class="language-text">'
                      '```\n```` trailing text\ncontent\n</code></pre>\n'
                      '<p>After fence.</p>', html)
        self.assertIn('<pre><code class="language-kursal">'
                      '<span class="tok-keyword">fn</span> answer()', html)
        self.assertIn('42</span> }\n```\n</code></pre>', html)
        self.assertIn('<pre><code class="language-text">first\nsecond\n'
                      '</code></pre>', html)

    def test_fenced_code_in_lists_keeps_blank_lines_and_indent(self):
        tick = chr(96)
        (self.site / "src/list-fences.md").write_text(
            '- Parent\n'
            f'  {tick * 4}\n'
            f'  {tick * 3}\n'
            '\n'
            '  code\n'
            f'  {tick * 4}\n'
            '- Sibling\n'
            '- Nested parent\n'
            '  - Child\n'
            '    ~~~~\n'
            '    ~~~\n'
            '\n'
            '    nested code\n'
            '    ~~~~\n'
            '  - Nested sibling\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/list-fences/index.html").read_text()
        self.assertIn('<li>Parent<pre><code>```\n\ncode\n</code></pre>\n'
                      '</li>\n<li>Sibling</li>', html)
        self.assertIn('<li>Child<pre><code>~~~\n\nnested code\n</code></pre>\n'
                      '</li>\n<li>Nested sibling</li>', html)

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

    def test_loose_lists_and_paragraphs_inside_items(self):
        (self.site / "src/lists.md").write_text(
            '- First item\n\n'
            '- Second item\n\n'
            '  Second paragraph\n'
            '  - nested item\n\n'
            '  Third paragraph\n'
            '- Third item\n\n'
            'Outside paragraph.\n\n'
            '1. tight first\n'
            '2. tight second\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/lists/index.html").read_text()
        self.assertIn(
            '<ul>\n'
            '<li><p>First item</p>\n</li>\n'
            '<li><p>Second item</p>\n'
            '<p>Second paragraph</p>\n'
            '<ul>\n<li>nested item</li>\n</ul>\n'
            '<p>Third paragraph</p>\n</li>\n'
            '<li><p>Third item</p>\n</li>\n'
            '</ul>\n<p>Outside paragraph.</p>\n'
            '<ol>\n<li>tight first</li>\n<li>tight second</li>\n</ol>', html)

    def test_fenced_code_and_blockquotes_inside_list_items(self):
        fence = chr(96) * 3
        (self.site / "src/list-blocks.md").write_text(
            '- First\n'
            f'  {fence}kursal\n'
            '  fn answer() -> usize { 42 }\n'
            '\n'
            '  let value = answer()\n'
            f'  {fence}\n'
            '  After code\n'
            '  > Quoted *line*\n'
            '  > second line\n'
            '  After quote\n'
            '- Second\n'
            '- Parent\n'
            '  - Child\n'
            '    > Nested quote\n'
            f'    {fence}other\n'
            '    <tag>\n'
            f'    {fence}\n'
            '  - Sibling child\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/list-blocks/index.html").read_text()
        self.assertIn('<li>First<pre><code class="language-kursal">', html)
        self.assertIn('<span class="tok-keyword">fn</span> answer()', html)
        self.assertIn('\n\n<span class="tok-keyword">let</span> value = answer()\n'
                      '</code></pre>\n<p>After code</p>\n', html)
        self.assertIn('<blockquote>\n<p>Quoted <em>line</em> second line</p>\n'
                      '</blockquote>\n<p>After quote</p>\n</li>\n<li>Second</li>', html)
        self.assertIn('<li>Child<blockquote>\n<p>Nested quote</p>\n</blockquote>\n'
                      '<pre><code class="language-other">&lt;tag&gt;\n</code></pre>\n'
                      '</li>\n<li>Sibling child</li>', html)

    def test_headings_and_tables_inside_list_items(self):
        page = self.site / "src/list-sections.md"
        page.write_text(
            '# Overview\n\n'
            '- First section\n'
            '  ## Details {#item-details}\n'
            '  | Name | Value |\n'
            '  | --- | --- |\n'
            '  | alpha | one |\n'
            '  - Nested section\n'
            '    ### Details\n'
            '- Second section\n\n'
            '[Jump](#item-details)\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/list-sections/index.html").read_text()
        self.assertIn('<li>First section<h2 id="item-details">Details</h2>\n'
                      '<table>\n<thead>\n<tr>\n<th>Name</th>\n<th>Value</th>\n'
                      '</tr>\n</thead>\n<tbody>\n<tr>\n<td>alpha</td>\n'
                      '<td>one</td>\n</tr>\n</tbody>\n</table>\n'
                      '<ul>\n<li>Nested section<h3 id="details">Details</h3>', html)
        self.assertIn('<li>Second section</li>\n</ul>\n<p><a href="#item-details">Jump</a></p>', html)

        page.write_text('- Parent\n  - [Missing](/missing/)\n')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('broken local link: /missing/ (line 2, column 5)', result.stderr)

    def test_lazy_list_paragraph_continuations(self):
        page = self.site / "src/lazy-lists.md"
        page.write_text(
            '- First line\n'
            'wrapped without indentation\n'
            '- Parent\n'
            '  - Nested first line\n'
            'nested continuation\n'
            '  - Nested sibling\n'
            '- Final\n\n'
            '1. Ordered first line\n'
            '  partially indented continuation\n'
            '2. Ordered second\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/lazy-lists/index.html").read_text()
        self.assertIn('<li>First line wrapped without indentation</li>\n'
                      '<li>Parent<ul>\n'
                      '<li>Nested first line nested continuation</li>\n'
                      '<li>Nested sibling</li>\n</ul>\n</li>\n'
                      '<li>Final</li>', html)
        self.assertIn('<ol>\n<li>Ordered first line partially indented continuation</li>\n'
                      '<li>Ordered second</li>\n</ol>', html)

        page.write_text('- First line\nwrapped\n\n- Second line\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/lazy-lists/index.html").read_text()
        self.assertIn('<li><p>First line wrapped</p>\n</li>\n'
                      '<li><p>Second line</p>\n</li>', html)

    def test_lazy_list_lines_stop_at_block_boundaries(self):
        page = self.site / "src/lazy-boundaries.md"
        fence = chr(96) * 3
        page.write_text(
            '- First\n\n'
            'Outside after blank.\n\n'
            '- Second\n'
            f'  {fence}\n'
            '  code\n'
            f'  {fence}\n'
            'Outside after code.\n\n'
            '- Third\n'
            '# Outside heading\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/lazy-boundaries/index.html").read_text()
        self.assertIn('<li>First</li>\n</ul>\n<p>Outside after blank.</p>', html)
        self.assertIn('</code></pre>\n</li>\n</ul>\n<p>Outside after code.</p>', html)
        self.assertIn('<li>Third</li>\n</ul>\n<h1 id="outside-heading">Outside heading</h1>', html)

        page.write_text('- Parent\n[Missing](/missing/)\n')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('broken local link: /missing/ (line 2, column 1)', result.stderr)

    def test_ordered_lists_preserve_start_numbers(self):
        (self.site / "src/numbered-lists.md").write_text(
            '3. Third\n'
            '4. Fourth\n'
            '   10. Tenth\n'
            '   11. Eleventh\n\n'
            'Between lists.\n\n'
            '0. Zero\n\n'
            'Between again.\n\n'
            '1. First\n'
            '2. Second\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/numbered-lists/index.html").read_text()
        self.assertIn('<ol start="3">\n<li>Third</li>\n'
                      '<li>Fourth<ol start="10">\n'
                      '<li>Tenth</li>\n<li>Eleventh</li>\n</ol>', html)
        self.assertIn('<ol start="0">\n<li>Zero</li>\n</ol>', html)
        self.assertIn('<ol>\n<li>First</li>\n<li>Second</li>\n</ol>', html)

    def test_markdown_hard_breaks_in_paragraphs_lists_and_quotes(self):
        slash = chr(92)
        (self.site / "src/hard-breaks.md").write_text(
            'First  \n'
            'Second\n'
            f'Third{slash}\n'
            'Fourth\n\n'
            '[Home](/)  \n'
            'linked line\n\n'
            '- List first  \n'
            '  list second\n'
            f'- List third{slash}\n'
            'lazy fourth\n\n'
            '> Quote first  \n'
            f'> quote second{slash}\n'
            '> quote third\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/hard-breaks/index.html").read_text()
        self.assertIn('<p>First<br>\nSecond Third<br>\nFourth</p>', html)
        self.assertIn('<p><a href="/">Home</a><br>\nlinked line</p>', html)
        self.assertIn('<li>List first<br>\nlist second</li>\n'
                      '<li>List third<br>\nlazy fourth</li>', html)
        self.assertIn('<blockquote>\n<p>Quote first<br>\n'
                      'quote second<br>\nquote third</p>\n</blockquote>', html)

    def test_hard_break_markers_at_block_ends_stay_literal_or_disappear(self):
        slash = chr(92)
        fence = chr(96) * 3
        (self.site / "src/break-boundaries.md").write_text(
            'Before blank  \n\n'
            f'Before heading{slash}\n'
            '# Heading\n\n'
            f'{fence}\n'
            'code  \n'
            f'{fence}\n\n'
            f'At end{slash}\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/break-boundaries/index.html").read_text()
        self.assertIn('<p>Before blank</p>', html)
        self.assertIn(f'<p>Before heading{slash}</p>\n<h1 id="heading">Heading</h1>', html)
        self.assertIn('<pre><code>code  \n</code></pre>', html)
        self.assertIn(f'<p>At end{slash}</p>', html)
        self.assertNotIn('<br>', html)

    def test_markdown_thematic_breaks_and_list_precedence(self):
        (self.site / "src/thematic-breaks.md").write_text(
            'Before\n'
            '***\n'
            'After\n\n'
            '---\n'
            '___\n'
            ' - - - \n'
            ' **  * ** *\n\n'
            ' _\t_\t_ \n'
            '- First\n'
            '- * * *\n'
            '- Third\n\n'
            '> Quote first\n'
            '> _ _ _\n'
            '> Quote last\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/thematic-breaks/index.html").read_text()
        self.assertIn('<p>Before</p>\n<hr>\n<p>After</p>\n'
                      '<hr>\n<hr>\n<hr>\n<hr>\n<hr>', html)
        self.assertIn('<ul>\n<li>First</li>\n<li><hr>\n</li>\n'
                      '<li>Third</li>\n</ul>', html)
        self.assertIn('<blockquote>\n<p>Quote first</p>\n<hr>\n'
                      '<p>Quote last</p>\n</blockquote>', html)

    def test_non_thematic_lines_and_fenced_markers_stay_text(self):
        fence = chr(96) * 3
        (self.site / "src/not-thematic.md").write_text(
            '--\n'
            '**\n'
            '__\n'
            '*-*\n'
            '---a\n'
            '    ***\n'
            '+++\n\n'
            f'{fence}\n'
            '---\n'
            f'{fence}\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/not-thematic/index.html").read_text()
        self.assertNotIn('<hr>', html)
        self.assertIn('<pre><code>---\n</code></pre>', html)

    def test_backslash_escapes_inline_punctuation_and_heading_text(self):
        slash = chr(92)
        tick = chr(96)
        (self.site / "src/escapes.md").write_text(
            f'# {slash}*Literal{slash}* and {slash}[bracket{slash}]\n\n'
            f'{slash}*literal{slash}* {slash}[not a link](/missing/) '
            f'{slash}& {slash}< {slash}A\n\n'
            f'*one{slash}* two* **bold{slash}** text**\n\n'
            f'{tick}a{slash}*b{tick}\n\n'
            f'{slash}# Not a heading\n\n'
            f'{slash}- Not a list\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/escapes/index.html").read_text()
        self.assertIn('<h1 id="literal-and-bracket">*Literal* and [bracket]</h1>', html)
        self.assertIn('<p>*literal* [not a link](/missing/) &amp; &lt; '
                      f'{slash}A</p>', html)
        self.assertIn('<p><em>one* two</em> <strong>bold** text</strong></p>', html)
        self.assertIn(f'<p><code>a{slash}*b</code></p>', html)
        self.assertIn('<p># Not a heading</p>\n<p>- Not a list</p>', html)

    def test_underscore_emphasis_preserves_identifiers_and_heading_text(self):
        slash = chr(92)
        (self.site / "src/underscores.md").write_text(
            '# _Readable_ file_name and __bold__\n\n'
            '_emphasis_ __strong__ (__punctuation__)\n\n'
            'file_name snake_case_name a__b__c _a_b_\n\n'
            '__strong with _emphasis_ inside__\n\n'
            f'{slash}_escaped{slash}_ and _open and __open\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/underscores/index.html").read_text()
        self.assertIn('<h1 id="readable-file-name-and-bold"><em>Readable</em> '
                      'file_name and <strong>bold</strong></h1>', html)
        self.assertIn('<p><em>emphasis</em> <strong>strong</strong> '
                      '(<strong>punctuation</strong>)</p>', html)
        self.assertIn('<p>file_name snake_case_name a__b__c <em>a_b</em></p>', html)
        self.assertIn('<p><strong>strong with <em>emphasis</em> inside</strong></p>', html)
        self.assertIn('<p>_escaped_ and _open and __open</p>', html)

    def test_escaped_link_image_and_table_delimiters(self):
        slash = chr(92)
        (self.site / "src/assets/diagram.svg").write_text('<svg/>\n')
        (self.site / "src/escaped-delimiters.md").write_text(
            f'[la{slash}]bel](/) [site](https://example.org/a{slash})b)\n\n'
            f'![A{slash}]B](/assets/diagram.svg "Diagram {slash}" details")\n\n'
            f'| A{slash}|B | C |\n'
            '| --- | --- |\n'
            '| one | two |\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/escaped-delimiters/index.html").read_text()
        self.assertIn('<a href="/">la]bel</a>', html)
        self.assertIn('<a href="https://example.org/a)b">site</a>', html)
        self.assertIn('<img src="/assets/diagram.svg" alt="A]B" '
                      'title="Diagram &quot; details">', html)
        self.assertIn('<th>A|B</th>\n<th>C</th>', html)

    def test_markdown_pipe_tables_without_outer_pipes_and_with_alignment(self):
        (self.site / "src/tables.md").write_text(
            'Before table.\n'
            'Name | Score | Note\n'
            ':--- | ---: | :---:\n'
            'Ada | 10 | `a|b`\n'
            'Bob | 7\n'
            'Eve | 9 | yes | ignored\n\n'
            'After table.\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/tables/index.html").read_text()
        self.assertIn('<p>Before table.</p>\n<table>', html)
        self.assertIn('<th align="left">Name</th>\n'
                      '<th align="right">Score</th>\n'
                      '<th align="center">Note</th>', html)
        self.assertIn('<td align="left">Ada</td>\n'
                      '<td align="right">10</td>\n'
                      '<td align="center"><code>a|b</code></td>', html)
        self.assertIn('<td align="center"></td>', html)
        self.assertNotIn('ignored', html)
        self.assertIn('</table>\n<p>After table.</p>', html)

    def test_markdown_pipe_tables_validate_delimiters_and_code_spans(self):
        slash = chr(92)
        (self.site / "src/table-validation.md").write_text(
            f'| A{slash}|B | `x|y` |\n'
            '| --- | --- |\n'
            f'| one{slash}|two | ``a|`b`` |\n\n'
            'Name | Value\n'
            '--- | nope\n\n'
            'One | Two\n'
            '--- | --- | ---\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/table-validation/index.html").read_text()
        self.assertEqual(html.count('<table>'), 1)
        self.assertIn('<th>A|B</th>\n<th><code>x|y</code></th>', html)
        self.assertIn('<td>one|two</td>\n<td><code>a|`b</code></td>', html)
        self.assertIn('Name | Value', html)
        self.assertIn('One | Two', html)

    def test_markdown_indented_code_blocks_preserve_content_and_boundaries(self):
        (self.site / "src/indented-code.md").write_text(
            'Before.\n'
            '    still paragraph\n\n'
            '    <tag> & value  \n'
            '      extra indent\n'
            '\n'
            '    after blank\n'
            '\n'
            'After.\n\n'
            '    final line\n'
            '\n'
            '    A | B\n'
            '    --- | ---\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/indented-code/index.html").read_text()
        self.assertIn('<p>Before.     still paragraph</p>', html)
        self.assertIn('<pre><code>&lt;tag&gt; &amp; value  \n'
                      '  extra indent\n\nafter blank\n</code></pre>', html)
        self.assertIn('</code></pre>\n<p>After.</p>\n'
                      '<pre><code>final line\n\nA | B\n--- | ---\n</code></pre>', html)
        self.assertEqual(html.count('<pre><code>'), 2)

    def test_markdown_indented_code_blocks_in_lists_and_quotes(self):
        (self.site / "src/nested-indented-code.md").write_text(
            '- Item\n\n'
            '      let x = 1\n'
            '      <value>\n'
            '- Next\n\n'
            '> Quote\n'
            '>\n'
            '>     <quoted>\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/nested-indented-code/index.html").read_text()
        self.assertIn('<li><p>Item</p>\n<pre><code>let x = 1\n'
                      '&lt;value&gt;\n</code></pre>\n</li>', html)
        self.assertIn('<li><p>Next</p>\n</li>', html)
        self.assertIn('<blockquote>\n<p>Quote</p>\n'
                      '<pre><code>&lt;quoted&gt;\n</code></pre>\n</blockquote>', html)

    def test_inline_code_spans_match_backtick_run_lengths(self):
        tick = chr(96)
        (self.site / "src/code-spans.md").write_text(
            f'{tick}simple{tick} {tick * 2} code {tick} inside {tick * 2} '
            f'{tick * 3}two {tick * 2} inside{tick * 3}\n\n'
            f'{tick}<a&b>{tick} {tick} {tick} {tick * 2}  {tick * 2}\n\n'
            f'{tick * 2}unmatched{tick}\n\n'
            f'[Label {tick * 2}a{tick}b{tick * 2}](/)\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/code-spans/index.html").read_text()
        self.assertIn('<code>simple</code> <code>code ` inside</code> '
                      '<code>two `` inside</code>', html)
        self.assertIn('<code>&lt;a&amp;b&gt;</code> <code> </code> '
                      '<code>  </code>', html)
        self.assertIn('<p>``unmatched`</p>', html)
        self.assertIn('<a href="/">Label <code>a`b</code></a>', html)

    def test_inline_code_spans_keep_heading_text_and_escapes(self):
        tick = chr(96)
        slash = chr(92)
        (self.site / "src/_includes/code-toc.html").write_text(
            '{% for heading in page.headings %}{{ heading.text }}|{{ heading.id }}{% endfor %}'
            '{{ content | safe }}')
        (self.site / "src/code-heading.md").write_text(
            '+++\nlayout = "code-toc.html"\n+++\n'
            f'# Show {tick * 2}a{tick}b{tick * 2} and {tick}*x*{tick}\n\n'
            f'{slash}{tick}literal{slash}{tick} '
            f'{tick}a{slash}*b{tick}\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/code-heading/index.html").read_text()
        self.assertIn('Show a`b and *x*|show-ab-and-x', html)
        self.assertIn('<h1 id="show-ab-and-x">Show <code>a`b</code> '
                      'and <code>*x*</code></h1>', html)
        self.assertIn(f'<p>{tick}literal{tick} <code>a{slash}*b</code></p>', html)

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

    def test_markdown_source_links_use_generated_urls(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        (src / "posts").mkdir(parents=True)
        (src / "guide").mkdir()
        (self.site / "krayon.toml").write_text('base_path = "/docs"\n')
        (src / "guide/index.md").write_text(
            '+++\npermalink = "/manual/"\n+++\n# Manual\n## Section\n')
        (src / "other.md").write_text(
            '+++\npermalink = "/outside.html"\n+++\n# Outside\n')
        post = src / "posts/first.md"
        post.write_text(
            '# First\n\n'
            '[Relative](../guide/index.md#section) '
            '[Root](/guide/index.md?view=all#section) '
            '[Other](/other.md) '
            '[Self](first.md#first) '
            '[External](https://example.org/file.md)\n\n'
            '<!-- more -->\n\nRest.\n')
        (src / "archive.html").write_text(
            '{% for entry in collections.pages %}'
            '{% if entry.excerpt %}{{ entry.excerpt | safe }}{% endif %}'
            '{% endfor %}')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/posts/first/index.html").read_text()
        excerpt = (self.site / "dist/archive/index.html").read_text()
        for rendered in (html, excerpt):
            self.assertIn('href="/docs/manual/#section"', rendered)
            self.assertIn('href="/docs/manual/?view=all#section"', rendered)
            self.assertIn('href="/docs/outside.html"', rendered)
            self.assertIn('href="/docs/posts/first/#first"', rendered)
            self.assertIn('href="https://example.org/file.md"', rendered)

        post.write_text(post.read_text() + '\n[Missing](missing.md)\n')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('broken local link', result.stderr)
        self.assertEqual((self.site / "dist/posts/first/index.html").read_text(), html)

    def test_page_url_filter_uses_ordinary_source_paths(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        (src / "guide").mkdir(parents=True)
        (src / "_includes").mkdir()
        (self.site / "krayon.toml").write_text('base_path = "/docs"\n')
        (src / "guide/index.md").write_text(
            '+++\npermalink = "/manual/"\n+++\n# Manual\n## Setup\n')
        (src / "about.html").write_text(
            '+++\npermalink = "/about-us/"\n+++\n<h1>About</h1>')
        (src / "feed.xml").write_text(
            '+++\npermalink = "/site-feed.xml"\n+++\n<feed/>')
        (src / "data.json").write_text(
            '+++\npermalink = "/catalog.json"\n+++\n{}')
        (src / "robots.txt").write_text('User-agent: *\n')
        (src / "_includes/nav.html").write_text(
            '<nav><a href="{{ "guide/index.md#setup" | page_url }}">Guide</a></nav>'
            '{{ content | safe }}')
        links = src / "links.html"
        links.write_text(
            '+++\nlayout = "nav.html"\ntarget = "/guide/index.md?view=all#setup"\n+++\n'
            '<a href="{{ page.target | page_url }}">Dynamic</a>'
            '<a href="{{ "./guide/index.md" | page_url }}">Local</a>'
            '<a href="{{ "about.html" | page_url }}">About</a>'
            '<a href="{{ "/feed.xml" | page_url }}">Feed</a>'
            '<a href="{{ "data.json" | page_url }}">Data</a>'
            '<a href="{{ "robots.txt" | page_url }}">Robots</a>')
        (src / "links.json").write_text(
            '{"url":{{ "guide/index.md#setup" | page_url | json }}}')
        (src / "links.xml").write_text(
            '<root><loc>{{ "guide/index.md" | page_url }}</loc></root>')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.site / "dist/links/index.html").read_text()
        self.assertIn('href="/docs/manual/#setup"', html)
        self.assertIn('href="/docs/manual/?view=all#setup"', html)
        self.assertIn('href="/docs/manual/"', html)
        self.assertIn('href="/docs/about-us/"', html)
        self.assertIn('href="/docs/site-feed.xml"', html)
        self.assertIn('href="/docs/catalog.json"', html)
        self.assertIn('href="/docs/robots.txt"', html)
        self.assertEqual(json.loads((self.site / "dist/links.json").read_text()),
                         {"url": "/docs/manual/#setup"})
        self.assertIn('<loc>/docs/manual/</loc>', (self.site / "dist/links.xml").read_text())

        (src / "_data").mkdir()
        (src / "_data/site.toml").write_text('[[items]]\nslug = "one"\n')
        (src / "generated.html").write_text(
            '+++\ngenerate = "site.items"\n'
            'permalink = "/items/{{ item.slug }}/"\n+++\nGenerated')
        links.write_text('{{ "generated.html" | page_url }}')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('page_url', result.stderr)
        self.assertEqual((self.site / "dist/links/index.html").read_text(), html)

        links.write_text('{{ "missing.md" | page_url }}')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('links.html:1:1:', result.stderr)
        self.assertIn('page_url', result.stderr)
        self.assertEqual((self.site / "dist/links/index.html").read_text(), html)

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

    def test_duplicate_generated_html_ids_report_every_repeat(self):
        self.assertEqual(self.build().returncode, 0)
        previous = (self.site / "dist/index.html").read_bytes()
        page = self.site / "src/duplicate.html"
        page.write_text('é <div id="a&amp;b"></div>\n'
                        "<span ID='a&b'></span>\n"
                        '<a id="a&b" href="/missing/">Broken</a>\n')
        for command in (self.check, self.build):
            result = command()
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stderr.count("duplicate HTML ID: a&b"), 2)
            self.assertIn("generated HTML /duplicate/ line 2, column 11; "
                          "first at line 1, column 12", result.stderr)
            self.assertIn("generated HTML /duplicate/ line 3", result.stderr)
            self.assertIn("broken local link: /missing/", result.stderr)
            self.assertEqual((self.site / "dist/index.html").read_bytes(), previous)
            self.assertEqual(list(self.site.glob("dist.krayon-*")), [])

        page.write_text('<div id="shared"></div><div id="Shared"></div>')
        (self.site / "src/other.html").write_text('<div id="shared"></div>')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_layout_and_markdown_raw_html_ids_collide_with_heading(self):
        home = self.site / "src/index.md"
        original_home = home.read_text()
        layout = self.site / "src/_includes/base.html"
        original_layout = layout.read_text()
        layout.write_text(original_layout.replace("<main>", '<main><div id="welcome"></div>', 1))
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{home}: duplicate HTML ID: welcome "
                      "(source line 5, column 1; first at generated HTML / line", result.stderr)

        layout.write_text(original_layout)
        home.write_text(original_home + '\n<div id="welcome"></div>\n')
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{home}: duplicate HTML ID: welcome "
                      "(generated HTML / line", result.stderr)
        self.assertIn("first at source line 5, column 1", result.stderr)

        home.write_text(original_home)
        explicit = self.site / "src/explicit.md"
        explicit.write_text('+++\ntitle = "Explicit"\nlayout = "base.html"\n+++\n'
                            '## Heading {#shared}\n<div id="shared"></div>\n')
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{explicit}: duplicate HTML ID: shared ", result.stderr)
        self.assertIn("first at source line 5, column 1", result.stderr)

        explicit.unlink()
        layout.write_text(original_layout.replace("<main>", '<main><div id="nested"></div>', 1))
        quoted = self.site / "src/quoted.md"
        quoted.write_text('+++\ntitle = "Quoted"\nlayout = "base.html"\n+++\n'
                          '> > ## Nested\n')
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{quoted}: duplicate HTML ID: nested "
                      "(source line 5, column 5; first at generated HTML /quoted/ line", result.stderr)

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

    def test_video_posters_and_object_data_are_checked(self):
        assets = self.site / "src/assets"
        (assets / "poster.jpg").write_bytes(b"poster")
        (assets / "report.pdf").write_bytes(b"report")
        page = self.site / "src/media.html"
        page.write_text('<video POSTER="../assets/poster.jpg?x=1&amp;y=2"></video>\n'
                        '<object DATA="/assets/report.pdf#page=1"></object>\n'
                        '<object data="data:application/pdf;base64,QQ=="></object>\n'
                        '<div poster="/missing-unrelated.jpg" '
                        'data="/missing-unrelated.pdf"></div>\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        previous = (self.site / "dist/media/index.html").read_bytes()

        page.write_text('<VIDEO POSTER="../assets/missing.jpg"></VIDEO>\n'
                        '<OBJECT DATA="/assets/missing.pdf"></OBJECT>\n')
        for command in (self.check, self.build):
            result = command()
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stderr.count("broken local link:"), 2)
            self.assertIn(f"{page}: broken local link: ../assets/missing.jpg "
                          "(generated HTML line 1, column 16)", result.stderr)
            self.assertIn(f"{page}: broken local link: /assets/missing.pdf "
                          "(generated HTML line 2, column 15)", result.stderr)
            self.assertEqual((self.site / "dist/media/index.html").read_bytes(), previous)
            self.assertEqual(list(self.site.glob("dist.krayon-*")), [])

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

    def test_html_base_href_resolves_relative_links_and_uses_first_base(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        (src / "guides").mkdir(parents=True)
        (src / "assets").mkdir()
        (self.site / "krayon.toml").write_text(
            'base_path = "/docs"\norigin = "https://example.org"\n')
        (src / "guides/target.md").write_text('# Part {#part}\n')
        (src / "assets/pic.png").write_bytes(b'picture')
        page = src / "page.html"
        page.write_text(
            '<a href="target/#part">Before base</a>\n'
            '<base href="/docs/guides/">\n'
            '<base href="/docs/ignored/">\n'
            '<img srcset="../assets/pic.png 1x">\n'
            '<div style="background:url(../assets/pic.png)"></div>\n'
            '<style>.picture{background:url(../assets/pic.png)}</style>\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        previous = (self.site / "dist/page/index.html").read_bytes()

        source = page.read_text()
        page.write_text(source.replace('target/#part', 'missing/#part'))
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f'{page}: broken local link: missing/#part', result.stderr)
        self.assertEqual((self.site / "dist/page/index.html").read_bytes(), previous)

        page.write_text(source.replace('/docs/guides/', '/docs/absent/', 1))
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f'{page}: broken local link: target/#part', result.stderr)

        page.write_text(source.replace('/docs/guides/', '../guides/', 1))
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

        (src / "guides/index.md").write_text('# Base {#base}\n')
        page.write_text('<base href="https://EXAMPLE.org/docs/guides/?q=1">'
                        '<a href="#base">Base fragment</a>')
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

        page.write_text(page.read_text().replace('#base', '#absent'))
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f'{page}: broken local link: #absent', result.stderr)

        page.write_text('<base href="https://elsewhere.example/">'
                        '<a href="missing/">External</a>'
                        '<a href="/docs/missing/">External root</a>')
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_build_and_check_report_all_broken_links_without_replacing_output(self):
        shutil.rmtree(self.site / "src")
        src = self.site / "src"
        (src / "assets").mkdir(parents=True)
        (self.site / "krayon.toml").write_text(
            'base_path = "/docs"\norigin = "https://example.org"\n')
        (src / "guide.md").write_text('# Part {#part}\n')
        page = src / "links.html"
        page.write_text('<a href="/docs/guide/#part">Guide</a>')
        sheet = src / "assets/site.css"
        sheet.write_text('.x { color: red }')
        sitemap = src / "sitemap.xml"
        sitemap.write_text('<urlset><url><loc>/docs/guide/</loc></url></urlset>')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        previous_page = (self.site / "dist/links/index.html").read_bytes()
        previous_sheet = (self.site / "dist/assets/site.css").read_bytes()
        previous_sitemap = (self.site / "dist/sitemap.xml").read_bytes()

        page.write_text(
            '<a href="/docs/missing-one/">One</a>\n'
            '<a href="https://example.org/docs/guide/#missing">Fragment</a>\n'
            '<img srcset="/docs/assets/missing-a.png 1x, '
            '/docs/assets/missing-b.png 2x">')
        sheet.write_text('.x { background: url(/docs/assets/missing-c.png) }')
        sitemap.write_text('<urlset><url><loc>/docs/missing-xml/</loc></url></urlset>')
        for command in (self.check, self.build):
            result = command()
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stderr.count('broken local link:'), 6)
            for missing in ('/docs/missing-one/', 'https://example.org/docs/guide/#missing',
                            '/docs/assets/missing-a.png', '/docs/assets/missing-b.png',
                            '/docs/assets/missing-c.png', '/docs/missing-xml/'):
                self.assertIn(f'broken local link: {missing}', result.stderr)
            self.assertEqual((self.site / "dist/links/index.html").read_bytes(), previous_page)
            self.assertEqual((self.site / "dist/assets/site.css").read_bytes(), previous_sheet)
            self.assertEqual((self.site / "dist/sitemap.xml").read_bytes(), previous_sitemap)
            self.assertEqual(list(self.site.glob("dist.krayon-*")), [])

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

    def test_markdown_links_report_source_locations_and_leave_no_markers(self):
        page = self.site / "src/located.md"
        page.write_text('+++\ntitle = "Located"\nlayout = "base.html"\n+++\n'
                        '# Title\n\n[Home](/)\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('krayon-md-source',
                         (self.site / 'dist/located/index.html').read_text())

        page.write_text('+++\ntitle = "Located"\nlayout = "base.html"\n+++\n'
                        '# Title\n\né [Missing](/missing/)\n\n'
                        '> [Quoted](/quoted/)\n> > [Nested](/nested/)\n\n'
                        '- [Listed](/listed/)\n\n'
                        '| Link |\n| --- |\n| [Table](/table/) |\n\n'
                        '![Missing image](/assets/missing.png)\n')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        for target, line, column in (('/missing/', 7, 3), ('/quoted/', 9, 3),
                                     ('/nested/', 10, 5), ('/listed/', 12, 3),
                                     ('/table/', 16, 3), ('/assets/missing.png', 18, 1)):
            self.assertIn(f'{page}: broken local link: {target} '
                          f'(line {line}, column {column})', result.stderr)

        layout = self.site / 'src/_includes/base.html'
        layout.write_text(layout.read_text() + '<a href="/layout-missing/">Missing</a>')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f'{page}: broken local link: /layout-missing/ '
                      '(generated HTML line ', result.stderr)

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
                         '<h1 id="first">First</h1>\n<p>A page.</p>\n')

    def test_false_condition_uses_else_branch(self):
        data = self.site / "src/_data/site.toml"
        data.write_text(data.read_text().replace('subtitle = "A small Krayon site"\n', ""))
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("A site", (self.site / "dist/index.html").read_text())

    def test_if_checks_nonempty_arrays_and_tables(self):
        page = self.site / "src/conditions.html"
        page.write_text(
            '+++\n'
            'empty_array = []\nitems = [1]\n'
            'empty_table = {}\nperson = { name = "Ada" }\n'
            'disabled = false\ncount = 0\n+++\n'
            '{% if page.empty_array %}bad{% else %}empty-array;{% endif %}'
            '{% if page.items %}items;{% else %}bad{% endif %}'
            '{% if page.empty_table %}bad{% else %}empty-table;{% endif %}'
            '{% if page.person %}person;{% else %}bad{% endif %}'
            '{% if page.disabled %}bad{% else %}disabled;{% endif %}'
            '{% if page.count %}bad{% else %}zero;{% endif %}'
            '{% if page.missing %}bad{% else %}missing;{% endif %}'
            '{% if page.person.name == "Ada" %}equals;{% else %}bad{% endif %}'
            '{% for entry in collections.pages %}'
            '{% if entry %}{% if entry.url == "/conditions/" %}record;{% endif %}{% endif %}'
            '{% endfor %}')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.site / "dist/conditions/index.html").read_text(),
                         'empty-array;items;empty-table;person;disabled;zero;missing;equals;record;')

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
