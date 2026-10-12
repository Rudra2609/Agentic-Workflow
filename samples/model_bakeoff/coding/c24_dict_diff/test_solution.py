from solution import dict_diff

def test_flat():
    assert dict_diff({"a": 1, "b": 2}, {"b": 3, "c": 4}) == ["added: c", "changed: b", "removed: a"]

def test_nested():
    old = {"db": {"host": "x", "port": 5432}, "debug": False}
    new = {"db": {"host": "x", "port": 6543, "user": "u"}, "debug": False}
    assert dict_diff(old, new) == ["added: db.user", "changed: db.port"]

def test_dict_replaced_by_value():
    assert dict_diff({"a": {"b": 1}}, {"a": 5}) == ["changed: a"]

def test_equal():
    assert dict_diff({"x": {"y": [1, 2]}}, {"x": {"y": [1, 2]}}) == []
