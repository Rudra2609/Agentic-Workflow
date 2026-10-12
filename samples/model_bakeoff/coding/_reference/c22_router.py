class NotFound(Exception):
    pass
class MethodNotAllowed(Exception):
    pass
def _segs(p):
    return [s for s in p.strip("/").split("/") if s != ""]
class Router:
    def __init__(self):
        self.routes = []
    def add(self, method, pattern, handler):
        self.routes.append((method.upper(), _segs(pattern), handler))
    def _match(self, pat, segs):
        if len(pat) != len(segs):
            return None
        params = {}
        for p, s in zip(pat, segs):
            if p.startswith("{") and p.endswith("}"):
                params[p[1:-1]] = s
            elif p != s:
                return None
        return params
    def dispatch(self, method, path):
        segs = _segs(path)
        matches = []
        for m, pat, h in self.routes:
            params = self._match(pat, segs)
            if params is not None:
                matches.append((len(params), m, h, params))
        if not matches:
            raise NotFound(path)
        allowed = sorted([x for x in matches if x[1] == method.upper()], key=lambda x: x[0])
        if not allowed:
            raise MethodNotAllowed(method)
        _, _, h, params = allowed[0]
        return (h, params)
