+++
title = "Templates"
layout = "base.html"
+++
# Templates

## Front matter and layouts

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

## Excerpts

A Markdown page can put `<!-- more -->` on its own line outside a fenced code
block to mark an archive excerpt. `collections.pages` exposes the Markdown
before that line as rendered HTML in `entry.excerpt`. Use
`{{ entry.excerpt | safe }}` in an HTML archive template; an ordinary
`{{ entry.excerpt }}` substitution escapes the HTML. Pages without a marker
have no generated excerpt. The marker is omitted from the full page.

## Includes

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

## URL filters

Use `{{ page.url | url }}` or `{{ "/assets/site.css" | url }}`
in templates to prefix a root relative local URL. The filter leaves external,
protocol relative, relative, and fragment URLs alone. Markdown links with root
relative targets are prefixed automatically; raw HTML in Markdown is passed
through as written.
Markdown links to local `.md` source files resolve to the target page's
generated URL, including a custom `permalink`. Relative paths are resolved
from the linking source file; paths beginning with `/` are resolved from
`input`. Queries and fragments are preserved, and `base_path` is applied to
the resolved URL. For example, `[Guide](../guide/index.md#setup)` can link to
`/guide/` or any permalink set by that source page. Links to omitted drafts
fail the local link check in a normal build. External links and raw HTML links
keep their existing behavior. Markdown excerpts use the same resolution.
Templates and layouts can resolve a page source path explicitly with
`{{ "guide/index.md" | page_url }}`. The path is relative to `input`, with an
optional leading `/` or `./`; the filter preserves a query or fragment and
applies `base_path`. It also accepts a string field, such as
`{{ page.guide_source | page_url }}`. A missing source fails the build at the
template expression. Use `{{ "guide/index.md" | page_url | json }}` for a
complete JSON string value. The filter works for ordinary Markdown, HTML,
XML, JSON, and text page sources. Generated and paginated templates have no
single URL, so their source paths cannot be resolved with `page_url`.
With `origin` configured, `{{ page.url | absolute_url }}` produces a full URL
including `base_path`. The filter leaves external, protocol relative,
relative, and fragment URLs unchanged. It works in HTML, XML, and JSON
templates; use `{{ page.url | absolute_url | json }}` to emit a complete JSON
string value.

## Page queries

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
