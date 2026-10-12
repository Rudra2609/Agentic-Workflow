Write `markdown_table(rows: list[dict], columns: list[str] | None = None) -> str`.

- Columns default to the keys of the first row, in order. With no rows and no columns, return `""`.
- Output: a header line, a separator line, then one line per row, joined with `\n` (no trailing newline):

      | name | age |
      | --- | --- |
      | ann | 20 |

- Values are converted with `str()`. A missing key gives an empty cell, i.e. two spaces between the pipes: `|  |`.
- A `|` inside a value must be escaped as `\|`.
