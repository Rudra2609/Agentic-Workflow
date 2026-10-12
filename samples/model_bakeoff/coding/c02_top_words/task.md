Write `top_words(text: str, k: int) -> list[tuple[str, int]]`.

- A word is a maximal run of ASCII letters `a`-`z` after lower-casing the text (so "Don't" gives "don" and "t").
- Return the `k` most frequent words as `(word, count)` pairs, sorted by count descending, then word ascending.
- If there are fewer than `k` distinct words, return all of them. `k <= 0` returns `[]`.
