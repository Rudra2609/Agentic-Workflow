# Final release gate (items 11.19–11.24)

The release checklist (doc 02 §3.5) and every gate result, run on Member 1's laptop on 2026-11-02 (Apple M3, 16 GB,
Docker infra via Colima). Rows marked **personal** or **Member 1 (models)** are still open; sign-off by Member 1 and
Member 9 closes the gate.

## 1. Regression matrix (11.19)
All sprint tests × `HMAP_LLM_MODE` {fake, replay, live-smoke} × `HMAP_ROUTER` {off, on} × tier {0, 1}
(`scripts/release_matrix.sh`; raw results `samples/models/release/matrix.json`). The fake cells are
`scripts/check_sprint.sh 11` with `HMAP_ROUTER=off` and `=on`: each 1462 backend tests with the Docker infra, 169
frontend tests + lint / types / build, 31 security tests, the Sprint 11 demo in memory and on RabbitMQ + Postgres. The
replay cells replay the three golden scenarios; the live-smoke cells call `fast`, `reasoner` (schema), `classify`
and `embed` through the platform-built gateway with the team keys (the embedder is always local: Ollama runs for it).

<!-- matrix:start -->
| Cell | Status | Seconds |
|---|---|---|
| fake / router off / tier 0 | green |  |
| fake / router on / tier 0 | green |  |
| replay / router off / tier 0 | green | 26.6 |
| replay / router on / tier 0 | green | 29.0 |
| live-smoke / router off / cloud | green | 7.0 |
| live-smoke / router on / cloud | green | 3.8 |
| live-smoke / router off / tier 1 (local only) | green | 19.1 |
| live-smoke / router on / tier 1 (local only) | green | 5.4 |
<!-- matrix:end -->

## 2. Chaos + soak (11.20) — on the clean copy, RabbitMQ + Postgres, router on
- **Chaos** (`scripts/demo_chaos.sh`, Member 4's): the agents process was killed while a research step ran; after
  42 s the lease expired, the execution was abandoned and retried on the new agents process; **recovered in 76 s, 0
  dead letters** (`samples/models/release/chaos-clean-copy.txt`). One round (the Sprint 6 / 10 runs did 3).
- **Soak** (`infra/observability/load/soak.py --real`, Member 4's): 40 projects × 8 steps, 20 at a time, two agent
  sets: **40 / 40 completed, 0 failed**, 4.2 steps/s, latency p50 17 s / p95 52 s, deepest queue 201, process RSS ≤
  200 MB, free RAM never below 1.6 GB (`soak-clean-copy.json`).
- Not repeated here: broker / DB down (Sprint 4 and Sprint 10 runs; the stack is unchanged since), Ollama down (the
  whole release ran with Ollama stopped except for the embedder).

## 3. Clean-copy run (11.21)
`scripts/make_handoff.sh final` → `/Volumes/Tirth_SSD/hmap_handoff/sprint-final_2026-11-02/` (no `.env`, no data, no
models; `.env` with the team keys copied in by hand) → its **own database `hmap_release`** (the real `hmap` database
untouched; `hmap_release` dropped afterwards) → `scripts/doctor.sh` (OK; Ollama "not running" is only needed live)
→ `make demo` live: API healthy on RabbitMQ, dashboard 200, the demo account and the seeded project waiting at the
plan approval → chaos + soak (§2) → `make stop` → **`make demo-replay` with Ollama stopped**: healthy → `make stop`.

| Checklist item (doc 02 §3.5) | Result |
|---|---|
| fresh copy from `make_handoff.sh final` | done |
| `scripts/doctor.sh` green | done |
| `make demo` (migrations + seed run automatically) | done (live, cloud keys) |
| demo script passes | the three golden scenarios replayed (matrix) + live TCP chat (eval.md §4) |
| the same demo with **no cloud keys** (all roles local) | partly: the platform-built gateway answers every role locally (tier-1 matrix cells, `qwen3.5:9b`, router off and on: green) and `make demo` ran with the lite model loaded (sizing.md); a full golden scenario all-local is **not run** here: it takes > 90 min with the 9B (Sprint 10 eval §6) |
| `make reset-demo` then `make demo-replay`, Ollama stopped, Wi-Fi off | demo-replay with Ollama stopped: done (on a fresh database instead of reset-demo); **Wi-Fi off: personal** |
| video backup | **personal** |
| runbook | [runbook.md](runbook.md) |

## 4. Rehearsals (11.22)
| Run | Who | Result |
|---|---|---|
| offline (replay + cached research) ×1 | build | done: the three golden scenarios replayed, router off and on (matrix), and `make demo-replay` on the clean copy |
| live ×3 on Member 1's laptop | **personal** | |
| video backup of a full run | **personal** | |

## 5. Slides (11.23)
[slides.md](slides.md): one 60-second slide per member (each member fills their own) + `make report`.

## 6. Freeze (11.24)
- Model digests pinned (`samples/models/release/pinned_models.json`): `qwen3.5:9b` 56671c2a…, `qwen3.5:4b`
  d8b0f5e9…, `nomic-embed-text` 0a109f42… (all from `ollama list`, 2026-11-02); cloud models are named in
  `DEFAULT_CLOUD_ROLE_MAP` (no digest exists for them). Pin them in a running registry with the Models page "Pin".
- Snapshot: `scripts/make_handoff.sh final` → `/Volumes/Tirth_SSD/hmap_handoff/sprint-final_2026-11-02/` (+
  `MANIFEST.json` with every file's SHA-256). Re-make it after Member 1's model decisions.

## 7. Sign-off (DoD)
| | Name | Date |
|---|---|---|
| Release checklist executed | Member 11 | |
| Signed off | Member 1 | |
| Signed off | Member 9 | |
