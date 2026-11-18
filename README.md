# Krayon

Krayon builds static websites from Markdown, HTML templates, site data, and
assets. It is written in Kursal and produces files for any static host.

## Build Krayon

Bootstrap the adjacent `../kursal` repository first, then run:

```sh
mkdir -p bin
../kursal/bin/kursal build krayon -o bin/krayon
```

## Build a site

```sh
bin/krayon build examples/hello-site
```

`build` accepts a site root, defaulting to the current directory. Krayon reads
`krayon.toml` there when present. This is its complete configuration:

```toml
input = "src"
output = "dist"
layouts = "_includes"
data = "_data/site.toml"
assets = "assets"
```

All paths are relative. `input` and `output` are relative to the site root;
the other paths are relative to `input`. The values above are the defaults.
The site data file and assets directory are optional. The output directory
must be outside the input directory.

A site can contain Markdown (`.md`) and HTML (`.html`) pages anywhere under
`input`. Krayon copies `assets` recursively and omits layouts and data from
page discovery. `index.md` becomes `/index.html`, `guide/setup.md` becomes
`/guide/setup/index.html`, and `guide/index.md` becomes
`/guide/index.html`. A page can set a `permalink` ending in `/` or `.html`.
Krayon fails on output collisions, unsafe paths, missing layouts, and template
errors. It writes into the output directory without clearing older files;
use a fresh output directory for deployment builds.

Pages and layouts may start with TOML front matter between `+++` lines:

```text
+++
title = "Getting started"
layout = "article.html"
permalink = "/start/"
+++
# Getting started

Hello, Krayon.
```

Layouts are looked up under `layouts`. A layout may name another layout in its
own front matter. Page fields are available as `page.title`, `page.permalink`,
and so on; `page.url` is the resolved URL. Values from the site data TOML file
are available as `site.title`, `site.links.repository`, and other dotted keys.

Templates use `{{ page.title }}` for escaped output and `{{ content | safe }}`
for rendered page or layout HTML. They support `or` with a quoted fallback,
`{% if ... %}`, `{% else %}`, and `{% endif %}`. Conditions can test a value
or compare it to a quoted string with `==`. Unknown substitutions fail the
build. Raw HTML in Markdown is passed through deliberately.

The current Markdown renderer supports ATX headings, paragraphs, links, inline
code, emphasis, strong text, fenced code blocks, flat ordered and unordered
lists, and pipe tables. It is a documented subset, not a complete CommonMark
implementation.

## Code and checks

- `krayon/` — thin command-line program
- `lib/site/` — configuration, discovery, routing, rendering, and output
- `lib/html/` — front matter and templates
- `lib/markdown/` — Markdown rendering
- `examples/hello-site/` — independent site example

Kursal programs can call `site::build(&cx, root)` directly. It takes a site
root as a byte span and returns `Result[(), Buffer!]`; the error buffer is a
message suitable for printing. The CLI is a small wrapper around that API.

Run `python3 tests/integration.py` for the end-to-end checks. They build
Krayon with the adjacent Kursal compiler and use temporary site copies.
