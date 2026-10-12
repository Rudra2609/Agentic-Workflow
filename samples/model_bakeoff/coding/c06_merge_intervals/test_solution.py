from solution import merge_intervals

def test_basic():
    assert merge_intervals([(1, 3), (2, 6), (8, 10), (15, 18)]) == [(1, 6), (8, 10), (15, 18)]

def test_touching_and_unsorted():
    assert merge_intervals([(5, 6), (1, 2), (2, 3)]) == [(1, 3), (5, 6)]

def test_contained_and_empty():
    assert merge_intervals([(1, 10), (2, 3), (4, 5)]) == [(1, 10)]
    assert merge_intervals([]) == []

def test_input_not_modified():
    data = [(3, 4), (1, 2)]
    merge_intervals(data)
    assert data == [(3, 4), (1, 2)]
