# API reference: todo_api

5 endpoint(s), read from the code (AST).

| Endpoint | Handler |
|---|---|
| GET /health | `app.py::health` |
| GET /todos | `app.py::list_all` |
| POST /todos | `app.py::create` |
| DELETE /todos/{todo_id} | `app.py::delete` |
| GET /todos/{todo_id} | `app.py::read` |

## `/health`

### GET /health

- Handler: `app.py::health`

## `/todos`

### GET /todos

- Handler: `app.py::list_all`

### POST /todos

- Handler: `app.py::create`
- Parameters: `todo: TodoIn`
- Request body: `TodoIn`

### DELETE /todos/{todo_id}

- Handler: `app.py::delete`
- Parameters: `todo_id: int`

### GET /todos/{todo_id}

- Handler: `app.py::read`
- Parameters: `todo_id: int`
