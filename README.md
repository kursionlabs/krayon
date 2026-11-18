# Krayon

Krayon is a static site generator written in Kursal. Its first target is the
source of `kursal.dev`: Markdown pages with simple YAML front matter, Nunjucks
layouts, and passthrough assets.

## Build

Bootstrap Kursal in `../kursal` first, then from this directory:

```sh
mkdir -p bin
../kursal/bin/kursal build krayon -o bin/krayon
bin/krayon build ../kursal.dev/src dist
```

Deploy `dist/` to any static file host. The root page is `index.html` and
other pages are emitted as `name/index.html`.

Krayon currently supports the Markdown and Nunjucks features used by the
Kursal site: headings, paragraphs, links, code, lists, tables, front matter,
variable interpolation, and simple `if` blocks. It reads shared values from
`src/_data/site.json`, layouts from `src/_includes/`, and copies files from
`src/assets/`. It does not yet implement general Nunjucks or recursive asset
directories.

## Layout

- `krayon/` — the executable and site build orchestration
- `lib/markdown/` — Markdown rendering
- `lib/html/` — front matter, site data, and template rendering
