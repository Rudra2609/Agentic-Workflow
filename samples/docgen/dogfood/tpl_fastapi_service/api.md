# API reference: tpl_fastapi_service

3 endpoint(s), read from the app's OpenAPI document.

| Endpoint | Handler |
|---|---|
| GET /health | `app/main.py::health` |
| POST /items | `app/main.py::create_item` |
| GET /items/{item_id} | `app/main.py::get_item` |

## `/health`

### GET /health

Health

- Handler: `app/main.py::health`

## `/items`

### POST /items

Create Item

- Handler: `app/main.py::create_item`
- Request body: `ItemIn`
- Response: `Item`

### GET /items/{item_id}

Get Item

- Handler: `app/main.py::get_item`
- Parameters: item_id: integer (path)
- Response: `Item`
