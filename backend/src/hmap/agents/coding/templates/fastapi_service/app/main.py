"""HTTP service skeleton: a health route and a small in-memory CRUD resource.

    uvicorn app.main:app --port 8000
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="service")


class ItemIn(BaseModel):
    name: str


class Item(ItemIn):
    id: int


_items: dict[int, Item] = {}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/items", status_code=201)
def create_item(body: ItemIn) -> Item:
    item = Item(id=len(_items) + 1, name=body.name)
    _items[item.id] = item
    return item


@app.get("/items/{item_id}")
def get_item(item_id: int) -> Item:
    if item_id not in _items:
        raise HTTPException(status_code=404, detail="item not found")
    return _items[item_id]
