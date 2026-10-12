Write `to_roman(n: int) -> str` and `from_roman(s: str) -> int`.

- `to_roman` handles 1..3999 using standard subtractive notation (4 = IV, 9 = IX, 40 = XL, 90 = XC, 400 = CD, 900 = CM);
  raise `ValueError` outside that range.
- `from_roman` accepts only upper-case numerals in canonical form (exactly what `to_roman` would produce) and raises
  `ValueError` for anything else, e.g. `"IIII"`, `"IC"`, `"VX"`, `""`, `"iv"`.
