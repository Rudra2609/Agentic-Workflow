#!/usr/bin/env bash
# Checks the local toolchain for hmap (doc 00 §E). Exit code = number of required tools missing.
missing=0
ok()   { printf "  \033[32mOK\033[0m    %s\n" "$1"; }
warn() { printf "  \033[33mWARN\033[0m  %s\n" "$1"; }
bad()  { printf "  \033[31mMISS\033[0m  %s\n" "$1"; missing=$((missing+1)); }

echo "hmap doctor"
if command -v python3.11 >/dev/null || python3 -c 'import sys; sys.exit(sys.version_info[:2] != (3, 11))' 2>/dev/null; then
  ok "python 3.11"; else warn "python 3.11 not on PATH (uv will fetch it)"; fi
command -v uv   >/dev/null && ok "uv $(uv --version | awk '{print $2}')" || bad "uv (brew install uv)"
command -v node >/dev/null && ok "node $(node --version)" || bad "node 20 (brew install node@20)"
if command -v docker >/dev/null && docker info >/dev/null 2>&1; then ok "docker"; else warn "docker not running (needed from Phase B: brew install colima docker docker-compose)"; fi
if command -v ollama >/dev/null; then
  ok "ollama $(ollama --version 2>/dev/null | awk '{print $NF}' | tail -1)"
  url="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
  if curl -sf "$url/api/version" >/dev/null; then
    n=$(curl -s "$url/api/tags" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["models"]))')
    ok "ollama server at $url ($n models)"
  else warn "ollama server not reachable at $url (only needed for HMAP_LLM_MODE=live|record)"; fi
else warn "ollama not installed (only needed for live LLM runs)"; fi
command -v tesseract >/dev/null && ok "tesseract" || warn "tesseract (Sprint 2 local OCR of scans: brew install tesseract)"
exit $missing
