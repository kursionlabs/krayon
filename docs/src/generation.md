+++
title = "Collections and generation"
layout = "base.html"
+++
# Collections and generation

## Generate pages from site data

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
XML, JSON, and text templates.

A template or record can set `draft = true`; a record's value overrides the
template default.

## Pagination

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

## Named collections and navigation

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
