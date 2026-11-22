+++
title = "Content and Markdown"
layout = "base.html"
+++
# Content and Markdown

A site can contain Markdown (`.md`), HTML (`.html`), XML (`.xml`), JSON
(`.json`), and text (`.txt`) templates anywhere under `input`. Krayon copies
`assets` recursively and omits layouts and data from page discovery.

## Page URLs

Markdown source paths map to HTML files:

| Source | Output |
| --- | --- |
| `index.md` | `/index.html` |
| `guide/setup.md` | `/guide/setup/index.html` |
| `guide/index.md` | `/guide/index.html` |

HTML pages can set a `permalink` ending in `/` or `.html`. XML, JSON, and text
outputs keep their source path by default and require a matching `.xml`,
`.json`, or `.txt` suffix when given a permalink.

## Directory defaults

Put an optional `_defaults.toml` in `input` or any content subdirectory to
provide front matter defaults for pages beneath it:

```toml
# src/posts/_defaults.toml
layout = "article.html"
kind = "post"
draft = false
permalink_pattern = "/journal/{{ page.slug }}/"
```

Defaults flow into child directories. A child's `_defaults.toml` overrides
matching fields from its ancestors, and a page's own front matter takes final
precedence. Values are replaced as a whole; nested tables are not merged.

These defaults apply to Markdown, HTML, XML, JSON, and text pages, including
pages generated from data. A generated record still overrides the template's
defaults. Set `layout = ""` on a page to omit an inherited layout. Layouts
must have the same extension as the output template, so use directory defaults
or page overrides when a site mixes output formats.

`permalink_pattern` sets URLs for ordinary pages beneath the directory. It
substitutes `{{ page.<field> }}` from the merged front matter, including dotted
fields, and accepts strings, integers, and TOML dates. If no `slug` is set,
`page.slug` defaults to the source filename without its extension. A page can
override the pattern with `permalink`, replace it with another
`permalink_pattern`, or set `permalink_pattern = ""` to use its normal source
URL.

The resulting URL must match the output format and pass the usual path and
collision checks. Generated and paginated templates use their own URL rules;
the directory pattern does not route their outputs.

Other routing and generation fields such as `permalink`, `generate`,
`paginate`, and pagination options cannot appear in `_defaults.toml`; Krayon
reports an error if they do. `_defaults.toml` itself is never published.

## Aliases

An ordinary Markdown or HTML page can keep old URLs with `aliases`:

```toml
aliases = ["/old/", "/old.html"]
```

Each alias produces an HTML file with an immediate refresh and a visible link
to the page's current URL. The target includes `base_path`. These are HTML
redirect pages for static hosts, not HTTP 301 responses.

Aliases may end in `/` or `.html` and pass the usual path and output collision
checks. They are excluded from `collections.pages` and from `page_url` source
lookups. Draft aliases appear only in `--drafts` builds. Generated and
paginated templates, non-HTML outputs, and `_defaults.toml` cannot declare
aliases.

## Drafts

Set `draft = true` in a page's front matter to omit it from a normal build and
from `collections.pages`. Use `krayon preview [SITE_ROOT] --drafts` to serve a
temporary build with drafts without replacing the configured output. Running
`krayon build [SITE_ROOT] --drafts` does replace that output; run a normal build
again to restore the published version. `draft` must be a boolean.

## Markdown and headings

The current Markdown renderer supports ATX headings, paragraphs, links,
images with optional titles, inline code, emphasis, strong text, fenced code
blocks, blockquotes, tight and loose nested ordered and unordered lists, and pipe tables.
It is a documented subset, not a complete CommonMark implementation.

Ordered lists retain the first marker's number. For example, `3. Third` starts
an HTML ordered list at 3; later item marker numbers do not reset the count.

Blank lines between list items or between paragraphs in an item make the list
loose. Loose list items render their paragraphs with `<p>` tags; tight list
items keep the existing compact markup.

Paragraph lines may continue a list item without the item's usual indentation.
An unindented line immediately after a blank line or block ends the item.

Indent headings, tables, fenced code blocks, and blockquotes to the content
column of a list item to keep them inside that item. Text following a block
starts a new paragraph in the same item.

Fenced `kursal` code receives token classes for keywords, types,
strings, numbers, and comments. Other fence languages remain escaped plain
text.

ATX headings may end with explicit attributes, such as
`### Function {#api-function .item-heading .kind-fn}`. IDs must be unique
within a Markdown page. Attribute names may contain ASCII letters, digits,
hyphens, underscores, and colons.

Headings without an explicit ID receive one from their visible text: ASCII
letters become lowercase, spaces, underscores, and hyphens become hyphens,
ASCII punctuation is omitted, and Unicode text is retained. Repeated IDs get
`-2`, `-3`, and so on; an empty slug uses `section`.

Layouts for Markdown pages can build a table of contents from `page.headings`:

```html
{% for heading in page.headings %}<a href="#{{ heading.id }}">{{ heading.text }}</a>{% endfor %}
```

Each record has a one-based `level`, plain `text`, and rendered `id`. Headings
inside blockquotes are included; code fences and raw HTML headings are not.
`headings` is a reserved Markdown front matter field. Markdown pages without
headings expose an empty array.
