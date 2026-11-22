+++
title = "Command-line tools"
layout = "base.html"
+++
# Command-line tools

## Initialize a site

Run `bin/krayon init [DIR]` to create a starter site.

`init` defaults to the current directory and refuses to overwrite a
nonempty directory. It creates `krayon.toml`, a Markdown home page, a shared
HTML layout, and a `.gitignore` for `dist`.

## Build a site

`bin/krayon build [SITE_ROOT]` renders the site and writes its configured output.
The site root defaults to the current directory.

## Preview locally

Run `bin/krayon preview [SITE_ROOT]` to build once and serve the result on
loopback. Open the URL it prints. The URL includes `base_path` when configured.
Add `--drafts` to include drafts or `--overlay DIR` to merge generated sources.

Use `--port PORT` to choose the loopback port. Omit it or pass `--port 0` to
let the OS choose an available port. Kable serves preview output from a
temporary directory.

Press Ctrl+C to stop the server and remove the temporary files.

Use `python3 scripts/build_docs.py --preview` to preview the Krayon guides with
the generated API reference. It accepts the same `--port` option.

## Check without installing output

Run `bin/krayon check [SITE_ROOT]` to render and validate a site without
replacing its output directory. It catches the same template, output, and
local link errors as `build`, then removes its temporary staging directory.
The configured output remains untouched, whether or not the check succeeds.
Add `--drafts` to check draft pages too.

## Add generated source

Pass `--overlay DIR` to `build`, `check`, or `routes` to add a directory of
generated source files for that invocation. Paths inside `DIR` are relative to
the site's configured input directory. For example, `generated/api/index.md`
appears at `src/api/index.md` with:

```sh
bin/krayon build my-site --overlay generated
```

Overlay files replace files at the same relative path; other directories and
files are merged. Krayon then discovers routes and validates the combined
source using the site's configuration. The original input and overlay stay
untouched, and a failed build leaves the previous output in place.

Symlinks inside either source tree are rejected for an overlay build. The
overlay directory must be outside the site's input directory.

## Inspect routes

To inspect routes before building, run `bin/krayon routes [SITE_ROOT]`. It
lists pages as `page<TAB>source<TAB>URL`, redirects as
`alias<TAB>old URL<TAB>target URL`, and assets as
`asset<TAB>source<TAB>preferred URL`. Rows are grouped in that order; each
group is sorted by its URL or source path. URLs include `base_path`, and asset
URLs use fingerprinted filenames when `fingerprint_assets` is enabled.

Generated and paginated pages use their source template with an item or page
number. Add `--drafts` to include drafts. Add `--json` for an object with
`pages`, `aliases`, and `assets` arrays in the same order. Page and asset
objects have `source` and `url` fields; alias objects have `url` and `target`.

Page and alias objects also have an `output` path relative to the configured
output directory. Each asset has an `outputs` array containing its ordinary
copy, followed by its fingerprinted copy when fingerprinting is enabled.
These paths omit `base_path`.

For example, `bin/krayon routes --json` can feed a deployment script.
`routes` checks source discovery and route collisions, but does not render
pages, validate links, or write to the output directory.
