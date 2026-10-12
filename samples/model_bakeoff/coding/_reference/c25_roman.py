_VALS = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
         (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
def to_roman(n):
    if not isinstance(n, int) or not 1 <= n <= 3999:
        raise ValueError(n)
    out = []
    for v, s in _VALS:
        while n >= v:
            out.append(s); n -= v
    return "".join(out)
def from_roman(s):
    if not s or any(c not in "MDCLXVI" for c in s):
        raise ValueError(s)
    i, n = 0, 0
    for v, sym in _VALS:
        while s.startswith(sym, i):
            n += v; i += len(sym)
    if i != len(s) or not 1 <= n <= 3999 or to_roman(n) != s:
        raise ValueError(s)
    return n
