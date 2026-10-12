def tokenize(expr):
    out, i = [], 0
    while i < len(expr):
        c = expr[i]
        if c.isspace():
            i += 1
        elif c in "+-*/^()":
            out.append(c); i += 1
        elif c.isdigit() or c == ".":
            j = i
            while j < len(expr) and (expr[j].isdigit() or expr[j] == "."):
                j += 1
            num = expr[i:j]
            if num.count(".") > 1 or num == ".":
                raise ValueError(num)
            out.append(num); i = j
        else:
            raise ValueError(c)
    return out
