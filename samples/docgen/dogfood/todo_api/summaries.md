# Code summaries: todo_api

The `todo_api` repository is a Python application that implements a REST API for managing to-do items using `fastapi` and `uvicorn`. The application's five HTTP endpoints are defined in `app.py`, while data persistence is managed by an SQLite database layer in `storage.py`. Data validation across the system uses `pydantic`. Furthermore, the repository includes a test suite in one test file that leverages `pytest` and `httpx` to ensure the API functions correctly.

Public functions and classes: 11; described: 100 % (from docstrings or the model; the rest show their signature).

## `app.py`

“To-do REST API.”

- `app.py::TodoIn`: Defines a Pydantic model with a single string field 'title'.
- `app.py::health`: Returns a JSON object indicating the service status is 'ok'.
- `app.py::list_all`: Returns a list of all todo items from storage.
- `app.py::create`: Adds a new todo with the given title and returns its id, title, and done status.
- `app.py::read`: Retrieves a todo by id, raising 404 if not found.
- `app.py::delete`: Deletes a todo by id, raising 404 if not found.

## `storage.py`

“SQLite storage for to-do items.”

- `storage.py::connect`: Creates a SQLite connection and ensures the todos table exists.
- `storage.py::add_todo`: Inserts a new todo title and returns its auto-generated ID.
- `storage.py::list_todos`: Retrieves all todos as dictionaries with id, title, and done status.
- `storage.py::get_todo`: Returns the todo dictionary matching the given ID, or None if not found.
- `storage.py::delete_todo`: Deletes the todo with the specified ID and returns true if a row was removed.
