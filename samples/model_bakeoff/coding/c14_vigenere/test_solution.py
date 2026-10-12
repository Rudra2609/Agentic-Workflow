import pytest
from solution import vigenere_encrypt, vigenere_decrypt

def test_classic():
    assert vigenere_encrypt("ATTACKATDAWN", "LEMON") == "LXFOPVEFRNHR"

def test_case_and_punctuation():
    assert vigenere_encrypt("Hello, World!", "key") == "Rijvs, Uyvjn!"

def test_roundtrip():
    msg = "Meet me at 10:30, near Gate-2."
    assert vigenere_decrypt(vigenere_encrypt(msg, "Secret"), "sEcReT") == msg

def test_bad_key():
    for k in ["", "ab1", "a b"]:
        with pytest.raises(ValueError):
            vigenere_encrypt("x", k)
