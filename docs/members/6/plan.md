# Sprint 6 plan of action — Member 6: Research verification (+ security, + mid-eval readiness gate)

Spec: [`docs/sprints/sprint-06-member6-research-verification.md`](../../sprints/sprint-06-member6-research-verification.md)
(items 6.1–6.24). Mid-eval: [`docs/sprints/mid-evaluation.md`](../../sprints/mid-evaluation.md).
Written 2026-10-18 against the code as handed over after Sprint 5 (`check_sprint.sh 5` PASS, 2026-10-14).

**Status (2026-10-18): built.** Member 1 approved the defaults (Q1 non-blocking follow-up hook, Q2 additive
`Envelope.auth`, Q3 the three demo files, Q4 the cross-cutting rows). See [README](README.md), [design](design.md),
[eval](eval.md), [testing](testing.md), [security-report](security-report.md). Differences from this plan, found while
building:
- **The token never travels** (D14): sending it in `agent.register` would let anyone reading the bus reuse it; every
  message is signed with it instead, and the Manager re-derives it from the keyring.
- **"Assigned" means "a registered agent serving the task's capability"** (D16), not "the execution's agent":
  commands go to a shared capability queue and the broker redelivers to a new instance after a crash (found by the
  chaos script; security-report F4).
- Atomization is **rules only** (D12): a model split invents claims; 25/25 gold splits with rules.
- L3/L4 run only for parts the quotes support; L4 judges ≤ 3 passages.
- Per-item search worlds in the eval: a clean item's search must not find the counter-page planted for its
  contradiction twin.
- `make demo` uses empty local research / verify caches (as the recordings were made) and a separate demo account.
- The chaos script restarts the agents **after** the lease expired (started at once, the broker's redelivery lets the
  new agents finish the same execution: a recovery too, but not the lease-expiry path the storyline shows).
- The follow-up research's recordings were added to Member 5's replay folder (31 files, additive only; approved by
  Member 1 on 2026-10-18, listed in HANDOFF.md).

Sprint 6 has three parts:
- **A. Verification:** a real `verify.claims` agent (6.1–6.12).
- **B. Security:** the basic security layer that moved here from Sprint 1, plus hardening (6.13–6.20).
- **C. Mid-eval readiness gate** (6.21–6.24).

---

## 0. What already exists (checked in the code)

| Thing | Where | State |
|---|---|---|
| `ClaimVerdict`, `VerificationReport` (+ computed `summary`) | `core/contracts/domain.py:316-345` | done (Sprint 1). Matches spec §7 |
| `verification.completed` event type | `core/contracts/events.py:56` | defined, nobody emits it yet |
| `verify.claims` capability → `verification-report` | `core/contracts/capabilities.py` | done |
| `VerifyClaimsStub` (priority 0) | `agents/stubs/agents.py:123` | yields once a real plug-in exists |
| Verify step in every plan: `research → verify` | `agents/planning/templates.py:81,99` (Member 3) | done. In document projects the **test** step can be `verify.claims` too (line 44) |
| Upstream artifacts handed to a task | `manager.py:1151` `_dependency_artifacts` | the verify task gets the research report refs in `artifact_refs` + `inputs.dependency_artifacts` |
| Follow-up research | Member 5: `research.run` with `inputs={"follow_up_of": ref, "research_questions": [...]}` | done, keeps old evidence ids |
| Quote checker, providers, fetcher, index | `agents/research/{quotes,providers,fetch,index}.py` (Member 5) | public, reusable. `SearchCache(read_dirs, write_dir)` allows a separate verify cache |
| Benchmark (6.9) | `samples/verify/` (prep package) | **86 items, 60 seeded**, checker passes |
| Poisoned web pages | `samples/research/adversarial/` (Member 5) | 4 pages, read-only for me |
| `AgentRegister.token` field | `core/contracts/messages.py:124` | placeholder, unused |
| Message size cap | `core/contracts/envelope.py:20` `MAX_MESSAGE_BYTES = 256 KB` | exists |
| Upload size cap | `api/routers/projects.py:26` `25 MB` | exists; no file-type allow-list |
| Accounts, scrypt, CSRF, login rate limits | `api/` + `services/accounts/` (Member 1) | exists |
| Docker services bind `127.0.0.1` | `infra/docker-compose.yml` | done for Postgres + RabbitMQ |
| **`core/policy.py` (`allow_all` hook)** | — | **MISSING.** Sprint 1 §88 and HANDOFF promise it but the file does not exist and nothing calls it. See D13 |
| `make demo` / `make stop`, `scripts/demo_chaos.sh`, `scripts/security_check.sh` | — | missing (my job) |
| `samples/demo/` | has only `tcp_chat_assignment.txt` | the 3 inputs must be added |
| Judge role uses a different family | `DEFAULT_CLOUD_ROLE_MAP`: reasoner = Gemini/gpt-oss, judge = Groq **qwen** | true on cloud. **Locally every role is `qwen3.5:9b`** (same model) → limitation, not mine to change (Member 11) |

