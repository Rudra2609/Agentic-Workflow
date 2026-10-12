#!/usr/bin/env bash
# Runs scripts/ownership_check.py with uv's Python 3.11 (standard library only, no project install needed).
exec uv run --no-project --python 3.11 "$(dirname "$0")/ownership_check.py" "$@"
