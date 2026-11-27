#!/usr/bin/env bash
# Storage-aware model tiers (Sprint 11 item 11.16, doc 02 §2.2b): pull only what this laptop needs.
#   scripts/pull_models.sh --tier 0      nothing (replay / fake: recorded answers in samples/llm_cache/)
#   scripts/pull_models.sh --tier lite   qwen3.5:4b + nomic-embed-text            (~3.6 GB)
#   scripts/pull_models.sh --tier 1      qwen3.5:9b + nomic-embed-text            (~6.9 GB, the demo laptop)
#   scripts/pull_models.sh --tier 2      tier 1 + qwen3.5:4b                       (~10 GB, benchmarks / model host)
# Models go to OLLAMA_MODELS (default /Volumes/Tirth_SSD/ollama, the external disk). Prints the HMAP_ROLE_MAP line
# for the tier (role aliasing): paste it into .env yourself; this script never edits .env.
#   --check      only report what is pulled, pull nothing
#   --model-host URL   model-host mode: check the models on another machine on the LAN (docs/members/11/sizing.md); then set
#                OLLAMA_BASE_URL=URL in .env and pull nothing here
set -uo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
tier=""; check=0; host=""
while [ $# -gt 0 ]; do
  case "$1" in
    --tier) tier="${2:-}"; shift 2 ;;
    --check) check=1; shift ;;
    --model-host) host="${2:-}"; shift 2 ;;
    *) echo "usage: $0 --tier 0|lite|1|2 [--check] [--model-host http://<machine>:11434]"; exit 2 ;;
  esac
done
case "$tier" in
  0) models=() ; chat="" ;;
  lite) models=(qwen3.5:4b nomic-embed-text) ; chat=qwen3.5:4b ;;
  1) models=(qwen3.5:9b nomic-embed-text) ; chat=qwen3.5:9b ;;
  2) models=(qwen3.5:9b qwen3.5:4b nomic-embed-text) ; chat=qwen3.5:9b ;;
  *) echo "usage: $0 --tier 0|lite|1|2 [--check] [--model-host URL]"; exit 2 ;;
esac
roles() { [ -n "$1" ] && echo "HMAP_ROLE_MAP=reasoner=$1,judge=$1,coder=$1,fast=$1,classify=$1,embed=nomic-embed-text"; }
if [ "$tier" = 0 ]; then
  echo "tier 0: no model. Use HMAP_LLM_MODE=replay (make demo-replay, tests) - the recordings are in samples/llm_cache/."
  echo "HMAP_MODEL_TIER=0"; exit 0
fi
url="${host:-${OLLAMA_BASE_URL:-http://127.0.0.1:11434}}"; url="${url%/}"
if ! curl -fsS "$url/api/version" >/dev/null 2>&1; then
  if [ -n "$host" ]; then echo "the model host $url does not answer (it must serve on the LAN: docs/members/11/sizing.md)"; exit 1; fi
  echo "Ollama is not running at $url. Start it:"
  echo "  OLLAMA_MODELS=${OLLAMA_MODELS:-/Volumes/Tirth_SSD/ollama} OLLAMA_MAX_LOADED_MODELS=2 ollama serve"; exit 1
fi
have="$(curl -fsS "$url/api/tags" | python3 -c 'import json,sys; print("\n".join(m["name"] for m in json.load(sys.stdin)["models"]))')"
missing=()
for m in "${models[@]}"; do
  if printf '%s\n' "$have" | grep -qx -e "$m" -e "$m:latest"; then echo "  ok       $m"; else echo "  missing  $m"; missing+=("$m"); fi
done
if [ ${#missing[@]} -gt 0 ] && [ $check = 0 ] && [ -z "$host" ]; then
  disk="${OLLAMA_MODELS:-/Volumes/Tirth_SSD/ollama}"
  free_gb=$(df -g "$disk" 2>/dev/null | awk 'NR==2 {print $4}')
  if [ -n "$free_gb" ] && [ "$free_gb" -lt 20 ]; then echo "only ${free_gb} GB free on $disk: not pulling"; exit 1; fi
  for m in "${missing[@]}"; do echo "pulling $m ..."; OLLAMA_MODELS="$disk" ollama pull "$m" || exit 1; done
elif [ ${#missing[@]} -gt 0 ]; then
  [ -n "$host" ] && echo "pull them on the model host" || echo "(--check: nothing pulled)"; exit 1
fi
echo; echo "for .env (role aliasing, tier $tier):"; roles "$chat"; echo "HMAP_MODEL_TIER=$tier"
[ -n "$host" ] && echo "OLLAMA_BASE_URL=$host"
# smoke test: one short call per chat model of the tier
for m in "${models[@]}"; do
  case "$m" in *embed*) continue ;; esac
  out=$(curl -fsS "$url/api/chat" -d "{\"model\":\"$m\",\"stream\":false,\"think\":false,\"messages\":[{\"role\":\"user\",\"content\":\"Say OK.\"}],\"options\":{\"num_predict\":5}}" 2>/dev/null \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["message"]["content"].strip()[:20])' 2>/dev/null)
  [ -n "$out" ] && echo "  smoke    $m: \"$out\"" || { echo "  smoke    $m: FAILED"; exit 1; }
done
