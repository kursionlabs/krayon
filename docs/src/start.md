+++
title = "Quickstart"
layout = "base.html"
+++
# Quickstart

Bootstrap the adjacent `../kursal` repository, then build Krayon from the
repository root:

```sh
mkdir -p bin
../kursal/bin/kursal build krayon -o bin/krayon
```

Create and build a site:

```sh
bin/krayon init my-site
bin/krayon build my-site
```

Krayon writes the generated site to `my-site/dist`. Serve that directory
from `/` with a static file server, or upload it to a static host.

Use `bin/krayon check my-site` to validate without replacing `dist`, and
`bin/krayon routes my-site` to inspect the planned URLs. See the
[CLI reference](cli.md) for their options.

Try the repository's `examples/hello-site` for a small site, or follow the
[blog walkthrough](blog.md) to see collections, layouts, and feeds together.
