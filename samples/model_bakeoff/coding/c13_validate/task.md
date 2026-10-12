Write `validate(data: dict, schema: dict[str, type]) -> list[str]`.

`schema` maps each required field name to its expected Python type (e.g. `{"name": str, "age": int}`).
Return a sorted list of error strings:
- `"missing: <field>"` for a schema field not in `data`,
- `"type: <field>"` when the value is not an instance of the expected type — note that `bool` must **not**
  count as `int` (and `int` must not count as `float`),
- `"extra: <field>"` for keys in `data` that are not in `schema`.
Return `[]` when the data is valid.
