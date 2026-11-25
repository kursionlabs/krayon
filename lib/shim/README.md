# Kursal standard library candidates

`shim` is an overlay on Kursal's standard library. It contains only additions
proposed for `std`; existing APIs remain in the adjacent Kursal `std` package.
It is a staging area, not part of Krayon's template API. Consumers should
import existing APIs from `std` and these additions from `shim`.

`shim::path` contains lexical filesystem path operations used by Krayon while
Kursal's `std` has no `path` module. `shim::fs` adds `create_dir_all` without
re-exporting `std::fs`. Call sites can switch from `shim` to `std` if these
APIs are adopted.

Proposed `std::path` operations:

- `join(left, right)`: an absolute `right` replaces `left`; otherwise insert
  `/` if needed. Empty fragments are identities.
- `parent(path)`: return bytes before the last `/`, or empty if absent.
  `/` is its own parent and `/file` has parent `/`.
- `basename(path)`: return bytes after the last `/`, or the whole path if
  there is none. `/file` has basename `file`; `/` has an empty basename.

All return arena-backed `Str` values. They perform no filesystem I/O or
normalization. Their edge behavior is documented in `path.kur`. See
[`STDLIB_PROPOSAL.md`](STDLIB_PROPOSAL.md) for the proposed Kursal API and
the remaining design questions.

`shim::fs::create_dir_all` accepts existing directories and follows existing
directory symlinks, matching `std::fs::metadata`. It reports the failing
component and whether checking, creating, or finding a non-directory caused
the failure. Krayon maps that error to its CLI messages. Filesystem changes
by another process can still race with each check.
