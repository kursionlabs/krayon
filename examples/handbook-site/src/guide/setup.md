+++
title = "Set up a project"
order = 1
aliases = ["/start/"]
+++
# Set up a project {#setup .guide-heading}

Create a site directory, add a `krayon.toml`, and place pages under `src/`.
This example already has the configuration and a shared layout.

    input = "src"
    output = "dist"

The old `/start/` URL redirects here through the `aliases` front matter field.
Next, [write a page](writing.md).
