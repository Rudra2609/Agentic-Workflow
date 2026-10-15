import stats


def test_summarize_numeric_only():
    rows = [{"name": "a", "score": "1"}, {"name": "b", "score": "3"}]
    assert stats.summarize(rows) == {"score": {"min": 1.0, "max": 3.0, "mean": 2.0, "median": 2.0}}
