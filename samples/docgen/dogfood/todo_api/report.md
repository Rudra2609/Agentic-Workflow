# Project report

## Overview

The `todo_api` repository is a Python application that implements a REST API for managing to-do items using `fastapi` and `uvicorn`. The application's five HTTP endpoints are defined in `app.py`, while data persistence is managed by an SQLite database layer in `storage.py`. Data validation across the system uses `pydantic`. Furthermore, the repository includes a test suite in one test file that leverages `pytest` and `httpx` to ensure the API functions correctly.

## Design

| Component | Modules | What it is |
|---|---|---|
| `app.py` | 1 | To-do REST API. |
| `storage.py` | 1 | SQLite storage for to-do items. |

## Implementation

- `storage.py`: SQLite storage for to-do items.
- `app.py`: To-do REST API.

## Testing

1 test file(s) with 1 test functions.

```bash
pytest
```

## How to run

```bash
pip install -e ".[dev]"
python app.py
```
