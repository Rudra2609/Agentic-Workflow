import csv, io
def column_means(csv_text):
    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows:
        return {}
    header, data = rows[0], rows[1:]
    out = {}
    for i, name in enumerate(header):
        vals = [r[i] for r in data if i < len(r) and r[i].strip() != ""]
        if not vals:
            continue
        try:
            nums = [float(v) for v in vals]
        except ValueError:
            continue
        out[name] = sum(nums) / len(nums)
    return out
