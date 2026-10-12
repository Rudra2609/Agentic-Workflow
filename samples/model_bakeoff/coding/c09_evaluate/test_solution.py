import pathlib, re, pytest
from solution import evaluate

def test_precedence_and_assoc():
    assert evaluate("2 + 3 * 4") == 14
    assert evaluate("10 - 4 - 3") == 3
    assert evaluate("8 / 4 / 2") == 1
    assert evaluate("(2 + 3) * 4") == 20

def test_unary_and_decimals():
    assert evaluate("-(2 + 3)") == -5
    assert evaluate("2 * -3") == -6
    assert abs(evaluate("0.1 + 0.2") - 0.3) < 1e-9

def test_errors():
    with pytest.raises(ZeroDivisionError):
        evaluate("1 / (2 - 2)")
    for bad in ["", "2 +", "(1 + 2", "1 + 2)", "2 $ 3", "* 3"]:
        with pytest.raises(ValueError):
            evaluate(bad)

def test_no_eval_used():
    src = pathlib.Path(__file__).with_name("solution.py").read_text()
    assert not re.search(r"\b(eval|exec|compile)\s*\(", src)
    assert not re.search(r"^\s*(import ast|from ast import)", src, re.M)
