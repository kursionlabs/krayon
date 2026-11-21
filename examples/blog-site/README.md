# Blog example

Build this standalone site from the repository root:

```sh
bin/krayon build examples/blog-site
```

Serve `examples/blog-site/dist` from `/` with any static file server to view
the result. For example:

```sh
python3 -m http.server 8000 --directory examples/blog-site/dist
```

The site has three published Markdown posts and one draft. Run
`bin/krayon build examples/blog-site --drafts` to include the draft, then run
a normal build again to restore the published output.

The example demonstrates:

- `src/posts/_defaults.toml` for shared post metadata, layout, and URLs.
- A date-sorted `collections.posts` for the home page and post navigation.
- An archive with two posts per page and a topic page using `contains`.
- Markdown excerpts split by `<!-- more -->` and a shared post card include.
- The `url` filter on template links, ready for a configured `base_path`.
- An Atom feed and XML sitemap built from page collections with `absolute_url`.

The `origin = "https://example.com"` setting supplies the absolute URLs in
`atom.xml` and `sitemap.xml`. Replace it with the real site's origin before
publishing. Krayon checks same-origin links in the generated XML.

To mount the site under a prefix, add `base_path = "/blog"` near the top of
`krayon.toml`, before `[collections.posts]`, and rebuild. Template links and
Markdown links will use that prefix; output files remain under `dist`.
Mount `dist` at `/blog` on the static host when using that prefix.
