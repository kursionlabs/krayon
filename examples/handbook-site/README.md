# Handbook example

Build Krayon from the current source as described in the
[repository README](../../README.md), then build this standalone documentation
site from the repository root:

```sh
bin/krayon build examples/handbook-site
```

Open it with `bin/krayon preview examples/handbook-site`, or serve
`examples/handbook-site/dist` from a static host.

The pages under `src/guide/` inherit a layout and parent URL from
`_defaults.toml`. The shared `guide.html` layout queries the immediate children
of `/guide/` and sorts them by `order`, so a new page joins the sidebar when
you give it a title and order. The example also shows Markdown source links,
heading attributes, tables, indented code, an alias, and the `url` filter.

To mount the site under a prefix, add `base_path = "/handbook"` to
`krayon.toml`, rebuild, and mount `dist` at `/handbook` on the host.
