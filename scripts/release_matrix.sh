#!/usr/bin/env bash
# Final release gate, regression matrix (Sprint 11 item 11.19): see scripts/release_matrix.py.
exec python3 "$(dirname "$0")/release_matrix.py" "$@"
