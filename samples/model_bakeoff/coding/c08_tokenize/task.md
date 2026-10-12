Write `tokenize(expr: str) -> list[str]` for arithmetic expressions.

Tokens are numbers (integers like `42` or decimals like `3.14`), the operators `+ - * / ^`, and the
parentheses `(` `)`. Whitespace separates nothing and is skipped. A minus sign is always its own token
(do not merge it into the number). Raise `ValueError` on any other character, or on a malformed number
such as `1.2.3` or `.`.
