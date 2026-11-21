# Proposed Kursal filesystem path and directory APIs

Krayon repeatedly needed two operations that Kursal's `std` does not yet
provide: lexical path composition and recursive directory creation. The
implementations live in [`path.kur`](path.kur) and [`fs.kur`](fs.kur), with
behavior checks in `tests/shim`. This proposal describes moving them to
`std::path` and `std::fs` without coupling Kursal to static sites.

## `std::path`

Add `join`, `parent`, and `basename` with the signatures in `shim::path`.
They accept and return `Span` values under the caller's arena domain. They
inspect bytes only, use `/` as the separator, and do not consult the
filesystem, canonicalize, or resolve `.` and `..`.

| Call | Result |
| --- | --- |
| `join("a", "b")` | `"a/b"` |
| `join("a/", "b")` | `"a/b"` |
| `join("a", "/b")` | `"/b"` |
| `join("a", "")` | `"a"` |
| `join("", "b")` | `"b"` |
| `parent("a/b")` | `"a"` |
| `parent("file")` | `""` |
| `parent("/file")` | `"/"` |
| `parent("/")` | `"/"` |
| `basename("a/b")` | `"b"` |
| `basename("/file")` | `"file"` |
| `basename("dir/")` | `""` |
| `basename("/")` | `""` |

An absolute right-hand side replaces the left path because it already
identifies a location from the root. Relative fragments append. This rule
is the only behavior change from Krayon's original local `join`; its call
sites pass relative right-hand fragments. Repeated separators remain as
provided, except at the join boundary. The API handles Unix-style paths;
platform-specific path rules would need a separate design.

## `std::fs::create_dir_all`

Add the `create_dir_all` function and `CreateDirError` types from
`shim::fs`. The function creates missing components in order, accepts
existing directories, and returns `Result[(), CreateDirError['k]]`.
The error holds the component path and one of:

- `NotDirectory`: an existing component is a file or a symlink to a file.
- `Stat(Error)`: checking a component failed.
- `Create(Error)`: creating a missing component failed.

The function accepts an empty path as a no-op, follows existing symlinks to
directories as `std::fs::metadata` does, and rechecks a component if `mkdir`
reports `AlreadyExists` after an earlier `NotFound` observation. It does not
promise atomicity or prevent another process from changing a component
between operations. Callers that need to forbid symlink traversal must
validate their paths separately. Krayon retains its own CLI error wording
by mapping the structured error at the call site.

## Adoption

The shim imports Kursal's existing `std::fs` API internally and adds this one
function. If accepted, Kursal can move `path.kur` to `std/path.kur`, add
`create_dir_all` and its error types to `std/fs.kur`, and migrate the shim
checks into its standard library tests. Krayon can then import `std::path`
and `std::fs` directly and remove `lib/shim`.

Before adoption, Kursal maintainers should decide whether the lexical path
API belongs under `std::path` and whether the structured directory error
fits existing `std::io::Error` conventions. The behavior table and symlink
policy above are the proposed contract for that review.
