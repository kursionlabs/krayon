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
base_path = ""
```

All paths are relative. `input` and `output` are relative to the site root;
the other paths are relative to `input`. The values above are the defaults.
The site data file and assets directory are optional. The output directory
must be outside the input directory.
Set `base_path` to a path such as `"/docs"` when mounting the
generated output there. The default empty string serves the site at `/`.
Krayon keeps page URLs and output paths unprefixed, and exposes the setting as
`site.base_path`.

A site can contain Markdown (`.md`) and HTML (`.html`) pages anywhere under
`input`. Krayon copies `assets` recursively and omits layouts and data from
page discovery. `index.md` becomes `/index.html`, `guide/setup.md` becomes
`/guide/setup/index.html`, and `guide/index.md` becomes
`/guide/index.html`. A page can set a `permalink` ending in `/` or `.html`.
Krayon fails on output collisions, unsafe paths, missing layouts, and template
errors. It renders into a staging directory and replaces the configured output
only after a successful build. A failed render leaves the previous output
intact. Krayon owns the output directory and removes its previous contents on
a successful rebuild, including files placed there by hand.

Before installing the output, Krayon checks local `href` and `src`
values in generated HTML. Page links and copied assets must
resolve; fragments targeting generated pages must match an HTML ID. Relative
URLs, query strings, percent escapes, and `base_path` are handled;
external URLs are ignored. A broken link fails the build and reports the
source page and URL.
CSS `url()` references and `srcset` are not checked.

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
or compare it to a quoted string with `==`. An HTML page can list all pages,
ordered by URL, with `{% for entry in collections.pages %}` and
`{% endfor %}`. Each entry has its front matter fields and a resolved `url`.
Loops also work over arrays in site data and can be nested. Unknown
substitutions fail the build. Markdown page bodies are rendered as Markdown;
template expressions are evaluated in HTML pages and layouts. Raw HTML in
Markdown is passed through deliberately.

Use `{{ page.url | url }}` or `{{ "/assets/site.css" | url }}`
in templates to prefix a root relative local URL. The filter leaves external,
protocol relative, relative, and fragment URLs alone. Markdown links with root
relative targets are prefixed automatically; raw HTML in Markdown is passed
through as written.

Loop sources can be filtered with `children_of`, `where`, and `group_by`:

```html
{% for child in collections.pages | children_of: page.url %}{{ child.title }}{% endfor %}
{% for item in page.nav_items | where: "kind", "function" %}{{ item.name }}{% endfor %}
{% for group in page.nav_items | group_by: "kind" %}
  {{ group.key }}{% for item in group.items %}{{ item.name }}{% endfor %}
{% endfor %}
```

`children_of` matches a record's `parent` URL or any URL in its `parents`
array. These relationships are explicit front matter; URL nesting has no
effect. `where` compares a scalar field to a quoted value or template field.
`group_by` preserves first-seen group order and produces records with `key`
and `items`. All three work on arrays of records, including `collections.pages`.

The current Markdown renderer supports ATX headings, paragraphs, links, inline
code, emphasis, strong text, fenced code blocks, flat ordered and unordered
lists, and pipe tables. It is a documented subset, not a complete CommonMark
implementation.
Fenced `kursal` code receives token classes for keywords, types,
strings, numbers, and comments. Other fence languages remain escaped plain
text.
ATX headings may end with explicit attributes, such as
`### Function {#api-function .item-heading .kind-fn}`. IDs must be unique
within a Markdown page. Attribute names may contain ASCII letters, digits,
hyphens, underscores, and colons.

## Code and checks

- `krayon/` — thin command-line program
- `lib/site/` — configuration, discovery, routing, rendering, and output
- `lib/html/` — front matter and templates
- `lib/markdown/` — Markdown rendering
- `lib/links/` — local link validation
- `lib/url/` — deployment path prefixes
- `lib/highlight/` — fenced code highlighting
- `examples/hello-site/` — independent site example

Kursal programs can call `site::build(&cx, root)` directly. It takes a site
root as a byte span and returns `Result[(), Buffer!]`; the error buffer is a
message suitable for printing. The CLI is a small wrapper around that API.

Run `python3 tests/integration.py` for the end-to-end checks. They build
Krayon with the adjacent Kursal compiler and use temporary site copies.
