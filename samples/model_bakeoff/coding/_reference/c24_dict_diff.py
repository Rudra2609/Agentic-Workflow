def dict_diff(old, new, prefix=""):
    out = []
    for k in set(old) | set(new):
        p = f"{prefix}{k}"
        if k not in new:
            out.append(f"removed: {p}")
        elif k not in old:
            out.append(f"added: {p}")
        elif isinstance(old[k], dict) and isinstance(new[k], dict):
            out.extend(dict_diff(old[k], new[k], p + "."))
        elif old[k] != new[k]:
            out.append(f"changed: {p}")
    return sorted(out)
