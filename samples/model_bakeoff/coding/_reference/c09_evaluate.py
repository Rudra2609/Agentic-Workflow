import re
def evaluate(expr):
    toks = re.findall(r"\d+\.\d*|\.\d+|\d+|[-+*/()]|\S", expr)
    for t in toks:
        if not re.fullmatch(r"\d+\.\d*|\.\d+|\d+|[-+*/()]", t):
            raise ValueError(t)
    pos = 0
    def peek():
        return toks[pos] if pos < len(toks) else None
    def take():
        nonlocal pos
        t = peek()
        if t is None:
            raise ValueError("unexpected end")
        pos += 1
        return t
    def expr_():
        v = term()
        while peek() in ("+", "-"):
            op = take(); r = term()
            v = v + r if op == "+" else v - r
        return v
    def term():
        v = factor()
        while peek() in ("*", "/"):
            op = take(); r = factor()
            if op == "*":
                v = v * r
            else:
                if r == 0:
                    raise ZeroDivisionError("division by zero")
                v = v / r
        return v
    def factor():
        t = take()
        if t == "-":
            return -factor()
        if t == "+":
            return factor()
        if t == "(":
            v = expr_()
            if take() != ")":
                raise ValueError("expected )")
            return v
        if re.fullmatch(r"\d+\.\d*|\.\d+|\d+", t):
            return float(t)
        raise ValueError(t)
    v = expr_()
    if pos != len(toks):
        raise ValueError("trailing tokens")
    return v
