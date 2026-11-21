+++
title = "Development"
layout = "base.html"
+++
# Development

- `krayon/` — thin command-line program
- `lib/site/` — configuration, discovery, routing, rendering, and output
- `lib/html/` — front matter and templates
- `lib/markdown/` — Markdown rendering
- `lib/links/` — local link validation
- `lib/records/` — record filtering and sorting shared by queries and pagination
- `lib/json/` — generated JSON validation
- `lib/xml/` — generated XML validation
- `lib/url/` — deployment path prefixes
- `lib/sha256/` — content digests for fingerprinted assets
- `lib/highlight/` — fenced code highlighting
- `lib/shim/` — stdlib overlay with path helpers and recursive directory creation
- `examples/hello-site/` — independent site example
- `examples/blog-site/` — blog example with feeds and pagination
- `docs/` — documentation site built with Krayon
- `docs/api-theme/` — layouts and assets for the generated library API reference
- `scripts/build_docs.py` — filters generated API source and builds the complete docs site

Kursal programs can call `site::build(&cx, root)` directly. It takes a site
root as a byte span and returns `Result[(), Buffer!]`; the error buffer is a
message suitable for printing. The CLI is a small wrapper around that API.
`site::build_with_drafts(&cx, root, true)` includes drafts for previews.

Run `python3 tests/integration.py` for the end-to-end checks. They build
Krayon with the adjacent Kursal compiler and use temporary site copies.
The integration suite also builds the example sites and documentation site.
Run `python3 scripts/build_docs.py` to generate the API reference from the
Krayon library packages and place it under `docs/dist/api` beside the guides.
The focused shim checks build with `../kursal/bin/kursal build tests/shim -o bin/shim-test`
and run with a temporary directory containing a file and a directory symlink.
CI bootstraps Kursal from its `main` branch, builds Krayon, and runs these checks.
If the Kursal repository is private, set the `KURSAL_REPO_TOKEN` Actions secret
to a token with read access to that repository.
