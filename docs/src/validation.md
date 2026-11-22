+++
title = "Validation and safe output"
layout = "base.html"
+++
# Validation and safe output

## Output installation

Krayon fails on output collisions, unsafe paths, missing layouts, and template
errors. It renders into a staging directory and replaces the configured output
only after a successful build. A failed render leaves the previous output
intact. Krayon owns the output directory and removes its previous contents on
a successful rebuild, including files placed there by hand.

## Link and ID checks

Before installing the output, Krayon checks local references in:

- HTML `href`, `src`, and `srcset` values, plus `video poster` and `object data` URLs.
- CSS `url()` references in inline styles and copied `.css` assets, and quoted
  `@import` paths in `<style>` elements and copied CSS.
- The XML link fields described under [output formats](formats.md).

Page links and copied assets must resolve. Fragments targeting generated pages
must match an HTML ID. Relative URLs, query strings, percent escapes, and
`base_path` are handled. Absolute URLs matching `origin` are checked; other
origins are ignored.

A broken link fails the build. Krayon reports every broken link with its source
file, URL, line, and column. Links and images in a Markdown page body point to
their source locations. Links introduced by layouts or raw HTML use generated
HTML locations. HTML documents use their first `<base href>` when resolving
relative links, including fragments, `srcset`, and inline CSS URLs. Copied CSS
positions refer to the stylesheet source.

Krayon also reports duplicate IDs in generated HTML, including IDs from
layouts, raw HTML, and Markdown headings. Diagnostics show both occurrences
in the generated page. Duplicate IDs and broken links are reported together.
