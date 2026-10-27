# Testing — Member 6 (Sprint 6, item 6.12)

All tests run offline with the `fake` model or the replay cache; integration tests run when `make infra-up` is up
and skip (with the reason) otherwise.

```bash
cd backend
uv run pytest tests/verify -q                       # 69 tests: verification + security (+1 integration)
uv run pytest tests/verify/security -q              # the security suite alone (also run by scripts/security_check.sh)
uv run python -m tests.verify.eval.run_eval         # the benchmark (replay), see eval.md
```

| File | What | Kind |
|---|---|---|
| `tests/verify/test_layers.py` | atomizer vs 25 gold splits; L1 on every benchmark item (15/15 fake quotes, 0 false fails) and each failure reason; L2 both orders, unsure, number guard, rules fallback; L3 own queries + cited pages excluded; L4 signals, rules and model; **every decision-table row**; roll-up; follow-up questions | unit (fake model) |
| `tests/verify/test_agent_api.py` | the agent on the in-memory bus: a tampered quote → UNSUPPORTED with reason; verification.completed; **one follow-up round** (research with `follow_up_of` + re-check depending on it) and **no third round**; the API (runs, detail with evidence, table, "request more research"), ownership (404 for another user); no report → "nothing to verify"; injected failure → retry; **idempotent redelivery** (same artifacts) | integration in memory |
| `tests/verify/test_integration_real.py` | the same on **RabbitMQ + Postgres**; a forged message on the real broker is refused and lands in `security_audit` | integration (infra) |
| `tests/verify/security/test_security_layer.py` | keyring file 0600 + shared; env keyring; token issue / expiry / wrong agent / retired key / revoke; signed envelopes (changed payload, other sender, unsigned); signer renewal at half-life and after rotation; on the bus: seeded tokens keep agents working; **5 forgery kinds refused + audited** (unsigned, unregistered sender, other capability, impersonating heartbeat, agent sending a command, changed in transit); commands only from the Manager; **rotation while a task runs, then retire, then revoke**; audit-only mode | unit + in memory |
| `tests/verify/security/test_injection.py` | the injection regression suite (design §7, security-report §3); known findings F1–F3 are `xfail(strict)` | in memory |
| `tests/verify/security/test_limits_and_secrets.py` | upload bytes must match the type (415); write rate limit (429, per client); other user's project / artifacts hidden, anonymous 401; oversized message refused; **every listener binds 127.0.0.1** (compose, scripts, Makefile, Next.js, metrics); **no key, agent secret or token** in logs, events, the agents page, bus messages or artifacts | in memory + static |
| `frontend/src/features/verify/*.test.ts(x)` | logic (sorting, layer lines, event key, excerpt); the panel (flagged first, layer lines, quote next to the saved page, "request more research") | vitest |

Changed Member 1 tests: `tests/db/test_migrations.py` (migration 006 indexes), the contract snapshot
`tests/contracts/snapshots/Envelope.schema.json` (additive `auth`). The whole backend suite: 1032 passed with infra
(2026-10-18), no regressions.

Demos: `scripts/demo_sprint_6.sh` (memory, and on RabbitMQ + Postgres with agents in their own process when infra is
up), `scripts/demo_chaos.sh` (3 rounds on `make demo`).
