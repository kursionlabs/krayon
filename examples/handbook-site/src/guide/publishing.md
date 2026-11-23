+++
title = "Publish the site"
order = 3
+++
# Publish the site

Run `krayon check` to validate links, then `krayon build` to write `dist/`.
Serve that directory with any static host.

The layout uses the `url` filter for navigation and assets, so a configured
`base_path` can move the handbook under a path prefix.
