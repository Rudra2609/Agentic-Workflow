#!/usr/bin/env bash
# Sprint 10 demo (Member 10: final review & recovery), offline, no model:
# 1. scripts/demo_sprint_10.py — the 12 seeded failures through the real review modules, and the closed loop on the
#    real Manager + API + review agent with scripted agents (multi-client failure -> targeted revision -> PASS; a fix
#    that never helps -> plateau -> a person accepts);
# 2. the golden TCP-chat scenario on the whole platform (scripts/demo_final.sh --only=tcp), replayed from the
#    recordings in samples/llm_cache/review/e2e (skipped with a note while there are none: record them with
#    `scripts/demo_final.sh --record`). DEMO_FINAL=0 skips step 2.
# Under check_sprint's RabbitMQ + Postgres pass (HMAP_BUS=rabbitmq), step 2 runs on that stack; step 1 is in-process.
set -uo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
(cd "$root/backend" && HMAP_LLM_MODE=fake uv run python "$root/scripts/demo_sprint_10.py") || exit 1
if [ "${DEMO_FINAL:-1}" = "1" ]; then
  if [ -n "$(ls -A "$root/samples/llm_cache/review/e2e" 2>/dev/null)" ]; then
    echo; echo "3. The golden TCP-chat scenario on the whole platform (replay)"
    HMAP_LLM_MODE=replay "$root/scripts/demo_final.sh" --only=tcp || exit 1
  else
    echo "(no golden recordings yet: run scripts/demo_final.sh --record once with the team keys)"
  fi
fi
