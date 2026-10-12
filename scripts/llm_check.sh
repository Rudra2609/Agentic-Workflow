#!/usr/bin/env bash
# LLM gateway live + replay smoke test (needs Ollama running). See scripts/llm_check.py.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
export HMAP_ROLE_MAP="${HMAP_ROLE_MAP:-reasoner=qwen3.5:9b,coder=qwen3.5:9b,judge=qwen3.5:9b,fast=qwen3.5:9b,classify=qwen3.5:9b,embed=nomic-embed-text}"
exec uv run --directory "$root/backend" --frozen python "$root/scripts/llm_check.py"
