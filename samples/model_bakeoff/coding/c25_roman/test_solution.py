import pytest
from solution import to_roman, from_roman

def test_to_roman():
    assert [to_roman(n) for n in [1, 4, 9, 14, 40, 90, 400, 1994, 3999]] == \
        ["I", "IV", "IX", "XIV", "XL", "XC", "CD", "MCMXCIV", "MMMCMXCIX"]

def test_roundtrip_all():
    for n in range(1, 4000):
        assert from_roman(to_roman(n)) == n

def test_invalid():
    for bad in [0, 4000, -1]:
        with pytest.raises(ValueError):
            to_roman(bad)
    for bad in ["IIII", "IC", "VX", "", "iv", "MMMM", "IIV", "ABC"]:
        with pytest.raises(ValueError):
            from_roman(bad)
