#!/usr/bin/env bash
# Cloud key-pool check: which team keys work and does every cloud route answer (no Ollama needed). See scripts/cloud_check.py.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
exec uv run --directory "$root/backend" --frozen python "$root/scripts/cloud_check.py"
