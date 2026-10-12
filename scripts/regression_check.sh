#!/usr/bin/env bash
# Runs scripts/regression_check.py with uv's Python 3.11 (standard library only, no project install needed).
exec uv run --no-project --python 3.11 "$(dirname "$0")/regression_check.py" "$@"
