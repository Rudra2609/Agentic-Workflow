import pytest
from solution import tokenize

def test_basic():
    assert tokenize("3 + 4*2") == ["3", "+", "4", "*", "2"]

def test_decimals_parens_power():
    assert tokenize("(1.5+2)^2") == ["(", "1.5", "+", "2", ")", "^", "2"]

def test_unary_minus_separate():
    assert tokenize("-3 - -4") == ["-", "3", "-", "-", "4"]

def test_errors():
    for bad in ["2 $ 3", "1.2.3", "a+1", "."]:
        with pytest.raises(ValueError):
            tokenize(bad)
