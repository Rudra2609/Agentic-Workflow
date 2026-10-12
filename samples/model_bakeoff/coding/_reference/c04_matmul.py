def _check(m):
    if not m or any(not r for r in m) or len({len(r) for r in m}) != 1:
        raise ValueError("bad matrix")
def matmul(a, b):
    _check(a); _check(b)
    if len(a[0]) != len(b):
        raise ValueError("dimension mismatch")
    return [[sum(a[i][k] * b[k][j] for k in range(len(b))) for j in range(len(b[0]))] for i in range(len(a))]
