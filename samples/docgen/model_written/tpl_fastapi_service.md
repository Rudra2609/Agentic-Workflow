# Service – Simple FastAPI CRUD Example

## Table of Contents
- [Overview](#overview)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Running the Service](#running-the-service)
- [API Reference](#api-reference)
- [Configuration](#configuration)
- [Testing](#testing)
- [Project Structure](#project-structure)
- [License](#license)

## Overview
`service` is a minimal FastAPI application that demonstrates a health‑check endpoint and a tiny in‑memory CRUD resource for **items**. It is ideal for:

- Learning how to structure a FastAPI project.
- Using FastAPI’s automatic OpenAPI documentation.
- Running quick integration tests with `unittest` and `httpx`.

All data is stored in a Python dictionary, so the service is **stateless** between restarts and does **not** require a database.

## Features
- **Health endpoint** (`GET /health`) – returns service status.
- **Create item** (`POST /items`) – adds an item with an auto‑incremented integer ID.
- **Retrieve item** (`GET /items/{item_id}`) – fetches a stored item or returns 404.
- Automatic OpenAPI/Swagger UI at `/docs`.
- Fully typed with **Pydantic** models.
- Unit tests using FastAPI’s `TestClient`.

## Prerequisites
- Python **3.9+**
- `pip` (or your preferred Python package manager)

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/service.git
cd service

# 2. Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

If a `requirements.txt` file is not present, you can install the needed packages directly:

```bash
pip install fastapi uvicorn httpx
```

## Running the Service

```bash
# Using uvicorn (recommended)
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The service will be reachable at `http://localhost:8000`.  
OpenAPI docs are available at `http://localhost:8000/docs` and the ReDoc view at `http://localhost:8000/redoc`.

### Docker (optional)

A Dockerfile can be added later, but you can run the service quickly with:

```bash
docker run -p 8000:8000 python:3.11-slim bash -c "\
    pip install fastapi uvicorn && \
    uvicorn app.main:app --host 0.0.0.0 --port 8000"
```

## API Reference

### Health Check

| Method | Path   | Description                | Response                     |
|--------|--------|----------------------------|------------------------------|
| GET    | `/health` | Returns service health status | `{ "status": "ok" }` (200)   |

### Create Item

| Method | Path   | Request Body | Description                     | Response |
|--------|--------|--------------|---------------------------------|----------|
| POST   | `/items` | `{ "name": "string" }` | Creates a new item, assigns an auto‑incremented `id`. | `{ "id": int, "name": "string" }` (201) |

**Example**

```bash
curl -X POST http://localhost:8000/items \
     -H "Content-Type: application/json" \
     -d '{"name":"pen"}'
```

### Get Item

| Method | Path            | Description                     | Response |
|--------|-----------------|---------------------------------|----------|
| GET    | `/items/{id}`   | Retrieves the item with the given `id`. | `{ "id": int, "name": "string" }` (200) or 404 if not found |

**Example**

```bash
curl http://localhost:8000/items/1
```

## Configuration
The current implementation uses **in‑memory storage**, so there is no external configuration required. If you wish to extend the project (e.g., add a database), you can:

1. Add a `settings.py` using **pydantic.BaseSettings**.
2. Read environment variables for DB connection strings.
3. Replace the `_items` dictionary with a proper persistence layer.

## Testing

The test suite lives in the `tests/` directory and uses Python’s built‑in `unittest` framework together with FastAPI’s `TestClient`.

```bash
# Run tests
python -m unittest discover -s tests
```

### What the tests cover
- **Health endpoint** returns the expected JSON.
- **Create item** returns a new item with an `id`.
- **Get item** returns the correct name for an existing item.
- **Get non‑existent item** returns a 404 status.

## Project Structure

```
service/
├── app/
│   ├── __init__.py          # package marker
│   └── main.py              # FastAPI application
├── tests/
│   ├── __init__.py
│   └── test_main.py         # unit tests
├── requirements.txt         # (optional) pinned dependencies
└── README.md                # you are here
```

## License
This project is released under the MIT License – see the `LICENSE` file for details.