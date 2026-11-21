# Kursal standard library candidates

`shim` is an overlay on Kursal's standard library. Its root module forwards
the current `std` modules, and its own modules hold additions proposed for
the standard library. It is a staging area, not part of Krayon's template API.
Consumers should keep an explicit `std` dependency alongside `shim`; Kursal
currently requires that for the forwarded modules' type dependencies.

`shim::path` contains lexical filesystem path operations used by Krayon while
Kursal's `std` has no `path` module. `shim::fs` forwards the current
`std::fs` API and adds `create_dir_all`. Call sites can switch from `shim`
to `std` if these APIs are adopted. The forwarding lists in `lib.kur` and
`fs.kur` should be kept in sync with Kursal when the dependency is updated.

Proposed `std::path` operations:

- `join(left, right)`: insert `/` if needed; empty fragments are identities.
- `parent(path)`: return bytes before the last `/`, or empty if absent.
  `/` is its own parent and `/file` has parent `/`.
- `basename(path)`: return bytes after the last `/`, or the whole path if
  there is none. `/file` has basename `file`; `/` has an empty basename.

All return arena-backed `Span` values. They perform no filesystem I/O or
normalization. Their edge behavior is documented in `path.kur`. `join` retains
an absolute right-hand side rather than replacing the left-hand side; that
choice should be reviewed before adoption in Kursal.

`shim::fs::create_dir_all` accepts existing directories and follows existing
directory symlinks, matching `std::fs::metadata`. It reports the failing
component and whether checking, creating, or finding a non-directory caused
the failure. Krayon maps that error to its CLI messages. Filesystem changes
by another process can still race with each check.
