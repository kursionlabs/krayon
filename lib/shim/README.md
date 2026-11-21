# Kursal standard library candidates

`shim` is an overlay on Kursal's standard library. Its root module forwards
the current `std` modules, and its own modules hold additions proposed for
the standard library. It is a staging area, not part of Krayon's template API.
Consumers should keep an explicit `std` dependency alongside `shim`; Kursal
currently requires that for the forwarded modules' type dependencies.

`shim::path` contains lexical filesystem path operations used by Krayon while
Kursal's `std` has no `path` module. Call sites can switch from `shim::path`
to `std::path` if the API is adopted. The forwarding list in `lib.kur` should
be kept in sync with Kursal's `std::lib` when the dependency is updated.

Proposed `std::path` operations:

- `join(left, right)`: insert `/` if needed; empty fragments are identities.
- `parent(path)`: return bytes before the last `/`, or empty if absent.
- `basename(path)`: return bytes after the last `/`, except when the parent is empty.

All return arena-backed `Span` values. They perform no filesystem I/O or
normalization. Their current edge behavior is documented in `path.kur`; a
stdlib version should settle absolute-right-hand-side and root semantics
before adoption. Krayon's existing call sites rely on the behavior here.

Other possible stdlib addition: recursive directory creation. Krayon still
implements this in `site` with its own error messages; extracting it would
need a generic `std::io::Error` API and a clear symlink policy.
