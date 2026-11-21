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

## Check without installing output

Run `bin/krayon check [SITE_ROOT]` to render and validate a site without
replacing its output directory. It catches the same template, output, and
local link errors as `build`, then removes its temporary staging directory.
The configured output remains untouched, whether or not the check succeeds.
Add `--drafts` to check draft pages too.

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
