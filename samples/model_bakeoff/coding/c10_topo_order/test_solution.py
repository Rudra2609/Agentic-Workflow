import pytest
from solution import topo_order

def test_chain():
    assert topo_order({"test": ["code"], "code": ["design"], "design": []}) == ["design", "code", "test"]

def test_alphabetical_ties_and_implicit_nodes():
    assert topo_order({"d": ["b", "c"], "c": ["a"]}) == ["a", "b", "c", "d"]

def test_diamond():
    out = topo_order({"review": ["docs", "tests"], "docs": ["code"], "tests": ["code"], "code": []})
    assert out == ["code", "docs", "tests", "review"]

def test_cycles():
    with pytest.raises(ValueError):
        topo_order({"a": ["b"], "b": ["a"]})
    with pytest.raises(ValueError):
        topo_order({"a": ["a"]})

def test_empty():
    assert topo_order({}) == []
