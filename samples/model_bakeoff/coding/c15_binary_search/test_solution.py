import pathlib
from solution import insert_position, count_occurrences

def test_insert_position():
    xs = [1, 2, 2, 2, 5, 7]
    assert [insert_position(xs, v) for v in [0, 1, 2, 3, 5, 7, 8]] == [0, 0, 1, 4, 4, 5, 6]
    assert insert_position([], 3) == 0

def test_count():
    xs = [1, 2, 2, 2, 5, 7, 7]
    assert [count_occurrences(xs, v) for v in [2, 7, 1, 3, 9]] == [3, 2, 1, 0, 0]
    assert count_occurrences([], 1) == 0

def test_large():
    xs = [i // 3 for i in range(300000)]
    assert count_occurrences(xs, 50000) == 3
    assert insert_position(xs, 50000) == 150000

def test_no_bisect():
    assert "bisect" not in pathlib.Path(__file__).with_name("solution.py").read_text()
