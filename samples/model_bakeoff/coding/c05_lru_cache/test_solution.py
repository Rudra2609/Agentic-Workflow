import pytest
from solution import LRUCache

def test_eviction_order():
    c = LRUCache(2)
    c.put(1, "a"); c.put(2, "b")
    assert c.get(1) == "a"
    c.put(3, "c")
    assert c.get(2) == -1
    assert c.get(1) == "a" and c.get(3) == "c"

def test_update_refreshes():
    c = LRUCache(2)
    c.put("x", 1); c.put("y", 2); c.put("x", 10); c.put("z", 3)
    assert c.get("y") == -1 and c.get("x") == 10 and c.get("z") == 3

def test_capacity_one_and_invalid():
    c = LRUCache(1)
    c.put(1, 1); c.put(2, 2)
    assert c.get(1) == -1 and c.get(2) == 2
    with pytest.raises(ValueError):
        LRUCache(0)
