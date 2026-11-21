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

Before installing the output, Krayon checks local `href`, `src`, and `srcset`
values in generated HTML, plus `video poster` and `object data` URLs. It also
checks CSS `url()` references in inline styles and copied `.css` assets,
quoted `@import` paths in `<style>` elements and copied CSS, and the XML link
fields described under [output formats](formats.md). Page links and copied
assets must resolve;
fragments targeting generated pages must match an HTML ID. Relative URLs,
query strings, percent escapes, and `base_path` are handled. Absolute
URLs matching `origin` are checked; other origins are ignored. A broken link
fails the build. Krayon reports every broken link with its source file, URL,
line, and column. HTML documents use their first `<base href>` when resolving
relative links, including fragments, `srcset`, and inline CSS URLs. HTML
positions refer to generated HTML, since Markdown and layouts can change
source positions; copied CSS positions refer to the stylesheet source.
Krayon also reports duplicate IDs in generated HTML, including IDs from
layouts, raw HTML, and Markdown headings. Diagnostics show both occurrences
in the generated page. Duplicate IDs and broken links are reported together.
