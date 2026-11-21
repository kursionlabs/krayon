+++
title = "Output formats"
layout = "base.html"
+++
# Output formats

XML, JSON, and text templates use the same page fields, site data, collections,
loops, layouts, and includes as HTML. Layouts and includes must use the same
extension as their template. HTML and XML substitutions escape markup;
JSON substitutions escape JSON string contents and must be placed inside JSON
quotes. Use `{{ site.catalog | json }}` in a JSON template to write a complete
JSON value without surrounding quotes. The filter supports strings, numbers,
booleans, dates (as strings), arrays, and tables, including values from
`collections.pages`; it rejects NaN and infinity. It can follow `| url`, as in
`{{ "/assets/site.css" | url | json }}`. Text substitutions are copied unchanged.
Krayon validates completed JSON and XML documents before installing the
output; invalid output reports its generated line and column and leaves the
previous output intact. XML validation accepts UTF-8 XML 1.0 with comments,
processing instructions, CDATA, and predefined or numeric references. DTD
declarations and other encodings are unsupported. For JSON arrays, loops expose
`loop.first`, `loop.last`, and the one-based `loop.index`:

```text
{"pages":[{% for entry in collections.pages %}{% if loop.first %}{% else %},{% endif %}"{{ entry.url }}"{% endfor %}]}
```

`collections.pages` contains rendered HTML and Markdown pages; output files
such as `sitemap.xml` are excluded. HTML link checks accept links to these
files. In generated XML, Krayon also checks sitemap `loc` elements, `link`
`href` attributes in feeds using the Atom namespace, and RSS channel and item
`link` text. Other XML fields and references in JSON and text files are not
scanned. Relative Atom links honor `xml:base` on the feed, entry, or link;
without it, they resolve from the feed URL.
