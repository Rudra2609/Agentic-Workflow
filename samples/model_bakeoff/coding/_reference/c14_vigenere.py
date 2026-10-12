def _shifts(key):
    if not key or not all("a" <= c.lower() <= "z" for c in key):
        raise ValueError("key")
    return [ord(c.lower()) - 97 for c in key]
def _run(text, key, sign):
    ks, out, i = _shifts(key), [], 0
    for ch in text:
        if "a" <= ch <= "z" or "A" <= ch <= "Z":
            base = 65 if ch.isupper() else 97
            out.append(chr((ord(ch) - base + sign * ks[i % len(ks)]) % 26 + base))
            i += 1
        else:
            out.append(ch)
    return "".join(out)
def vigenere_encrypt(text, key):
    return _run(text, key, 1)
def vigenere_decrypt(text, key):
    return _run(text, key, -1)
