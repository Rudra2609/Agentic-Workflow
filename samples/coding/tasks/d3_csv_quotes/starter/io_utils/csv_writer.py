"""Write rows as CSV: fields with a comma or a quote are quoted, quotes doubled."""


def quote_field(field: str) -> str:
    if "," in field or '"' in field:
        return '"' + field.replace('"', '""') + '"'
    return field


def write_line(fields: list[str]) -> str:
    return ",".join(quote_field(f) for f in fields)
