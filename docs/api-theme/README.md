# Krayon API layouts

These layouts and assets are merged into the documentation site when building
the API reference. Kursal's `docs/site` supplied their initial version. The
API uses the same stylesheet and theme toggle as the user guides, with its own
CSS for search and generated reference content.

`kursal doc` generates the pages and search index. `scripts/build_docs.py`
filters them to Krayon libraries, adds these layouts to a staged copy of
`docs/`, and builds the complete site with Krayon.
