from solution import column_means

def test_numeric_and_text():
    text = "name,age,score\nann,20,1.5\nbob,30,2.5\n"
    assert column_means(text) == {"age": 25.0, "score": 2.0}

def test_empty_cells_ignored():
    text = "a,b\n1,\n3,\n,\n"
    assert column_means(text) == {"a": 2.0}

def test_mixed_column_skipped():
    text = "x,y\n1,2\nn/a,4\n"
    assert column_means(text) == {"y": 3.0}

def test_quoted_fields():
    text = 'city,temp\n"Ahmedabad, IN",30\n"Pune, IN",20\n'
    assert column_means(text) == {"temp": 25.0}
