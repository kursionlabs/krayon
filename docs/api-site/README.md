# Krayon API theme

This is the Krayon-owned site shell for the library API reference. Kursal's
`docs/site` supplied the initial API layouts and search script. The API now uses
the user guides' stylesheet, copied from `docs/src/assets/css/docs.css` at build
time, with its own CSS for search and generated reference content.
The theme toggle uses the same script and saved preference as the user guides.

`kursal doc` generates the pages and search index. `scripts/build_docs.py`
combines them here, builds the API site with Krayon, and publishes it beside
the guides.
