+++
title = "Configuration"
layout = "base.html"
+++
# Configuration

`build` accepts a site root, defaulting to the current directory. Krayon reads
`krayon.toml` there when present. This is its complete configuration:

```toml
input = "src"
output = "dist"
layouts = "_includes"
data = "_data/site.toml"
assets = "assets"
fingerprint_assets = false
base_path = ""
origin = ""
exclude = []

[collections.posts]
where = { field = "kind", equals = "post" }
sort_by = "date"
sort_order = "desc"
```

## Paths and exclusions

All paths are relative. `input` and `output` are relative to the site root;
the other paths are relative to `input`. The scalar values above are the defaults.
The site data file and assets directory are optional. The output directory
must be outside the input directory.
Use `exclude = ["internal/", "notes/*.draft.md", "**/private/"]` to skip
source discovery. Rules are relative to `input`. A rule without a trailing
`/` matches files; a rule ending in `/` excludes matching directories and
everything beneath them. Literal paths match exactly. `*` matches within one
path segment; `**` must be a whole segment and matches zero or more segments.
Other glob syntax, such as `?` or character classes, is unsupported.
Excluded pages do not appear in collections or
`page_url` lookups; links to them fail the usual local link check. Exclusions
also apply to `--drafts` builds. They do not affect asset copying.

## Named collections

The optional `[collections.posts]` table defines a named page collection;
omit it when no collection is needed. Names must start with a letter or
underscore and contain only letters, digits, and underscores. `pages` is
reserved for Krayon's built-in collection.

## Deployment URLs

Set `base_path` to a path such as `"/docs"` when mounting the
generated output there. The default empty string serves the site at `/`.
Krayon keeps page URLs and output paths unprefixed, and exposes the setting as
`site.base_path`.
Set `origin` to the site's HTTP or HTTPS origin, such as
`"https://example.org"`, when templates need absolute URLs. It accepts an
optional port and trailing slash, stores the origin without the trailing
slash, and exposes it as `site.origin`. The default empty origin disables
`| absolute_url`. With `origin` set, links using that configured origin are checked
as local links, including absolute URLs emitted by `| absolute_url`.
