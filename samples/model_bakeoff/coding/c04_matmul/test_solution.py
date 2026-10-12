import pytest
from solution import matmul

def test_2x2():
    assert matmul([[1, 2], [3, 4]], [[5, 6], [7, 8]]) == [[19, 22], [43, 50]]

def test_rectangular():
    assert matmul([[1, 2, 3]], [[1], [2], [3]]) == [[14]]
    assert matmul([[1], [2]], [[3, 4]]) == [[3, 4], [6, 8]]

def test_errors():
    for a, b in [([], [[1]]), ([[1]], []), ([[1, 2], [3]], [[1], [1]]), ([[1, 2]], [[1, 2]]), ([[]], [[1]])]:
        with pytest.raises(ValueError):
            matmul(a, b)
