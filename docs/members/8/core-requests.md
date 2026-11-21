# Requests to Member 1 (core / shared files)

Anything you need changed outside your own paths (`ownership.toml`): describe it here, Member 1 implements it.

| # | Date | File / area | What and why | Status |
|---|---|---|---|---|
| 1 | 2026-10-30 | `ownership.toml` | `[cross_cutting] 8` rows for the shared files of [plan](plan.md) §3 (Q6) | default taken 2026-10-30, row added |
| 2 | 2026-10-30 | `backend/src/hmap/core/config.py`, `.env.example` | `HMAP_TESTING_*` settings (sandbox backend, image, memory, stage time limit, concurrency, auto-revise, rounds, test generation; 2026-10-31 stretch: mutation, mutants, fuzz, dependency audit, runtime, Node image) (Q5) | default taken 2026-10-30; stretch settings added 2026-10-31 under Member 1's "do every Member 8 item" |
| 3 | 2026-10-30 | `Makefile` | `sandbox-image` target: builds `hmap-sandbox-py:1` and (2026-10-31) `hmap-sandbox-node:1` from `agents/testing/sandbox/` (needs the internet once) (Q3) | default taken 2026-10-30 |
| 4 | 2026-10-30 | runner isolation | the testing agent runs on the host and calls the `docker` CLI (no socket in a container); falls back to Member 7's jailed runner without Docker (Q1, Q2) | default taken 2026-10-30; no core change |
| 5 | 2026-10-30 | test -> revise loop | on by default, at most 2 rounds, only real (not lint / flaky / generated / environment) failures; `code.revise` is created with Member 7's `revision_inputs` (Q4) | default taken 2026-10-30; no core change |
| 6 | 2026-10-30 | `scripts/demo_sprint_8.{sh,py}`, `README.md`, `HANDOFF.md`, `frontend/src/features/_registry.generated.ts` | Sprint 8 demo, "real vs stub" row, Sprint 8 handoff section, the regenerated feature registry (Testing tab) | default taken 2026-10-30 |
| 7 | 2026-10-31 | Colima VM | installing gVisor (`runsc`) as a Docker runtime in the Colima VM (downloads the binary, changes the VM's Docker daemon config) to measure it | approved by Member 1 2026-10-31; installed (release-20261026.0) and measured ([gvisor.md](gvisor.md)) |
