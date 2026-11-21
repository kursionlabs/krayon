+++
title = "Blog walkthrough"
layout = "base.html"
+++
# Blog walkthrough

The repository's `examples/blog-site` is a standalone Krayon site. From the
repository root, build it with:

```sh
bin/krayon build examples/blog-site
python3 -m http.server 8000 --directory examples/blog-site/dist
```

Open `http://localhost:8000/` while the static server runs. The example has
three published posts and one draft.

## How it fits together

1. `src/posts/_defaults.toml` gives each Markdown post its layout, collection
   kind, and `/posts/<slug>/` URL pattern. Posts supply their own title, date,
   tags, and body.
2. `krayon.toml` defines a date-sorted `posts` collection. The home page lists
   it, the archive paginates it, and each post gets newer and older neighbors.
3. `<!-- more -->` separates each post's archive excerpt from its full body.
   A shared post-card include renders those excerpts on the home page, archive,
   and topic page.
4. `atom.xml` loops over published posts and `sitemap.xml` loops over rendered
   pages. Both use `absolute_url`, so the site's `origin` must be set before
   publishing. The sample origin is `https://example.com`.

Run `bin/krayon build examples/blog-site --drafts` to include the draft, then
run a normal build to restore the published output. For a site mounted under
`/blog`, set `base_path = "/blog"` before `[collections.posts]` in
`examples/blog-site/krayon.toml` and mount its output at `/blog`.

Continue with [content](content.md), [generation](generation.md), and
[templates](templates.md) for the full behavior.
