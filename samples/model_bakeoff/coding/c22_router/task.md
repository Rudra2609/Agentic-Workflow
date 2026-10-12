Write a tiny URL router with exception classes `NotFound(Exception)` and `MethodNotAllowed(Exception)`.

- `Router()`; `add(method: str, pattern: str, handler)` registers a route. Patterns look like `/users/{id}/posts`;
  a `{name}` segment matches exactly one non-empty path segment.
- `dispatch(method: str, path: str) -> tuple[handler, dict[str, str]]` returns the handler and the captured parameters.
  Paths and patterns must have the same number of segments. A trailing slash is ignored (`/users/` == `/users`).
- When both a static route and a parameter route match a path (e.g. `/users/me` and `/users/{id}`), the static one wins.
- Raise `MethodNotAllowed` if some route matches the path but not the method, and `NotFound` if no route matches the path.
