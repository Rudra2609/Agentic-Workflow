Write `evaluate(expr: str) -> float` that evaluates an arithmetic expression **without** using
Python's `eval`, `exec`, `compile` or the `ast` module (write a small parser yourself).

Support numbers (integers and decimals), `+ - * /`, parentheses and unary minus (e.g. `-(2+3)`, `2*-3`).
`*` and `/` bind tighter than `+` and `-`; operators of equal precedence are left-associative.
Raise `ZeroDivisionError` when dividing by zero and `ValueError` for malformed input
(unknown characters, unbalanced parentheses, missing operands, empty string).
