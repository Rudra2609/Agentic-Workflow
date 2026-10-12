import re
_RE = re.compile(r'^(\S+) \S+ \S+ \[([^\]]+)\] "(\S+) (\S+) (\S+)" (\d{3}) (\d+|-)$')
def parse_log_line(line):
    m = _RE.match(line.strip())
    if not m:
        return None
    ip, ts, method, path, proto, status, size = m.groups()
    return {"ip": ip, "timestamp": ts, "method": method, "path": path, "protocol": proto,
            "status": int(status), "size": 0 if size == "-" else int(size)}
