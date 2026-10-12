Write `parse_log_line(line: str) -> dict | None`.

Input is one line of an Apache "common log format" access log, for example:

    127.0.0.1 - - [10/Oct/2025:13:55:36 +0000] "GET /index.html HTTP/1.1" 200 2326

The fields are separated by single spaces. The 2nd and 3rd fields (client identity and user name) may be any
non-space text, often `-`. Return a dict with keys:
- `ip` (str), `timestamp` (str, the text inside the square brackets),
- `method`, `path`, `protocol` (str, the three parts of the quoted request),
- `status` (int), `size` (int; the log uses `-` for "no body", which must become 0).

Return `None` if the line does not match the format (do not raise).
