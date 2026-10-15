"""SQLite storage for to-do items."""

import os
import sqlite3

DB_PATH = os.getenv("TODO_DB_PATH", "todos.db")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS todos (id INTEGER PRIMARY KEY, title TEXT NOT NULL, done INTEGER DEFAULT 0)")
    return conn


def add_todo(title: str) -> int:
    with connect() as conn:
        return conn.execute("INSERT INTO todos (title) VALUES (?)", (title,)).lastrowid


def list_todos() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT id, title, done FROM todos ORDER BY id").fetchall()
    return [{"id": r[0], "title": r[1], "done": bool(r[2])} for r in rows]


def get_todo(todo_id: int) -> dict | None:
    return next((t for t in list_todos() if t["id"] == todo_id), None)


def delete_todo(todo_id: int) -> bool:
    with connect() as conn:
        return conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,)).rowcount > 0
