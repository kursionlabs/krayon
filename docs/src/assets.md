+++
title = "Assets and fingerprints"
layout = "base.html"
+++
# Assets and fingerprints

Set `fingerprint_assets = true` to also copy each asset with its SHA-256
digest before its extension, in the form `site.<64 hex digits>.css`. Use
`{{ "/assets/css/site.css" | asset_url }}` in templates to link to the
fingerprinted copy. The filter accepts a root-relative asset path, preserves
query strings and fragments, and applies `base_path`. It resolves to the
ordinary asset path when fingerprinting is disabled and reports an error for
an unknown asset. Original asset paths remain available so existing links
and relative URLs inside CSS continue to work. Asset content changes update
the fingerprinted filename on the next build. The `asset_urls` site data key
is reserved for this map.
Fingerprinting also rewrites local `url(...)` references and quoted
`@import "..."` or `@import '...'` paths in the fingerprinted CSS copy. It
leaves the original CSS unchanged.
The CSS filename is based on the rewritten bytes, so changing an image or
imported stylesheet updates every stylesheet that depends on it. CSS import
cycles fail the build. Comments, ordinary quoted CSS text, and external URLs
are not rewritten.
When fingerprinting is enabled, Markdown images and links to copied assets
also use fingerprinted URLs, including links to PDFs and downloads.
Root-relative paths such as
`![Logo](/assets/img/logo.png)` resolve from the site root; relative paths
such as `![Logo](../assets/img/logo.png)` resolve from the Markdown source
file. Query strings, fragments, and `base_path` are preserved. Markdown
links to pages still resolve to their page URLs. Links and images outside
the asset directory keep their usual behavior.
