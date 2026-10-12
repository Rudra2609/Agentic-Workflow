Write `dict_diff(old: dict, new: dict) -> list[str]` that compares two (possibly nested) dicts.

- Report `"added: <path>"` for keys only in `new`, `"removed: <path>"` for keys only in `old`, and
  `"changed: <path>"` for keys in both whose values differ.
- When both values are dicts, compare recursively instead of reporting the parent as changed.
- `<path>` joins nested keys with dots, e.g. `db.port`. Keys are strings.
- Return the list sorted alphabetically.
