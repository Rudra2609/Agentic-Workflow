# HTTP service (FastAPI)

```bash
uvicorn app.main:app --port 8000
python -m unittest discover -s tests -t .      # needs fastapi + httpx (make coding-venv)
```

Routes live in `app/main.py`; add models next to them and keep state behind small functions.
