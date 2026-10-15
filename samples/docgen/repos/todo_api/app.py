"""To-do REST API."""

import os

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import storage

app = FastAPI(title="Todo API")


class TodoIn(BaseModel):
    title: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/todos")
def list_all() -> list[dict]:
    return storage.list_todos()


@app.post("/todos", status_code=201)
def create(todo: TodoIn) -> dict:
    return {"id": storage.add_todo(todo.title), "title": todo.title, "done": False}


@app.get("/todos/{todo_id}")
def read(todo_id: int) -> dict:
    todo = storage.get_todo(todo_id)
    if todo is None:
        raise HTTPException(404, "not found")
    return todo


@app.delete("/todos/{todo_id}", status_code=204)
def delete(todo_id: int) -> None:
    if not storage.delete_todo(todo_id):
        raise HTTPException(404, "not found")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("TODO_PORT", "8000")))
