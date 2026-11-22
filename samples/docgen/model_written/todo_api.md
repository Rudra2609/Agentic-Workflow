# Todo API

A tiny **RESTful** to‑do list service built with **FastAPI** and **SQLite**.  
It demonstrates a clean separation between the HTTP layer (`app.py`) and the persistence layer (`storage.py`), includes health‑check endpoint, and ships with a minimal test suite.

---

## Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Running the API](#running-the-api)
- [Configuration](#configuration)
- [API Endpoints](#api-endpoints)
- [Testing](#testing)
- [Project Structure](#project-structure)
- [License](#license)

---

## Features

- **CRUD** operations for to‑do items (Create, Read, List, Delete)
- SQLite‑backed storage (no external DB required)
- Health‑check endpoint (`/health`)
- Automatic table creation on first run
- Typed request/response models with **Pydantic**
- Fully typed with Python 3.11+
- Simple, zero‑dependency test suite using **pytest** and **httpx**

---

## Prerequisites

- Python **3.11** or newer
- `pip` (or your favourite Python package manager)

---

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/todo-api.git
cd todo-api

# Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate

# Install the package and its runtime dependencies
pip install .
```

*Optional*: Install development dependencies (testing, linting, etc.):

```bash
pip install .[dev]
```

---

## Running the API

```bash
# Default: binds to 127.0.0.1:8000
python app.py
```

Or, using **uvicorn** directly (useful for hot‑reloading in development):

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

The service will be reachable at `http://127.0.0.1:8000`.

---

## Configuration

| Environment Variable | Default | Description |
|----------------------|---------|-------------|
| `TODO_PORT`          | `8000`  | Port on which the API server listens (used by `app.py`). |
| `TODO_DB_PATH`       | `todos.db` | File path for the SQLite database (used by `storage.py`). |

You can set them in your shell before launching the app, e.g.:

```bash
export TODO_PORT=8080
export TODO_DB_PATH=/var/data/todos.db
python app.py
```

---

## API Endpoints

All responses are JSON. Errors are returned with appropriate HTTP status codes.

| Method | Path | Description | Request Body | Response |
|--------|------|-------------|--------------|----------|
| `GET` | `/health` | Simple health check. | – | `{ "status": "ok" }` |
| `GET` | `/todos` | List **all** to‑do items. | – | `[{ "id": 1, "title": "...", "done": false }, …]` |
| `POST` | `/todos` | Create a new to‑do. | `{ "title": "Buy milk" }` | `{ "id": 2, "title": "Buy milk", "done": false }` (201) |
| `GET` | `/todos/{todo_id}` | Retrieve a single item. | – | `{ "id": 2, "title": "...", "done": false }` (404 if not found) |
| `DELETE` | `/todos/{todo_id}` | Delete an item. | – | *No content* (204) (404 if not found) |

### Example with `curl`

```bash
# Create a todo
curl -X POST -H "Content-Type: application/json" \
     -d '{"title":"Write README"}' http://localhost:8000/todos

# List todos
curl http://localhost:8000/todos

# Get a specific todo
curl http://localhost:8000/todos/1

# Delete a todo
curl -X DELETE http://localhost:8000/todos/1
```

---

## Testing

The project includes unit tests for the storage layer.

```bash
# Run the test suite
pytest
```

The test `tests/test_storage.py` uses a temporary SQLite file (via `tmp_path`) and monkey‑patches `storage.DB_PATH` to avoid contaminating your real database.

---

## Project Structure

```
todo-api/
├─ app.py               # FastAPI application & route definitions
├─ storage.py           # SQLite helper functions
├─ pyproject.toml       # Build metadata & dependencies
├─ tests/
│   └─ test_storage.py # Storage unit tests
└─ README.md            # ← you are here
```

---

## License

This project is licensed under the **MIT License** – see the `LICENSE` file for details.