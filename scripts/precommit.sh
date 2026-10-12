#!/usr/bin/env bash
exec uv run --no-project --python 3.11 "$(dirname "$0")/precommit.py" "$@"
