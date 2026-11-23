# Portfolio example

Build Krayon from the current source as described in the
[repository README](../../README.md), then build this standalone site from the
repository root:

```sh
bin/krayon build examples/portfolio-site
```

Open it with `bin/krayon preview examples/portfolio-site`, or serve
`examples/portfolio-site/dist` from a static host.

The project records in `src/_data/site.toml` provide titles, categories,
summaries, URLs, and detail text. The home page groups them by category and
uses a shared card include. `src/work/project.html` generates each project
page from the same records. Add another `[[projects]]` table to create a new
card and detail page without copying a template.

All template links use the `url` filter. To deploy under a path prefix, add
`base_path = "/portfolio"` to `krayon.toml`, rebuild, and mount `dist` at
`/portfolio` on the host.
