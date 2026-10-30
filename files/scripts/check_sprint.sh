#!/usr/bin/env bash
# Sprint acceptance (doc 03 §2): full pre-commit (incl. slow tests + frontend build) + the sprint demo smoke test.
# Usage: scripts/check_sprint.sh <n> [--base <previous handoff folder>] [--member <n>]
set -uo pipefail
n="${1:?usage: check_sprint.sh <sprint-number> [precommit args]}"; shift || true
here="$(cd "$(dirname "$0")" && pwd)"
"$here/precommit.sh" "$@"; status=$?
if [ "$n" -ge 6 ]; then   # Sprint 6 DoD (Member 6): the security checks are part of every acceptance from now on
  echo; echo "=== security: $here/security_check.sh"
  "$here/security_check.sh" || status=1
fi
demo="$here/demo_sprint_${n}.sh"
if [ -x "$demo" ]; then
  echo; echo "=== demo smoke: $demo"
  "$demo" || status=1
  # Same demo on the real stack (RabbitMQ + Postgres, agents in their own process) when `make infra-up` is running.
  if (exec 3<>/dev/tcp/127.0.0.1/5672) 2>/dev/null && (exec 3<>/dev/tcp/127.0.0.1/5433) 2>/dev/null; then
    echo; echo "=== demo smoke on RabbitMQ + Postgres, agents in a separate process"
    DEMO_SPLIT=1 HMAP_BUS=rabbitmq HMAP_STORE=postgres "$demo" || status=1
  else
    echo "(infra not running: skipped the RabbitMQ + Postgres demo; run make infra-up)"
  fi
else
  echo "no $demo yet"
fi
[ $status -eq 0 ] && echo "SPRINT $n CHECK: PASS" || echo "SPRINT $n CHECK: FAIL"
exit $status
