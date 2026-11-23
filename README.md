# Krayon

Krayon is a static site generator written in Kursal. It builds Markdown,
HTML, XML, JSON, and text pages with layouts, site data, collections, and
assets for any static host.

## Build Krayon

Keep `../kursal` and `../kable` beside this checkout and install the libuv and
llhttp development libraries. Bootstrap Kursal first, and rerun its bootstrap
after updating Kursal so `bin/kursal` matches its source. Then run:

```sh
mkdir -p bin
../kursal/bin/kursal build krayon -o bin/krayon
```

## Build a site

```sh
bin/krayon init my-site
bin/krayon build my-site
```

The generated files are in `my-site/dist`. Use `bin/krayon check my-site` to
validate without replacing the output, or `bin/krayon routes my-site` to see
planned URLs. See the [quickstart](docs/src/start.md) and
[CLI reference](docs/src/cli.md) for details.

Use `--overlay DIR` with `build`, `check`, or `routes` to merge externally
generated source into a site for one command.

To preview a site locally, run `bin/krayon preview my-site` and open the
URL it prints. Kable serves a temporary build on loopback.
Pass `--drafts` to preview draft pages.

## Examples

- [`examples/hello-site`](examples/hello-site) is a small independent site.
- [`examples/blog-site`](examples/blog-site) has Markdown posts, excerpts,
  collection navigation, a paginated archive, an Atom feed, and a sitemap.
  Its [README](examples/blog-site/README.md) explains how to build and preview it.
- [`examples/portfolio-site`](examples/portfolio-site) generates project pages
  from TOML data and groups project cards by category.
- [`examples/handbook-site`](examples/handbook-site) uses directory defaults and
  page queries to keep a Markdown guide's sidebar in sync with its pages.

Each example is a standalone site. Build one with
`bin/krayon build examples/portfolio-site`, or use `bin/krayon preview` with
the same path to browse it locally. Each example has a README with its main
features and deployment notes.

## Documentation

The [documentation](docs/src/index.md) is itself a Krayon site. Build it
with the API reference generated from Krayon's library source:

```sh
bin/krayon check docs
python3 scripts/build_docs.py
```

Add `--preview` to serve the guides and generated API on loopback.

The script runs `kursal doc`, filters its output to Krayon's libraries, adds
the layouts and assets from `docs/api-theme` to a source overlay, and builds
the guides and API as one Krayon site. Running `bin/krayon build docs` alone
builds the guides with an API placeholder. Host `docs/dist` at `/` on a static
host. To publish under a prefix such as `/krayon`, set `base_path = "/krayon"`
in `docs/krayon.toml`, rerun the script, and mount `docs/dist` at that prefix.
The documentation uses Krayon's URL helpers for navigation and assets.

## Development

Run `python3 tests/integration.py` for the end-to-end checks. They build
Krayon with the adjacent Kursal compiler and use temporary site copies. The
[development guide](docs/src/development.md) describes the repository layout,
public API, and focused shim checks.
