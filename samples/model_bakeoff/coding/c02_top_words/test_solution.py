from solution import top_words

def test_basic_order():
    assert top_words("b a b c a b", 2) == [("b", 3), ("a", 2)]

def test_ties_alphabetical():
    assert top_words("dog cat ant", 3) == [("ant", 1), ("cat", 1), ("dog", 1)]

def test_case_and_punctuation():
    assert top_words("Hello, hello! HELLO? world.", 5) == [("hello", 3), ("world", 1)]

def test_apostrophe_splits():
    assert top_words("Don't don", 1) == [("don", 2)]

def test_k_edge_cases():
    assert top_words("a a b", 0) == []
    assert top_words("", 3) == []
    assert top_words("x y", 10) == [("x", 1), ("y", 1)]
