# Changes in other members' code (Sprint 11)

Taken with the plan's defaults (Q1, Q12; 2026-11-01). Each is listed in `ownership.toml [cross_cutting] 11` so the
ownership check reports it for sign-off.

| # | Owner | File(s) | Change | Why |
|---|---|---|---|---|
| 1 | M1 | `core/plugins.py` | `RouteQuery` / `RoutePlan` / `RouteOutcome`, the `RouteStrategy` protocol and `NoRouting` | the `llm_provider` slot was declared but had no interface and nobody read it (plan T1) |
| 2 | M1 | `core/llm/gateway.py` | `Gateway(route=…)`: before each live chat call it asks the strategy (`decide`), follows the plan (cloud route order / no cloud / the local model and provider), reports the outcome (`observe`); a broken strategy is logged and ignored. Replay, fake and embeddings never ask | the router must decide per call without agent changes |
| 3 | M1 | `core/llm/cloud.py` | `CloudRouter.chat(routes=…)` (one call's route order), `routes_for`, `available()`, `attempt_listener` (each HTTP attempt's outcome, for the router's per-model statistics) | the pool kept its fixed order; the router needs per-call order and the 429s per model |
| 4 | M1 | `system.py`, `core/runtime/host.py` | both gateway builders pass the discovered plug-ins' `llm_provider` (`route_strategy`, which calls `configure(settings)`) | the in-process system and the agents' own process (split mode) both route (plan T3) |
| 5 | M1 | `db/tables.py` | the four migration-011 tables in `MEMBER_TABLES` | the migration test compares the schema with this list |
| 6 | M1 / M9 | `core/config.py`, `.env.example`, `docs/members/9/platform/configuration.md` | router / tier / warm-up / MLX / llama.cpp settings, `HMAP_MODEL_ROLES` as an alias of `HMAP_ROLE_MAP` (plan T12); the reference regenerated | settings |
| 7 | M9 | `scripts/demo.sh`, `scripts/demo_preflight.py` | warm-up in the background when Ollama is up (`HMAP_WARMUP`); the pre-flight names a remote Ollama as the model host | items 11.16, 11.18 |
| 8 | M1 | `Makefile` | `models-pull`, `bench`, `release-matrix` | |
| 9 | M1 | `README.md`, `HANDOFF.md`, `docs/README.md`, `ownership.toml` | the status line and the model-routing row, the Sprint 11 handoff, the docs index | |
| 10 | M1 (M6) | `backend/tests/db/test_migrations.py` | migration 011's two indexes in the member-index list | the schema check compares migrations with the table models |
| 11 | M7 | `backend/tests/coding/test_integration_real.py` | wait for the `code.completed` event (poll) instead of reading the event feed once | a timing race: the event arrives through the outbox just after the task settles; failed in the full suite after the other coding tests, passed alone (also seen in Sprint 10) |

Tests for 1–4: `backend/tests/core/llm/test_route_slot.py` (no strategy = byte-for-byte the old behaviour; reorder;
unmapped role to the cloud; no cloud + local model; a routed local provider; `cloud_ok=false` still wins; a broken
router; failure observed; replay and fake never ask; slot resolution) and `tests/models/test_api.py` (both builders).

Not changed: the plug-in mount adds a session dependency to every route, which a WebSocket cannot satisfy, so the
route-decision stream is a 2-second poll of `GET /api/models/routes?since=` rather than a WebSocket (no change to
Member 1's mount).
