from solution import markdown_table

def test_basic():
    rows = [{"name": "ann", "age": 20}, {"name": "bob", "age": 31}]
    assert markdown_table(rows) == "| name | age |\n| --- | --- |\n| ann | 20 |\n| bob | 31 |"

def test_columns_missing_and_escape():
    rows = [{"a": "x|y"}, {"b": 2}]
    assert markdown_table(rows, ["a", "b"]) == "| a | b |\n| --- | --- |\n| x\\|y |  |\n|  | 2 |"

def test_empty():
    assert markdown_table([]) == ""
    assert markdown_table([], ["c"]) == "| c |\n| --- |"
