#!/usr/bin/env bash
# Seed a running API with a demo project waiting for approval. See scripts/seed.py.
exec uv run --no-project --python 3.11 "$(dirname "$0")/seed.py" "$@"
