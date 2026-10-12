def validate(data, schema):
    errs = []
    for f, t in schema.items():
        if f not in data:
            errs.append(f"missing: {f}")
            continue
        v = data[f]
        ok = isinstance(v, t) and not (t in (int, float) and isinstance(v, bool)) and not (t is float and type(v) is int)
        if not ok:
            errs.append(f"type: {f}")
    for f in data:
        if f not in schema:
            errs.append(f"extra: {f}")
    return sorted(errs)