---

## 1. Decisions (please confirm or change)

| # | Decision | Why |
|---|---|---|
| D1 | Verifier input = the newest `research-report` among the task's `artifact_refs`. No report (e.g. a document project's *test* step, or stub DocBundle upstream) → an **empty `VerificationReport`** with explanation "nothing to verify", task succeeds | planning sends `verify.claims` to steps with no research; must never fail the pipeline |
| D2 | Layers run cheapest first and **stop early**: L1 fail ⇒ no LLM call for that claim | spec §4 + saves calls |
| D3 | L2 judge = role `judge`, input = claim + one quote only, strict JSON `{verdict: supports\|refutes\|not_enough, rationale}`. **Position-bias control:** a second call with quote first / claim second on a sample; disagreement ⇒ `not_enough`. Quotes wrapped as untrusted data (same wrapper style as Member 5) | spec 6.3, research.md §2 |
| D4 | L3 own query generator (role `fast`) that sees **only the claim text**, never the brief, sub-questions or researcher queries. Uses Member 5's `get_providers(..., settings=…)` with **its own cache dir** `samples/verify/search_cache/` and the offline corpus read-only. Cap: 2 queries × 3 pages per claim, only for claims that pass L1+L2 | independence; offline demo; bounded cost |
| D5 | L4 compare = rules first (numbers with units, dates/years, negation words, version strings) between the claim's quote and L3 / counter pages; `judge` only for candidates the rules flag. Needs ≥ 2 distinct domains to call VERIFIED-with-agreement | cheap + explainable |
| D6 | Aggregator = the decision table in `research.md` §7 as data (`aggregate.TABLE`), tested row by row. Confidence = per-row base rate measured on the benchmark (fixed table, not model-reported) | 6.6; honest calibration |
| D7 | **Follow-up loop = a Manager hook in my plug-in** on `task.completed` (capability `verify.claims`): if any `UNSUPPORTED`/`NEEDS_MORE_RESEARCH` and round < `HMAP_VERIFY_MAX_ROUNDS` (default 1) → create `research.run` (`follow_up_of` + gap questions) and a `verify.claims` task that `depends_on` it, both with `parent_task_id`. Round count read from the task chain. Plan's downstream steps are **not** blocked (they already depend on the first verify) | 6.8; uses only `ManagerHandle.create_task`, no Manager change |
| D8 | Emit `verification.completed {task_id, report_ref, summary, round}` from the hook via `manager.emit` | spec §7 |
| D9 | Artifacts: `verification-report` (`VerificationReport`) + `verification-trace` (`vt-<task_id>`: per-claim per-layer results, for the UI and eval) | same pattern as Member 5's trace |
| D10 | Agent honours `stub_fail` / `stub_delay_s` like the stub (Member 4's and the chaos tests inject failures by capability) | Sprint 5 trap |
| D11 | Replay: every LLM call recorded in `samples/llm_cache/verify/`. Eval runs with `--record-missing` once (team keys), then everything is replay | CLAUDE.md: tests never use a key |
| D12 | Claim atomizer (6.1): rules split on `;`, " and " between clauses, lists; `fast` only for long claims; check-worthiness filter drops opinions/questions. Atomic claims keep the parent `claim_id` + suffix (`C3.a`) and verdicts roll up (worst wins) | report claim ids stay stable for Member 10 |
| D13 | **Security layer lives in `core/policy.py`** (allowed for me, cross-cutting). Because the Sprint 1 hook was never written, I also need a few call sites in Member 1 code (§5). Design: `Policy.check(envelope, payload) -> Decision`; Manager calls it in `handle_message` before dispatch; deny ⇒ drop + audit row + `security.denied` log/event | 6.20 |
| D14 | Service tokens: `token = HMAC-SHA256(platform_secret[kid], agent_id + exp)`, format `v1.<kid>.<exp>.<sig>`. Issued by the agent host at registration from `HMAP_AGENT_SECRETS` (keyring: current + previous). Manager checks on `agent.register` and binds agent_id → allowed capabilities. **Rotation:** add a new kid, keep the old one valid for a grace period → no downtime. **Revocation:** `revoked` set in the audit table. With no secret set (tests, old snapshots) → dev mode: tokens auto-seeded, still checked | 6.15, "existing agents keep working with seeded tokens" |
| D15 | Per-message auth: add an **optional, additive** `auth` field to `Envelope` (HMAC of message_id + type + task_id with the agent's token). Missing ⇒ allowed only in dev mode. Alternative (smaller): check only at registration + sender/capability match, no envelope change | see open question Q2 |
| D16 | Capability → allowed-message table: e.g. an agent may send `task.result` only for a task whose capability it registered; only the Manager may send `task.assign`/`task.cancel`. Table in `core/policy.py`, tested per row (allowed + denied) | 6.20 |
| D17 | Audit log = table `security_audit` in **migration `006_sprint_6_verify`** (mine) + in-memory version for `HMAP_STORE=memory` | 6.20 |
| D18 | Dependency + secret scan: `scripts/security_check.sh` runs the existing `secret_scan.sh`, `uvx pip-audit` (no new dependency in `pyproject.toml`), `npm audit --omit=dev`, a log/trace secret scan over `logs/` and replay cache. Report → `docs/members/6/security-report.md`, findings triaged (fix / accept / owner) | 6.16 |
| D19 | `make demo` (6.21) = **minimal**: `infra-up` + migrations + API + agents + web, `HMAP_LLM_MODE=replay`, research `cached`; `make stop` stops all and Ollama if started. No reset/seed/config reference (Member 9, Sprint 9) | spec 6.21 says minimal |
| D20 | `demo_chaos.sh` (6.22): split mode (RabbitMQ), start a project, wait for `research.run` RUNNING, `kill -9` the agents process, restart it, assert lease expiry → new execution → task SUCCEEDED, print the Ops/DLQ URL (Member 4's page, unchanged). Loop 3× | 6.22 |
| D21 | Demo inputs (6.23) copied from Member 2's gold set (read-only use): `g01_tcp_chat/tcp_chat_assignment.pdf`, `g04_scanned/library_assignment_scan.pdf` (the gold set has no scanned *lab manual*; this is the scanned one), `g02_lab_manual/lab4_unit_testing.docx` | Q3 |
| D22 | Demo storyline flagged claim must be **deterministic**: the demo brief's report has a claim the verifier flags in replay; the follow-up round fixes it; re-verify passes. Fixed by recordings, not by luck | 6.24, "live = replay" |

### Open questions for Member 1
- **Q1 (D7):** OK that follow-up research runs *next to* the downstream plan steps (not blocking them)? The other option is to make the verify agent wait, which needs a Manager change.
- **Q2 (D15):** additive `Envelope.auth` field (contract + snapshot change in `core/`), or registration-only checks?
- **Q3 (D21):** OK to use `library_assignment_scan.pdf` as the "scanned" input and `lab4_unit_testing.docx` as the DOCX?
- **Q4:** OK to add Member 6 entries to `[cross_cutting]` in `ownership.toml` (§5) so the ownership check shows "needs sign-off" instead of "shared"?

---

## 2. Work breakdown (order of build)

### Phase 1 — Verification core (offline, no LLM yet)
| Step | Item | Files (all mine) | Done when |
|---|---|---|---|
| 1 | 6.1 claims | `agents/verify/claims.py` | gold atomic splits in `samples/verify/atomic_gold.jsonl` (~25 claims) pass |
| 2 | 6.2 L1 mechanical | `agents/verify/mechanical.py` | sha256 of stored page = `content_sha256`, `quotes.locate()` finds the quote, URL matches page. **15/15 fake quotes caught**, 0/71 false fails |
| 3 | 6.6 aggregator | `agents/verify/aggregate.py` | one test per table row |
| 4 | models | `agents/verify/model.py` (layer results, trace) | — |

### Phase 2 — LLM layers + agent
| Step | Item | Files | Done when |
|---|---|---|---|
| 5 | 6.3 L2 entail | `agents/verify/entail.py`, `prompts.py` | fake-LLM unit tests; accuracy on labelled pairs in eval |
| 6 | 6.4 L3 independent | `agents/verify/independent.py`, `samples/verify/search_cache/` | finds the synthetic counter page on the seeded `contradiction` items |
| 7 | 6.5 L4 compare | `agents/verify/compare.py` | rule tests: numbers, dates, negation, versions |
| 8 | pipeline | `agents/verify/pipeline.py` | report + trace from a `ResearchReport` |
| 9 | 6.7 agent | `agents/verify/agent.py`, `plugin.py` (priority 100) | on the bus; idempotent (same task + execution → same artifact ids, no duplicate) |
| 10 | 6.8 follow-up hook | `agents/verify/hooks.py` (in `plugin.py`) | one loop on the demo brief; stops at max rounds |

### Phase 3 — Benchmark + eval
| Step | Item | Files | Done when |
|---|---|---|---|
| 11 | 6.9 benchmark | `samples/verify/` (exists) | add atomic gold + L3 search cache; `check_benchmark.py` OK |
| 12 | 6.10 eval | `backend/tests/verify/eval/run_eval.py` | ablation L1 → +L2 → +L3/L4: recall per kind, false-alarm rate on 20 clean, accuracy, citation recall/precision (ALCE), position-swap agreement; `eval.md` written |

### Phase 4 — API + UI
| Step | Item | Files | Done when |
|---|---|---|---|
| 13 | 6.11 API | `agents/verify/router.py` (auto-mounted `/api/verify`): `GET runs/{project_id}[/{task_id}]`, `POST runs/{project_id}/{task_id}/follow-up` ("request more research") | API tests |
| 14 | 6.11 UI | `frontend/src/features/verify/` (auto-registered tab): claim table with verdict chips, quote vs page side by side (reuse Member 5's page endpoint over HTTP), conflict view, layer badges, "Request more research" button | vitest + build green |

### Phase 5 — Security (6.13–6.20)
| Step | Item | Where | Done when |
|---|---|---|---|
| 15 | 6.20 basic layer | `core/policy.py` + call sites (§5), migration 006 audit table | unauthorized `task.result` denied + audited; all existing tests green with seeded tokens |
| 16 | 6.15 token lifecycle | `core/policy.py`, tests | rotate kid while agents run → no failed task; expired/revoked denied; secret-scan over logs/traces/replay cache finds nothing |
| 17 | 6.14 AuthN/Z tests | `backend/tests/verify/security/` | negative tests: other user's project/artifact → 404/403, unauth agent, wrong capability, audit row written |
| 18 | 6.13 injection suite | `samples/verify/injection/` + `backend/tests/verify/security/test_injection.py` | poisoned PDFs/DOCX (I make my own), Member 5's 4 pages (read-only), poisoned repo/README files, poisoned agent messages; runs in CI. M7/M9 cases run against the stubs now and are marked for Members 7/9 to switch on |
| 19 | 6.17 input limits | tests + small Member 1 changes (§5) | file-type allow-list on upload, message cap tested, API rate limit on write endpoints, every listener on `127.0.0.1` (test that greps compose + uvicorn args) |
| 20 | 6.16 scanning | `scripts/security_check.sh`, `docs/members/6/security-report.md` | findings triaged |
| 21 | 6.18 + 6.19 docs | `docs/members/6/design.md` (security section: STRIDE-lite threat model; TLS/mTLS deferral write-up) | team review |

### Phase 6 — Mid-eval readiness (6.21–6.24)
| Step | Item | Where | Done when |
|---|---|---|---|
| 22 | 6.23 inputs | `samples/demo/` | 3 files + README with sources |
| 23 | 6.21 `make demo` / `make stop` | `Makefile`, `scripts/demo.sh`, `scripts/stop.sh` | one command from a clean copy (`make_handoff.sh` folder) |
| 24 | demo 6 | `scripts/demo_sprint_6.{sh,py}` | research → verify → flagged claim → follow-up → re-verify, memory + split mode |
| 25 | 6.22 chaos | `scripts/demo_chaos.sh` | 3× in a row |
| 26 | 6.24 storyline + table | `README.md` "real vs stub" table, tick `mid-evaluation.md` §4 items I can verify | live (cloud keys) = replay result recorded once |

### Phase 7 — Hand-off
`docs/members/6/{README,design,eval,testing}.md`, `HANDOFF.md` Sprint 6 section, `scripts/check_sprint.sh 6` PASS (incl. `security_check.sh`), stop every process (API, agents, Ollama, Docker if I started it), tell Member 1 the sprint is done.

---

## 3. Tests (6.12)
- **Unit:** each layer with the `fake` LLM; aggregator table; atomizer gold; L1 on all 86 items.
- **Contract:** `VerificationReport` validates against the JSON Schema; trace schema.
- **Integration:** one test on RabbitMQ + Postgres (`@pytest.mark.integration`): research report → verify task → report artifact → hook creates follow-up.
- **Replay:** full benchmark in `replay`, 0 misses.
- **Security:** policy table rows, token rotate/expire/revoke, injection suite, authZ negatives.
- **Regression:** whole suite (968 backend + 130 frontend after Sprint 5) must stay green.

## 4. Metrics I will report in `eval.md`
Per layer and per kind: recall of flagged errors; false-alarm rate on 20 clean; verdict accuracy; L1 recall on fake quotes (**must be 100 %**); position-swap agreement; LLM calls + tokens per claim; time per report; follow-up loop rounds and how many flagged claims it fixed. Also a local-only run (`qwen3.5:9b`) with the caveat that judge and researcher are then the same model.

---

## 5. Paths outside my folders (needs Member 1 sign-off)

My own folders (`ownership.toml` `[members.6]`): `backend/src/hmap/agents/verify/**`, `backend/tests/verify/**`,
`frontend/src/features/verify/**`, `docs/members/6/**`, `samples/verify/**`, `samples/llm_cache/verify/**`,
`backend/alembic/versions/006_*`. Already allowed cross-cutting: `core/policy.py`, `scripts/security_check.sh`.

Member 1 paths the sprint spec makes me touch ("shared" in the ownership check). As in Sprints 3–5 I list them in the commit message:

| Path | Change | Item |
|---|---|---|
| `backend/src/hmap/manager/manager.py` | call `policy.check()` in `handle_message`; check token in `_on_register` | 6.20 |
| `backend/src/hmap/core/runtime/host.py` / `worker.py` | attach token at registration (and `auth` per message if Q2 = yes) | 6.20 |
| `backend/src/hmap/core/contracts/envelope.py` + schema snapshots | optional `auth` field (only if Q2 = yes) | 6.20 |
| `backend/src/hmap/core/config.py`, `.env.example` | `HMAP_VERIFY_*` (max rounds, L3 on/off, cache dir), `HMAP_AGENT_SECRETS`, `HMAP_TOKEN_TTL_S` | 6.8, 6.15 |
| `backend/src/hmap/db/tables.py`, `backend/tests/db/test_migrations.py` | add my tables to `MEMBER_TABLES`, new head 006 | 6.20 |
| `backend/src/hmap/api/routers/projects.py` | upload file-type allow-list; rate limit on write routes | 6.17 |
| `Makefile` | `demo`, `stop` targets | 6.21 |
| `scripts/check_sprint.sh` | call `security_check.sh` (DoD addition) | 5b |
| `scripts/demo_sprint_6.{sh,py}`, `scripts/demo_chaos.sh`, `scripts/demo.sh`, `scripts/stop.sh` | new | 6.21, 6.22 |
| `samples/demo/**` | 3 inputs + README | 6.23 |
| `README.md` | "what is real vs stub" table | 6.24 |
| `docs/sprints/mid-evaluation.md` | tick §4 items that are verified | 6.24 |
| `ownership.toml` | add the rows above to `[cross_cutting] 6` (Q4) | — |
| `HANDOFF.md` | Sprint 6 section (every sprint does this) | DoD |

No new Python/npm dependencies planned (`pip-audit` via `uvx`). If one becomes necessary I will ask first.

---

## 6. What I will NOT do (other members' work)

| Member | Their area | How Sprint 6 stays out of it |
|---|---|---|
| **M2** doc intel | `agents/doc_intel/**`, `samples/doc_intel/**` | only *copy* 3 gold files to `samples/demo/`; injection suite calls their public extract path. If an attack gets through their sanitizer I **report** it (security-report + `docs/members/2/core-requests.md`-style note to you), I do not patch their code |
| **M3** planning | `agents/planning/**` | the verify step already exists in their templates; no change |
| **M4** refine + observability + Ops/DLQ UI | `agents/refine/**`, `obs/**`, `agents/ops/**`, `features/ops/**` | `demo_chaos.sh` only *opens* their Ops/DLQ page; no DLQ replay UI, no new metrics/dashboards. No refine adapter for verify (not in my spec) |
| **M5** research | `agents/research/**`, `samples/research/**` (incl. its search cache) | only imported public functions (`quotes.locate`, `get_providers`, `Fetcher`, `HybridIndex`); my own search cache in `samples/verify/`; follow-up uses their existing `follow_up_of` input. No rule-quote fallback (their known limitation; recommended for M11/later) |
| **M7** coding / **M8** testing | `agents/coding/**`, `agents/testing/**` | poisoned repo fixtures live in `samples/verify/injection/`; no sanitizer in their code, no sandbox work |
| **M9** docs + demo packaging | `agents/docgen/**`; full `make demo`, seed/reset-to-demo-state, config reference, platform docs, runbook | my `make demo` is the **minimal** one the spec asks for; no reset/seed script, no config reference, no final-report compiler |
| **M10** review + e2e | `agents/review/**`, `tests/e2e/**`, golden scenarios, cross-agent contract suite | my integration tests stay in `tests/verify/`; I only emit `verification.completed` for them to use |
| **M11** models + routing + release gate | `agents/models/**`, router, model tiers, warm-up, video, freeze | no change to `DEFAULT_CLOUD_ROLE_MAP` or the router; the local "same model for judge and researcher" issue is documented, not fixed. Video backup + "explain in 60 s" are team tasks |

Before handing back: `scripts/precommit.sh --member 6 --base <sprint-5 handoff folder>` must show **no `foreign` files** (only own / cross_cutting / shared rows listed in §5).

---

## 7. Risks
| Risk | Plan |
|---|---|
| Local 9B judge is weak (Member 5 found 9B returns no quotes) | short inputs, strict enum, cloud-first by policy; report local numbers honestly |
| Verifier agrees with researcher | different family on cloud, own queries (D4), quote-only input |
| Over-flagging (false alarms) | track false-alarm rate on 20 clean items; NEEDS_MORE_RESEARCH instead of UNSUPPORTED when unsure |
| Security layer breaks existing agents/tests | dev-mode seeded tokens; land it behind the policy hook, run the full suite after each step |
| L3 offline: new queries have no cached results | own search cache recorded once with keys; offline corpus + synthetic pages as fallback |
| Chaos demo flaky | short leases in demo env vars (as Sprint 5 demo), wait on events not sleeps, 3× loop in the script |
| Sprint too big (3 parts) | order = Must of A → 6.20 → 6.21–6.24 → rest of B. STRETCH (ensemble, held-out calibration, temporal, intra-report contradictions) only if time is left; otherwise to the HANDOFF backlog |
