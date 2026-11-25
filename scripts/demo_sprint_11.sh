#!/usr/bin/env bash
# Sprint 11 demo (Member 11: local models & routing), offline, no model, no key: live route decisions through the
# real gateway + router (router on vs off), the Models page's API (registry, hardware, benchmark), and on the
# RabbitMQ + Postgres pass (HMAP_STORE=postgres) the decision log through migration 011.
set -uo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
(cd "$root/backend" && HMAP_ENV_FILE=none uv run python "$root/scripts/demo_sprint_11.py") || exit 1
