from solution import validate

S = {"name": str, "age": int, "score": float}

def test_valid():
    assert validate({"name": "a", "age": 3, "score": 1.5}, S) == []

def test_errors_sorted():
    assert validate({"name": 5, "extra1": 1}, S) == ["extra: extra1", "missing: age", "missing: score", "type: name"]

def test_bool_is_not_int_and_int_not_float():
    assert validate({"name": "a", "age": True, "score": 2}, S) == ["type: age", "type: score"]
