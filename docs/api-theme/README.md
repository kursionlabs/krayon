# Krayon API layouts

These layouts and assets are added as a source overlay when building
the API reference. Kursal's `docs/site` supplied their initial version. The
API uses the same stylesheet and theme toggle as the user guides, with its own
CSS for search and generated reference content.

`kursal doc` generates the pages and search index. `scripts/build_docs.py`
filters them to Krayon libraries, adds these layouts to the overlay, and
builds the complete site with Krayon.
