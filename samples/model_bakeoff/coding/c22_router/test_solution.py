import pytest
from solution import Router, NotFound, MethodNotAllowed

def h1(): pass
def h2(): pass
def h3(): pass

@pytest.fixture
def r():
    r = Router()
    r.add("GET", "/users/{id}", h1)
    r.add("GET", "/users/me", h2)
    r.add("POST", "/users/{id}/posts/{post_id}", h3)
    return r

def test_params(r):
    assert r.dispatch("GET", "/users/42") == (h1, {"id": "42"})
    assert r.dispatch("POST", "/users/7/posts/9") == (h3, {"id": "7", "post_id": "9"})

def test_static_wins_and_trailing_slash(r):
    assert r.dispatch("GET", "/users/me/") == (h2, {})

def test_errors(r):
    with pytest.raises(MethodNotAllowed):
        r.dispatch("DELETE", "/users/42")
    with pytest.raises(NotFound):
        r.dispatch("GET", "/users")
    with pytest.raises(NotFound):
        r.dispatch("GET", "/users/42/extra")
