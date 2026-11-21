"""Build the written guides and Krayon library API as one validated site."""

import argparse
import html
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib
from urllib.parse import urljoin, urlsplit


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ENTRY = re.compile(r'<li><a class="package-link" href="([^"]+)">.*?</li>\n?', re.S)
LINK = re.compile(r'<a\b[^>]*\bhref="([^"]*)"[^>]*>(.*?)</a>', re.S)
URL_FIELD = re.compile(r'(?m)^(parent|permalink|url) = "(/[^"]*)"$')
ENTRY = re.compile(r'(?ms)^(\[\[(?:nav_items|tree)\]\]\n)(.*?)(?=^\[\[|\Z)')
ENTRY_URL = re.compile(r'(?m)^url = "([^"]+)"$')
LAYOUTS = {"doc.html": "api-doc.html", "index.html": "api-index.html",
           "source.html": "api-source.html"}


def page_route(source, api_root):
    relative = source.relative_to(api_root)
    if relative.name == "index.md":
        parent = relative.parent.as_posix()
        return "/api/" if parent == "." else f"/api/{parent}/"
    return "/api/" + relative.with_suffix(".html").as_posix()


def prepare_api_source(api_root, packages):
    """Keep Krayon packages, rewrite their routes, and unlink removed dependencies."""
    generated = {path.name for path in api_root.iterdir()
                 if path.is_dir() and path.name != "src"}
    missing = packages - generated
    if missing:
        raise RuntimeError(f"Kursal did not generate Krayon packages: {sorted(missing)}")
    excluded = generated - packages

    index = api_root / "index.md"
    index.write_text(PACKAGE_ENTRY.sub(
        lambda match: match.group() if match.group(1).rstrip("/") in packages else "",
        index.read_text()))

    for source in api_root.rglob("*.md"):
        relative = source.relative_to(api_root)
        if relative.parts[0] in excluded:
            continue
        if relative.parts[0] == "src" and relative.parts[1] in excluded:
            continue

        content = source.read_text()
        if not content.startswith("+++\n"):
            raise RuntimeError(f"Kursal page has no front matter: {source}")
        front, separator, body = content[4:].partition("\n+++\n")
        if not separator:
            raise RuntimeError(f"Kursal page has unclosed front matter: {source}")
        route = page_route(source, api_root)
        front = re.sub(r'(?m)^layout = "([^"]+)"$',
                       lambda match: f'layout = "{LAYOUTS[match.group(1)]}"', front)
        front = URL_FIELD.sub(
            lambda match: f'{match.group(1)} = "/api{match.group(2)}"', front)
        permalink = re.search(r'(?m)^permalink = "([^"]+)"$', front)
        if permalink:
            route = permalink.group(1)

        def mark_current(match):
            url = ENTRY_URL.search(match.group(2))
            if url and url.group(1) == route:
                return match.group().rstrip("\n") + "\nis_page = true\n"
            return match.group()

        front = ENTRY.sub(mark_current, front)

        def unlink_dependency(match):
            target = urlsplit(urljoin("https://krayon.invalid" + route,
                                       html.unescape(match.group(1))))
            if target.netloc != "krayon.invalid" or not target.path.startswith("/api/"):
                return match.group()
            parts = target.path[len("/api/"):].split("/")
            package = parts[1] if parts[0] == "src" and len(parts) > 1 else parts[0]
            return match.group(2) if package in excluded else match.group()

        source.write_text("+++\n" + front + "\n+++\n" + LINK.sub(unlink_dependency, body))

    search_index = api_root / "search-index.json"
    entries = json.loads(search_index.read_text())
    entries = [entry for entry in entries
               if entry["u"].lstrip("/").split("/")[0] in packages]
    search_index.write_text(json.dumps(entries, ensure_ascii=False,
                                       separators=(",", ":")) + "\n")

    for package in excluded:
        shutil.rmtree(api_root / package)
        source_dir = api_root / "src" / package
        if source_dir.exists():
            shutil.rmtree(source_dir)


def add_api_layouts(site, theme_root):
    theme = theme_root / "src"
    layouts = site / "src/_includes"
    for source in (theme / "_includes").glob("*.html"):
        shutil.copy2(source, layouts / source.name)
    shutil.copytree(theme / "assets", site / "src/assets/api")


def publish(staged, output):
    """Prepare the complete output before replacing the published directory."""
    with tempfile.TemporaryDirectory(prefix=".krayon-docs-", dir=output.parent) as temporary:
        temporary = Path(temporary)
        ready = temporary / "ready"
        shutil.copytree(staged, ready)
        previous = temporary / "previous"
        if output.exists():
            output.rename(previous)
        try:
            ready.rename(output)
        except Exception:
            if previous.exists():
                previous.rename(output)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, default=ROOT / "docs",
                        help="documentation site root (default: docs)")
    parser.add_argument("--krayon", type=Path, default=ROOT / "bin/krayon",
                        help="Krayon executable")
    parser.add_argument("--kursal", type=Path,
                        default=ROOT.parent / "kursal/bin/kursal",
                        help="Kursal compiler")
    args = parser.parse_args()

    site = args.site.resolve()
    with (site / "krayon.toml").open("rb") as config_file:
        config = tomllib.load(config_file)
    output_name = config.get("output", "dist")
    output = site / output_name
    packages = {path.parent.name for path in (ROOT / "lib").glob("*/kur.toml")}

    with tempfile.TemporaryDirectory(prefix="krayon-docs-") as temporary:
        staged_site = Path(temporary) / "site"

        def ignore(directory, names):
            if Path(directory) == site:
                return [name for name in (output_name, "api-theme") if name in names]
            return []

        shutil.copytree(site, staged_site, ignore=ignore)
        placeholder = staged_site / "src/api.md"
        placeholder.unlink(missing_ok=True)
        api_root = staged_site / "src/api"
        subprocess.run([args.kursal.resolve(), "doc", ROOT / "lib/site",
                        "-o", api_root], check=True)
        prepare_api_source(api_root, packages)
        add_api_layouts(staged_site, site / "api-theme")
        subprocess.run([args.krayon.resolve(), "build", staged_site], check=True)
        publish(staged_site / output_name, output)

    print(f"Documentation written to {output}")


if __name__ == "__main__":
    main()
