# 04 — Gaps in the Work Distribution, and Risks

## A. Things nobody owns in the 11-member table (and who we assign them to)

| Gap | Why it matters | Plan |
|---|---|---|
| **Manager Agent** (planning-execution loop, assignment, watchdog, recovery driver) | Central to the project pitch ("Manager coordinates") but not a row in the table | **Member 1** builds Manager core in Sprint 1 (task state machine, assignment, retries, DLQ, naive DAG executor). Member 3 plugs in the real graph; Member 10 plugs in recovery. |
| **FastAPI backend** | Required by stack | Member 1 shell; each member adds a router |
| **React/Next.js UI + WebSockets** | Required by stack; the mid-eval needs a visible demo | Member 1 builds the dashboard shell + live event stream; **each member ships one UI panel** for their subsystem |
| **PostgreSQL schema** | Persistent state | Member 1 core tables; each member adds migrations |
| **Human-in-the-loop** (approve plan, request changes) | Core claim in the guide | Gate API + states in Sprint 1; plan-approval UI in Sprint 3; review-approval UI in Sprint 10 |
| **Local LLM needed from Sprint 2, but Member 11 is last** | Circular dependency | Sprint 1 ships a thin LLM Gateway; Sprint 11 replaces its internals only |
| **End-to-end integration, observability, security hardening, demo packaging, demo** | "Plan till deployment" — and we have exactly 11 sprints for 11 people | **Split, no extra sprint:** observability + ops → M4 (S4); security hardening → M6 (S6); one-command laptop demo packaging + platform docs → M9 (S9); golden end-to-end scenarios + contract suite → M10 (S10); laptop model setup + release gate → M11 (S11) |
| **Evaluation datasets** | Every member needs gold data to show "evidence it works" | Each sprint owner builds a small gold set in `samples/` |

## B. Risks & mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | **Sprint 1 is the critical path** and the biggest scope; delay stalls 10 people | High | High | Strict Must/Stretch split; observability → Sprint 4, **all security incl. basic tokens/policy → Sprint 6**, context selective/token-budgeted views → stretch, full-stack chaos → Sprint 11; compose-stack integration tests (no testcontainers); stubs make later sprints independent of Sprint-1 stretch |
| R2 | Sequential schedule leaves members idle | High | Med | Parallel research + dataset prep from day 0 (doc 00 §F) |
| R3 | 16 GB RAM can't run stack + 8B model comfortably | Med | High | Compose `dev` profile (infra only); one model resident; `fast` 3B model; `replay` mode |
| R4 | Docker not installed / Mac Docker-Metal limitation | High (Docker missing today) | Med | Install first (doc 00); Ollama on host |
| R5 | 7–8B model quality too low for agent tasks | High | Med | Constrained JSON, programmatic checks first, narrow prompts, M4 refinement, M11 routing/fine-tune, test-feedback fix loop (71 % → 83 % on our coding set), team cloud key pool for `coder` |
| R6 | Web search flaky / blocked at demo | Med | High | Cached corpora + offline mode (Sprint 5), `replay` LLM |
| R7 | Contract drift between members | Med | High | Contracts frozen in Sprint 1, additive-only, contract tests in CI |
| R8 | Sandbox security (Sprint 8) — Docker socket exposure | Med | High | Run sandbox runner on host or via restricted socket proxy; no network; limits; documented |
| R9 | Members edit shared files → merge pain without git | Med | Med | Plug-in auto-discovery (Sprint 1 §3.5) removes every shared-file edit; one-migration-per-sprint; per-plug-in replay-cache folders; merge only owned folders |
| R10 | Mid-eval demo breaks live | Med | High | Rehearsal sprint-buffer, `replay` mode, recorded video backup |
| R11 | LLM-as-judge bias / self-preference (M10) | Med | Med | Different judge model, objective signals weighted first, calibration on gold set |
| R12 | Fine-tuning shows no gain | Med | Low | Reported as research finding; not on the critical path |
| R13 | Scope creep from Member-1 research (OTel, mTLS, Kafka, A2A…) | High | Med | Research §31 itself says defer; stretch items re-homed to Sprints 4/6/9/11 (see sprints/README.md) |
| R14 | Licensing/ToS of scraped web content | Low | Med | Respect robots.txt, rate-limit, cache only for dev/demo, cite sources |
| R15 | Team cloud keys: free quota runs out, a key is revoked, a provider limits an account, or prompts leave the laptop (Gemini free tier may use them) | Med | Med | Cloud only for selected roles; per-key cooldown + local fallback so runs never stop; `make demo-replay` needs no keys; key owners informed of the risk; private projects set `cloud_ok=false`; keys only in `.env` |

## C. Open questions for the team (answer before Sprint 1 if possible)

1. ~~Is **Member 1 = you**?~~ **Answered: yes.** Member 1 also co-signs the final release gate with Member 11.
2. Real sprint length (we assumed 1 week)?
3. Do all members have ≥16 GB RAM? (if not, `replay` mode or the LAN model host is their development path; the demo itself only runs on Member 1's laptop)
4. ~~Is a cloud-LLM fallback acceptable?~~ **Answered (2026-10-11): yes** — the product may use the team's free-tier Groq + Gemini key pool for selected roles, always with local fallback (doc 02 §2.5).
5. Do we target Python only for the Coding/Testing agents (recommended), or also JS?
6. Mid-eval date fixed? (plan assumes end of Sprint 5 + 2 buffer days)
