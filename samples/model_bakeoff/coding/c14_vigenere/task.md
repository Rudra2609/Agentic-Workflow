Write `vigenere_encrypt(text: str, key: str) -> str` and `vigenere_decrypt(text: str, key: str) -> str`.

- Shift each ASCII letter of `text` by the alphabet position of the current key letter (a/A = 0, b/B = 1, ...),
  wrapping around and keeping the letter's case.
- Non-letters are copied unchanged and do **not** advance the key position.
- The key is case-insensitive and is repeated as needed. Raise `ValueError` if the key is empty or contains a non-letter.
