# Todo API

A small REST API for a to-do list, built with FastAPI and stored in SQLite (Python 3.11 or newer).

## Run
```bash
pip install -e ".[dev]"
python app.py
```
The API listens on port 8000 (`TODO_PORT` changes it); the database file is set by `TODO_DB_PATH` (default
`todos.db`). You can also start it with `uvicorn app:app`.

## Endpoints
| Method | Path | What it does |
|---|---|---|
| GET /health | | liveness check |
| GET /todos | | list every item |
| POST /todos | | create an item from `{"title": ...}` (`TodoIn`) |
| GET /todos/{todo_id} | | one item, 404 if missing |
| DELETE /todos/{todo_id} | | delete an item, 404 if missing |

## Code
`app.py` defines the routes; `storage.py` holds the SQL (`add_todo()`, `list_todos()`, `get_todo()`,
`delete_todo()`). The service does not need Docker or a database server.

## Tests
```bash
pytest
```
