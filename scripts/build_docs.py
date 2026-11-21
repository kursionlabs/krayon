"""Build the written Krayon guides and generated Kursal API reference together."""

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


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f"Krayon's API theme changed: expected {old!r}")
    return text.replace(old, new)


def keep_library_docs(output, api_base_path, packages):
    """Remove dependency documentation from Kursal's full package graph."""
    generated_packages = {path.name for path in output.iterdir()
                          if path.is_dir() and path.name not in {"assets", "src"}}
    missing = packages - generated_packages
    if missing:
        raise RuntimeError(f"Kursal did not generate Krayon packages: {sorted(missing)}")
    excluded = generated_packages - packages

    index = output / "index.html"
    landing = index.read_text()
    landing = PACKAGE_ENTRY.sub(
        lambda match: match.group() if match.group(1).rstrip("/") in packages else "",
        landing)
    index.write_text(landing)

    api_root = f"{api_base_path}/"

    def excluded_link(page, href):
        page_url = api_root + page.relative_to(output).as_posix()
        target = urlsplit(urljoin("https://krayon.invalid" + page_url,
                                   html.unescape(href)))
        if target.netloc != "krayon.invalid" or not target.path.startswith(api_root):
            return False
        parts = target.path[len(api_root):].split("/")
        package = parts[1] if parts[0] == "src" and len(parts) > 1 else parts[0]
        return package in excluded

    for page in output.rglob("*.html"):
        content = page.read_text()
        page_url = api_root + page.relative_to(output).as_posix()
        if page_url.endswith("/index.html"):
            page_url = page_url[:-len("index.html")]

        def rewrite_link(match):
            href = match.group(1)
            if excluded_link(page, href):
                return match.group(2)
            target = urlsplit(urljoin("https://krayon.invalid" + page_url,
                                       html.unescape(href)))
            if target.netloc != "krayon.invalid" or target.path != page_url or target.fragment:
                return match.group()
            anchor = match.group()
            if 'class="nav-kind-' in anchor:
                return anchor.replace(">", ' aria-current="page">', 1)
            if 'class="tree-current"' in anchor:
                return anchor.replace('aria-current="location"', 'aria-current="page"', 1)
            return anchor

        content = LINK.sub(rewrite_link, content)
        page.write_text(content)

    search_index = output / "search-index.json"
    entries = json.loads(search_index.read_text())
    entries = [entry for entry in entries
               if entry["u"].lstrip("/").split("/")[0] in packages]
    search_index.write_text(json.dumps(entries, ensure_ascii=False,
                                       separators=(",", ":")) + "\n")

    for package in excluded:
        shutil.rmtree(output / package)
        source = output / "src" / package
        if source.exists():
            shutil.rmtree(source)


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
    base_path = config.get("base_path", "").rstrip("/")
    api_base_path = f"{base_path}/api"
    output = site / config.get("output", "dist")

    with tempfile.TemporaryDirectory(prefix="krayon-api-") as temporary:
        generated = Path(temporary) / "site"
        packages = {path.parent.name for path in (ROOT / "lib").glob("*/kur.toml")}
        subprocess.run([args.kursal.resolve(), "doc", ROOT / "lib/site",
                        "-o", generated / "src"], check=True)
        shutil.copytree(ROOT / "docs/api-site", generated, dirs_exist_ok=True)
        shutil.copy2(site / "src/assets/css/docs.css",
                     generated / "src/assets/docs.css")
        generated_config = generated / "krayon.toml"
        generated_config.write_text(generated_config.read_text()
                                    + f'base_path = "{api_base_path}"\n')

        subprocess.run([args.krayon.resolve(), "build", generated], check=True)
        subprocess.run([args.krayon.resolve(), "build", site], check=True)

        api_output = output / "api"
        staged_api = output / ".api-generated"
        shutil.copytree(generated / "dist", staged_api)
        keep_library_docs(staged_api, api_base_path, packages)
        guide_url = f"{base_path}/" if base_path else "/"
        for page in staged_api.rglob("*.html"):
            page.write_text(replace_once(
                page.read_text(), '<div class="header-actions">',
                f'<div class="header-actions"><a class="guide-link" href="{guide_url}">Guides</a>'))
        shutil.rmtree(api_output)
        staged_api.rename(api_output)

    print(f"Documentation written to {output}")


if __name__ == "__main__":
    main()
