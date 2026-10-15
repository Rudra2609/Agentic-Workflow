import storage


def test_add_and_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "t.db"))
    todo_id = storage.add_todo("write docs")
    assert storage.get_todo(todo_id)["title"] == "write docs"
    assert storage.delete_todo(todo_id)
