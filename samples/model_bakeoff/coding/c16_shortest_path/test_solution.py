import math
from solution import shortest_path

G = {"A": {"B": 1, "C": 4}, "B": {"C": 2, "D": 5}, "C": {"D": 1}, "D": {}}

def test_basic():
    assert shortest_path(G, "A", "D") == (4, ["A", "B", "C", "D"])

def test_same_node_and_unreachable():
    assert shortest_path(G, "C", "C") == (0, ["C"])
    cost, path = shortest_path(G, "D", "A")
    assert math.isinf(cost) and path == []
    cost, path = shortest_path(G, "A", "Z")
    assert math.isinf(cost) and path == []

def test_target_only_node():
    g = {"s": {"t": 2.5}}
    assert shortest_path(g, "s", "t") == (2.5, ["s", "t"])

def test_prefers_cheaper_longer_path():
    g = {"a": {"b": 10, "c": 1}, "c": {"d": 1}, "d": {"b": 1}}
    assert shortest_path(g, "a", "b") == (3, ["a", "c", "d", "b"])
