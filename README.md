# Krayon

Krayon builds static websites from Markdown, HTML, XML, JSON, and text
templates, site data, and assets. It is written in Kursal and produces files
for any static host.

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
origin = ""

[collections.posts]
where = { field = "kind", equals = "post" }
sort_by = "date"
sort_order = "desc"
```

All paths are relative. `input` and `output` are relative to the site root;
the other paths are relative to `input`. The scalar values above are the defaults.
The site data file and assets directory are optional. The output directory
must be outside the input directory.
The optional `[collections.posts]` table defines a named page collection;
omit it when no collection is needed. Names must start with a letter or
underscore and contain only letters, digits, and underscores. `pages` is
reserved for Krayon's built-in collection.
Set `base_path` to a path such as `"/docs"` when mounting the
generated output there. The default empty string serves the site at `/`.
Krayon keeps page URLs and output paths unprefixed, and exposes the setting as
`site.base_path`.
Set `origin` to the site's HTTP or HTTPS origin, such as
`"https://example.org"`, when templates need absolute URLs. It accepts an
optional port and trailing slash, stores the origin without the trailing
slash, and exposes it as `site.origin`. The default empty origin disables
`| absolute_url`.

A site can contain Markdown (`.md`), HTML (`.html`), XML (`.xml`), JSON
(`.json`), and text (`.txt`) templates anywhere under `input`. Krayon copies
`assets` recursively and omits layouts and data from page discovery.
`index.md` becomes `/index.html`, `guide/setup.md` becomes
`/guide/setup/index.html`, and `guide/index.md` becomes
`/guide/index.html`. HTML pages can set a `permalink` ending in `/` or
`.html`; XML, JSON, and text outputs keep their source path by default and
require a matching `.xml`, `.json`, or `.txt` suffix when given a permalink.
Krayon fails on output collisions, unsafe paths, missing layouts, and template
errors. It renders into a staging directory and replaces the configured output
only after a successful build. A failed render leaves the previous output
intact. Krayon owns the output directory and removes its previous contents on
a successful rebuild, including files placed there by hand.

Set `draft = true` in a page's front matter to omit it from a normal build and
from `collections.pages`. Run `krayon build [SITE_ROOT] --drafts` to include
drafts in a preview build. This replaces the configured output with the preview;
run a normal build again to restore the published output. `draft` must be a
boolean.

An output template can generate a file for each table in a site data array:

```html
+++
generate = "site.products"
permalink = "/products/{{ item.slug }}/"
layout = "base.html"
kind = "product"
+++
<h1>{{ page.title }}</h1>
```

The site data file supplies records:

```toml
[[products]]
slug = "widget"
title = "Widget"
```

The template's `permalink` pattern substitutes `{{ item.<field> }}` from each
record, including nested fields. Substituted fields must be strings or integers.
A record can set an explicit string `url` to override the pattern. Each resolved
URL must have the suffix for the template format (or end in `/` for HTML) and
pass the usual path and collision checks.
Record fields become `page.*` fields and override the template's front matter
defaults; `page.permalink` is the resolved URL. A template can omit `permalink`
when every record supplies `url`.
The template itself produces no file. Generated HTML pages appear in
`collections.pages`. Generated files support layouts and includes and pass
the same output collision checks as ordinary files. `generate` accepts dotted
site data paths such as `site.catalog.products`; it is available in HTML,
XML, JSON, and text templates. A template or record can set `draft = true`;
a record's value overrides the template default.

An HTML template can split a site data array or page collection across
list pages:

```html
+++
paginate = "site.posts"
page_size = 10
where = { field = "published", equals = true }
sort_by = "date"
sort_order = "desc"
permalink = "/blog/"
+++
{% for post in page.pagination.items %}<h2>{{ post.title }}</h2>{% endfor %}
{% if page.pagination.previous %}<a href="{{ page.pagination.previous | url }}">Previous</a>{% endif %}
{% if page.pagination.next %}<a href="{{ page.pagination.next | url }}">Next</a>{% endif %}
```

The first page uses `/blog/`; later pages use `/blog/page/2/`,
`/blog/page/3/`, and so on. Without `permalink`, the template's normal URL is
the base. The base must end in `/`. Set
`page_permalink = "/blog/p{{ page.pagination.number }}.html"` to choose the
URLs for pages 2 and later. The pattern must contain that placeholder exactly
once and resolve to safe HTML URLs; the generated pages pass the usual output
collision checks. `previous` and `next` use the chosen URLs.
`page.pagination` also exposes the one-based `number`, `total_pages`, and
`total_items`. An empty array produces one page
with no items. Pagination preserves array order and accepts any TOML array
values. Paginated pages appear in `collections.pages`; the template does not
produce an additional file. `paginate` and `generate` cannot be combined.
The template's `draft` flag applies to all its pages. An optional `where` table
selects records before sorting and slicing. Its `field` can be a dotted path;
use either `equals` to match a scalar field or `contains` to match an element
of an array field. Both accept a string, integer, boolean, or TOML date. Like
the template filters, comparisons use scalar text and skip records with a
missing field or the wrong field shape; array items must be tables. For a tag
archive, use `where = { field = "tags", contains = "kursal" }`.
`sort_by` is optional and accepts a field path such as `author.name`;
`sort_order` is `asc` by default or `desc`. Sorting happens before page
slices are chosen.

Use `paginate = "collections.pages"` to archive Markdown and HTML pages by
their front matter. The source includes published pages (and drafts with
`--drafts`) plus pages generated from site data. All templates paginating
`collections.pages` read the same snapshot, which excludes pages created by
those templates; their archive pages appear in the final `collections.pages`
used while rendering other templates.

Named page collections select from that same initial page snapshot, so they
also exclude pages created by pagination. Their `where`, `sort_by`, and
`sort_order` rules use the pagination syntax above. Without rules, a named
collection contains every page in the snapshot in URL order. Templates and
layouts can loop over `collections.posts`, and an HTML template can use
`paginate = "collections.posts"`. Named collections stay fixed during the
build; `collections.pages` includes generated archive pages when templates
render. Named collections support drafts according to the build's `--drafts`
setting.

A page in a named collection can link to its neighbors in that collection's
configured order. `page.collection_navigation.posts.previous` and `.next`
contain the neighboring page records, including their `url` and front matter.
At either end of the collection, the missing neighbor has no fields. Check for
the neighbor before rendering a link:

```html
{% if page.collection_navigation.posts.previous %}<a href="{{ page.collection_navigation.posts.previous.url | url }}">Previous: {{ page.collection_navigation.posts.previous.title }}</a>{% endif %}
{% if page.collection_navigation.posts.next %}<a href="{{ page.collection_navigation.posts.next.url | url }}">Next: {{ page.collection_navigation.posts.next.title }}</a>{% endif %}
```

Pages can belong to multiple named collections and get separate navigation
for each. Pages outside a collection have no navigation for it. The
`collection_navigation` front matter field is reserved.

XML, JSON, and text templates use the same page fields, site data, collections,
loops, layouts, and includes as HTML. Layouts and includes must use the same
extension as their template. HTML and XML substitutions escape markup;
JSON substitutions escape JSON string contents and must be placed inside JSON
quotes. Use `{{ site.catalog | json }}` in a JSON template to write a complete
JSON value without surrounding quotes. The filter supports strings, numbers,
booleans, dates (as strings), arrays, and tables, including values from
`collections.pages`; it rejects NaN and infinity. It can follow `| url`, as in
`{{ "/assets/site.css" | url | json }}`. Text substitutions are copied unchanged.
Krayon validates completed JSON and XML documents before installing the
output; invalid output reports its generated line and column and leaves the
previous output intact. XML validation accepts UTF-8 XML 1.0 with comments,
processing instructions, CDATA, and predefined or numeric references. DTD
declarations and other encodings are unsupported. For JSON arrays, loops expose
`loop.first`, `loop.last`, and the one-based `loop.index`:

```text
{"pages":[{% for entry in collections.pages %}{% if loop.first %}{% else %},{% endif %}"{{ entry.url }}"{% endfor %}]}
```

`collections.pages` contains rendered HTML and Markdown pages; output files
such as `sitemap.xml` are excluded. HTML link checks accept links to these
files, while references inside XML, JSON, and text files are not scanned.

Before installing the output, Krayon checks local `href`, `src`, and `srcset`
values in generated HTML, plus CSS `url()` references in inline styles and
copied `.css` assets. Page links and copied assets must
resolve; fragments targeting generated pages must match an HTML ID. Relative
URLs, query strings, percent escapes, and `base_path` are handled;
external URLs are ignored. A broken link fails the build and reports the
source file, URL, line, and column. HTML positions refer to the generated
HTML, since Markdown and layouts can change the source positions; copied CSS
positions refer to the stylesheet source.

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
for rendered page or layout HTML. The `| safe` filter writes a scalar value
unchanged, including rendered Markdown excerpts. Templates support `or` with
a quoted fallback,
`{% if ... %}`, `{% else %}`, and `{% endif %}`. Conditions can test a value
or compare it to a quoted string with `==`. Empty arrays and tables are false;
nonempty arrays and tables are true. Scalar conditions keep their existing
behavior: empty strings, `false`, and `0` are false. An HTML page can list all
pages, ordered by URL, with `{% for entry in collections.pages %}` and
`{% endfor %}`. Each entry has its front matter fields and a resolved `url`.
Loops also work over arrays in site data and can be nested. Unknown
substitutions fail the build. Markdown page bodies are rendered as Markdown;
template expressions are evaluated in HTML pages and layouts. Raw HTML in
Markdown is passed through deliberately.

A Markdown page can put `<!-- more -->` on its own line outside a fenced code
block to mark an archive excerpt. `collections.pages` exposes the Markdown
before that line as rendered HTML in `entry.excerpt`. Use
`{{ entry.excerpt | safe }}` in an HTML archive template; an ordinary
`{{ entry.excerpt }}` substitution escapes the HTML. Pages without a marker
have no generated excerpt. The marker is omitted from the full page.

Templates can reuse same-format fragments from the configured `layouts`
directory:

```html
{% include "components/card.html" %}
```

Includes share the current page, site data, loop variables, and rendered
`content`. Paths are relative to `layouts` and must end in
`.html`. Missing files, paths that escape the layouts directory,
and include cycles fail the build. An include in an inactive `if`
branch is not loaded.
Template errors report the source file, line, and column. Errors inside an
include also show the include chain, with each call site's location.

Use `{{ page.url | url }}` or `{{ "/assets/site.css" | url }}`
in templates to prefix a root relative local URL. The filter leaves external,
protocol relative, relative, and fragment URLs alone. Markdown links with root
relative targets are prefixed automatically; raw HTML in Markdown is passed
through as written.
With `origin` configured, `{{ page.url | absolute_url }}` produces a full URL
including `base_path`. The filter leaves external, protocol relative,
relative, and fragment URLs unchanged. It works in HTML, XML, and JSON
templates; use `{{ page.url | absolute_url | json }}` to emit a complete JSON
string value.

Loop sources can be filtered with `children_of`, `where`, `contains`,
`group_by`, and `sort_by`:

```html
{% for child in collections.pages | children_of: page.url %}{{ child.title }}{% endfor %}
{% for item in page.nav_items | where: "kind", "function" %}{{ item.name }}{% endfor %}
{% for post in collections.pages | contains: "tags", "kursal" %}{{ post.title }}{% endfor %}
{% for group in page.nav_items | group_by: "kind" %}
  {{ group.key }}{% for item in group.items %}{{ item.name }}{% endfor %}
{% endfor %}
{% for post in site.posts | sort_by: "date", "desc" %}{{ post.title }}{% endfor %}
```

`children_of` matches a record's `parent` URL or any URL in its `parents`
array. These relationships are explicit front matter; URL nesting has no
effect. `where` compares a scalar field to a quoted value or template field;
`contains` checks whether an array field has a matching scalar element. Both
accept dotted field paths and skip missing or differently shaped fields.
`group_by` preserves first-seen group order and produces records with `key`
and `items`. `sort_by` accepts a field path and an optional `"asc"` or
`"desc"` order; it preserves source order for equal keys. It compares
strings lexically, integers and floats numerically, booleans as false before
true, and TOML dates by their text. Sort keys must be present, scalar, and
the same type across records. These filters work on arrays of records,
including `collections.pages`.

The current Markdown renderer supports ATX headings, paragraphs, links,
images with optional titles, inline code, emphasis, strong text, fenced code
blocks, blockquotes, tight nested ordered and unordered lists, and pipe tables.
It is a documented subset, not a complete CommonMark implementation.
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
- `lib/records/` — record filtering and sorting shared by queries and pagination
- `lib/json/` — generated JSON validation
- `lib/xml/` — generated XML validation
- `lib/url/` — deployment path prefixes
- `lib/highlight/` — fenced code highlighting
- `examples/hello-site/` — independent site example

Kursal programs can call `site::build(&cx, root)` directly. It takes a site
root as a byte span and returns `Result[(), Buffer!]`; the error buffer is a
message suitable for printing. The CLI is a small wrapper around that API.
`site::build_with_drafts(&cx, root, true)` includes drafts for previews.

Run `python3 tests/integration.py` for the end-to-end checks. They build
Krayon with the adjacent Kursal compiler and use temporary site copies.
CI bootstraps Kursal from its `main` branch, builds Krayon, and runs these checks.
If the Kursal repository is private, set the `KURSAL_REPO_TOKEN` Actions secret
to a token with read access to that repository.
