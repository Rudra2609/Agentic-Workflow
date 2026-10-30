# Handoff — end of Sprint 6 (Member 6: research verification + security + mid-eval readiness)

Status: **built 2026-10-18**; acceptance: `scripts/check_sprint.sh 6` (result under "Test status"). Next: the
**mid-evaluation** (Members 1–6), then Sprint 7 (Member 7, coding). The Sprint 5…1 handoffs follow below and are
still valid.

## What now works (Sprint 6)
- **Real `verify.claims`** (`backend/src/hmap/agents/verify/`, priority 100; the stub stands down). Every claim of a
  research report is checked in four layers, cheapest first:
  1. **L1** quote verbatim in the saved page + page / evidence hashes + URL (no model): 15/15 fake quotes caught;
  2. **L2** a judge of another model family says whether the quotes state the claim (asked in both orders; a changed
     number is caught by a guard too);
  3. **L3** the verifier's own searches (claim-only queries, its own search cache, cited pages excluded);
  4. **L4** conflicts with other sources (numbers, years, negation + judge).
  A documented decision table gives VERIFIED / UNSUPPORTED / CONFLICTING / NEEDS_MORE_RESEARCH with a measured
  confidence and an explanation. Benchmark (86 items, 60 seeded): accuracy 0.907, error recall 0.985, 20 % false
  alarms on clean items (`docs/members/6/eval.md`).
- **Follow-up loop:** flagged claims become research questions → `research.run` (`follow_up_of`) → re-check, one
  round by default (`HMAP_VERIFY_MAX_ROUNDS`, hard cap 3); "Request more research" in the Verification tab.
- **Verification tab:** claim table (flagged first, verdict chips), each layer in plain words, the quote next to the
  saved page, conflicting sources, follow-up steps.
- **Security layer** (`backend/src/hmap/core/policy.py`): every bus message signed with a per-agent token derived from
  a keyring (the token never travels); the Manager checks every report against a policy table, agents accept
  commands only from the Manager; refusals audited (memory + `security_audit` table); key rotation without downtime,
  expiry, revocation (`python -m hmap.core.policy …`); upload content sniffing; API write rate limit; injection
  regression suite; `scripts/security_check.sh` (secrets, leaks, pip-audit, npm audit, tests, listeners) runs in
  `check_sprint.sh` from Sprint 6 on.
- **Mid-eval readiness:** `make demo` / `make stop` (offline, agents in their own process), `scripts/demo_chaos.sh`
  (kill the agents mid-research → lease expiry → retry as a new execution; 3/3), `samples/demo/` (the three inputs),
  `scripts/demo_sprint_6.sh` (the storyline), README "What is real vs stub".

## Public interfaces added (Sprint 6)
- **Artifacts:** `verification-report` (`vr-<task_id>`, `VerificationReport`), `verification-trace` (`vt-<task_id>`).
- **Event:** `verification.completed {task_id, report_ref, research_report_ref, summary{verified, unsupported,
  conflicting, needs_more}, round, follow_up{research_task_id, verify_task_id} | null}`.
- **Inputs of `verify.claims`:** `research_report` (ref), `verify_round`, `follow_up_of_verification`, `layers`,
  `research_mode`; `stub_fail` / `stub_delay_s` honoured. With no research report: an empty report, success.
- **API:** `GET /api/verify/runs/{project}`, `GET /api/verify/runs/{project}/{task}`, `POST
  /api/verify/runs/{project}/{task}/follow-up` (`{claim_ids?, questions?}`), `GET /api/verify/table`, `GET
  /api/verify/security`.
- **Contract (additive, snapshot updated):** `Envelope.auth` (signature). `make_envelope` signs when
  `hmap.core.policy.install()` has run (the Manager and the agent runtime do it).
- **DB:** migration `006_sprint_6_verify` (`security_audit`; `MEMBER_TABLES`).
- **Config:** `HMAP_VERIFY_MAX_ROUNDS`, `HMAP_VERIFY_INDEPENDENT`, `HMAP_VERIFY_CACHE_DIR`, `HMAP_AGENT_SECRETS`,
  `HMAP_AGENT_TOKEN_TTL_S`, `HMAP_SECURITY_ENFORCE`, `HMAP_API_WRITE_RATE`, `HMAP_API_WRITE_BURST`.
- **Make:** `make demo`, `make stop`, `make security`.

## Member 1 paths changed (approved in the plan, Q1–Q4; listed for the commit message)
`core/contracts/envelope.py` (+ exported schema and snapshot), `core/runtime/worker.py`, `manager/manager.py`,
`core/config.py`, `api/app.py`, `api/routers/projects.py`, `db/tables.py`, `tests/db/test_migrations.py`,
`.env.example`, `Makefile`, `scripts/{check_sprint.sh, demo.sh, stop.sh, demo_sprint_6.{sh,py},
demo_chaos.{sh,py}, security_check.{sh,py}}`, `samples/demo/*`, `README.md`, `docs/sprints/mid-evaluation.md`,
`ownership.toml` (Member 6 `[cross_cutting]` rows). New: `core/policy.py`. Member 2's gold files were copied into
`samples/demo/`; Member 5's code is only imported.

## Member 5 replay recordings added (approved by Member 1 on 2026-10-18)
The demo's follow-up research round (Sprint 6 storyline) had no recorded model answers. With Member 1's approval,
**31 new files** were recorded into Member 5's `samples/llm_cache/research/` (476 KB; `reasoner` / `fast` answers
and embeddings of the follow-up research on the TCP-chat demo). **Additive only: none of Member 5's 539 existing
recordings was changed or removed** (checked by SHA-256 before / after); no code changed. Recorded with
`HMAP_LLM_RECORD_MISSING=research,verify scripts/demo_sprint_6.sh --record-missing` (team cloud keys + local
`nomic-embed-text` for embeddings). `scripts/precommit.sh --member 6` lists these files as Member 5's paths; this
section is the sign-off.

<details><summary>The 31 files</summary>

- `samples/llm_cache/research/06/0652bc68c2db650aafba7f01adb37523ff046173af42798304bab95621e11434.json`
- `samples/llm_cache/research/18/183a4af28961e3ffb10abb37ed3a76bfaac12778256d9c4f4279b0fabc6f3285.json`
- `samples/llm_cache/research/1d/1da228a94ce271ca99bcf11d6863ad41d5e3ed881e651e3dba3fdd03dd410ffc.json`
- `samples/llm_cache/research/24/243c9b47f001edf21a3f2ea8408a2417314da882bf52f1c363fadc69392f4646.json`
- `samples/llm_cache/research/36/3602c8194f8c6f20bc4b83d90b2cdf911e9b5c957373079a95cd1e3bc0d8ad7a.json`
- `samples/llm_cache/research/3b/3b932c553e411298f9e2268c45a2cbefe3725a4004dabf89a81e2534c92ef6fe.json`
- `samples/llm_cache/research/5e/5ee75c7fdd5ca5e221b719778a7782b87d92757eda101ed14a5894d2afbb2e0e.json`
- `samples/llm_cache/research/68/68e374111aa52755e960dade4d2ccfb67d49be20a7ba4ab2fbe326510aca9435.json`
- `samples/llm_cache/research/6c/6ca3c2e39c996e7da3d315ca56b2db847dee2743c5b75b4406669a08f7eb52b2.json`
- `samples/llm_cache/research/70/7044163acac8c46cd286b58a045ca7b7606d5ff7207ae7df910b1587db021103.json`
- `samples/llm_cache/research/74/7422352d49b2f5c84e1e07995c8a1b1c0e403f9d3b1d2d4b83664f2bfdd7997d.json`
- `samples/llm_cache/research/79/7939a1938b9dce3cf7f1b069bfd8c9770a81eadf0a1d2250578495b98c00587d.json`
- `samples/llm_cache/research/7a/7a1ad14e53645fea967d83411126d59e7f3f1252ed613860b1157c23b17a1bbf.json`
- `samples/llm_cache/research/85/85874be843b4a3ae55e67a86771b09384581ad6c84a53292e0e669bfeb46588d.json`
- `samples/llm_cache/research/85/85df08c9d86fa8565fe6aeda17675b4adf8e0076a3967db083083cd7cdb1a560.json`
- `samples/llm_cache/research/89/89ac0ec588654c3846af51fa94442717216788390e3015a3154fe10e883b8014.json`
- `samples/llm_cache/research/94/94007312d9269386f83473eb9f6bb6d309737fb28be260b8935bde112c817b49.json`
- `samples/llm_cache/research/96/96a1e684f52ab0a356899a5edc2655dc492f14a7829ac740ee33a8a0f3037c3a.json`
- `samples/llm_cache/research/9f/9f74c629a1db2a386a6ef89a49c923268d10ea36e6a5a338083273bf418e2191.json`
- `samples/llm_cache/research/b0/b07b68b348dc8d19d25dd16037e66a9929dd7f4e7666fec8bb7ceb6f1dec24b0.json`
- `samples/llm_cache/research/b2/b277ecdab2d13b4e6c425be6ba03ec1c82045173f5bddb0322946eab03bcced8.json`
- `samples/llm_cache/research/b9/b9a0580eb36947a26fe543419148bfdf615f45a4d4d599375d531c9b167537af.json`
- `samples/llm_cache/research/ca/ca4a266d40e0d526120378160b30d9b624a81652d98aede9e951ff47d1d218e7.json`
- `samples/llm_cache/research/cb/cbfe619970e1ab15afef158ea24fe2e0d72424faedd27ddd84fe7cbcbbbe2787.json`
- `samples/llm_cache/research/cc/cc30b1edafed7c3324f80deb630d1c5b2d9100e121a36731ba8ce52ef71cd574.json`
- `samples/llm_cache/research/d1/d14302447bc670a9e5e8993395c1a47d034379da37046b5611cb00cd513ad417.json`
- `samples/llm_cache/research/d6/d6dfb0eed2c7a2f05364920119a527938b1fd3569bec46923216df9b296e8a96.json`
- `samples/llm_cache/research/e4/e4079b3798b9ce7cca627df3ec864cad2f1246083363477018aa134412868207.json`
- `samples/llm_cache/research/ee/eee570cc2fad24de04eb592a78744a81a7cf351c04369c1806f3047e94110ec6.json`
- `samples/llm_cache/research/f1/f1ee26735200bdba2e7637537d3e5ac8791e28b82388cc4fe8d5b89a2d3c0f96.json`
- `samples/llm_cache/research/f7/f7a99d2e0b710df64f048135f3aa17e40157c2ba9c49960d9d0ba2238b835cb0.json`

</details>

## How the next members plug in
- **Member 7 / 9:** your agents read repositories: run `samples/verify/injection/repo/` through your reader in
  `tests/verify/security/test_injection.py::test_repository_entry_points_are_switched_on_when_real` (it fails on
  purpose once your capability is real, until you add it) and handle finding F3.
- **Member 10:** `verification.completed` + the `verification-report` are review evidence; the M5 → M6 pair belongs
  in the contract suite.
- **Member 11:** `samples/verify/benchmark.jsonl` + `tests/verify/eval/run_eval.py --local-only` measure a judge model;
  locally the judge is the researcher's model (a routing decision).
- **Member 2:** findings **F1 / F2** (hidden PDF / DOCX text becomes a requirement) — `docs/members/6/security-report.md`.

## Known limitations (Sprint 6)
- L3 retrieval is weak offline (5 of 13 contradictions found by the verifier's own search).
- 20 % false alarms on clean items (2 judge-strict, 2 "unsure" from the position check).
- The demo's follow-up research (now recorded, see above) finds nothing new in the offline corpus: it searches two
  more rounds, stops on "low novelty" and keeps the same 9 findings, so the re-check gives the same verdicts as round
  0. Online (`HMAP_RESEARCH_MODE=online`) it can search the web for the gap questions.
- In replay, the two extra demo inputs (`lab_manual_scanned.pdf`, `requirements.docx`) have no recordings under their
  demo names: Member 2's extraction uses its rule / OCR fallbacks for them (the storyline itself replays with 0
  misses). Recording them would add files to Member 2's `samples/llm_cache/doc_intel/` (not done; needs approval).
- One shared keyring per laptop; no `agent.registered` reply (security-report F5, F6).

## Deferred
| Item | Owner |
|---|---|
| F1 / F2 hidden text in PDF / DOCX | Member 2 |
| F3 repository-text injection patterns | Members 7 / 9 (shared sanitizer: Member 5) |
| Stretch: multi-judge ensemble, held-out calibration, temporal validity, claim-to-claim consistency | Member 6 backlog / Member 10 |
| Full demo packaging (reset / seed / config reference) | Member 9, Sprint 9 |

## Test status (Sprint 6)
`scripts/check_sprint.sh 6` → **PASS** (2026-10-18): secret scan, ruff (src, tests, scripts), mypy (206 files), **1032
backend tests** with Docker infra (RabbitMQ + Postgres + pgvector; 2 skipped = Members 7 / 9 entry points, 3 xfailed
= known findings F1–F3), frontend lint / typecheck / **137 tests** / build, **security check PASS** (secrets, leaks,
pip-audit, npm audit, security tests, loopback-only listeners), `scripts/demo_sprint_6.sh` in memory **and** on
RabbitMQ + Postgres with agents in a separate process. After the Member 5 recordings were added: the demo replays
with **0 research / verify replay misses** (twice, identical verdicts), security check PASS. Also: `scripts/demo_chaos.sh` 3/3; `make demo` from a clean
`make_handoff` copy + the storyline: PASS; benchmark replay = recording (0 network calls).

---

# Handoff — end of Sprint 5 (Member 5: autonomous research)

Status: **accepted by `scripts/check_sprint.sh 5` on 2026-10-14** (all checks PASS). Next: Sprint 6, Member 6
(research verification + security + **the mid-evaluation readiness gate**: the mid-evaluation now comes after Sprint 6).
The Sprint 4, 3, 2 and 1 handoffs follow below and are still valid.

## What now works (Sprint 5)
- **Real `research.run`** (`backend/src/hmap/agents/research/`, priority 100; the stub stands down). A plan's
  research step (questions from Member 3's plan) or a question asked in the dashboard becomes a **cited
  `ResearchReport`**:
  1. sub-questions, each with search queries;
  2. search in Wikipedia, arXiv, DuckDuckGo and the offline corpus;
  3. polite, safe fetching;
  4. cleaning and hybrid indexing (keywords + embeddings, pgvector on Postgres);
  5. explainable source scores;
  6. quotes **checked word for word** against the saved page;
  7. coverage per sub-question, a clear stop rule, and claims that each cite evidence.
- **Offline by default** (`HMAP_RESEARCH_MODE=cached`): the committed corpus (`samples/research/corpus`, 105
  freely licensed pages) and search results replace the web; the demo and every test run with Wi-Fi off.
- **Safety**:
  - an SSRF guard: no localhost / private addresses, re-checked after every redirect;
  - robots.txt and polite rate limits;
  - prompt-injection hygiene: hidden HTML and AI-directed lines removed, page text wrapped as untrusted, page text
    never becomes a query;
  - adversarial pages tested.
- **Research tab** on every project: sub-questions with coverage bars, cited findings (click [n] to see the quote
  highlighted in the saved page), sources with their score breakdown, how each round searched, and the written
  report. You can ask your own questions there.
- **Measured** (details in `docs/members/5/eval.md`): 
  - On 10 gold questions (offline): fact coverage **0.65** (hybrid retrieval; dense 0.62, keyword 0.58; no model
    0.28).
  - Citation validity **100 %** (64/64; 0 invented quotes in any report, 9 of 329 proposed quotes refused by the
    check).
  - 3.5 findings and 2.4 sources per question; ~8 k tokens and 6 model calls; ~15 s live.
  - Pure replay = recording, 0 network calls.
  - Member 4's refinement made no difference to fact coverage.
  - A local-only run (qwen3.5:9b) found nothing (the model returned no quotes).

## Public interfaces added (Sprint 5)
- **Artifacts:** `research-report` (`ResearchReport`, first in the result; a refined report is its next version),
  `research-trace` (`rt-<task_id>`), `research-brief` (`rb-<task_id>`), `research-page` (`rp-<sha256[:32]>`: the
  cleaned page text the quotes were checked against).
- **Contract (additive, snapshots updated):** `SubQuestion`, `ResearchReport.sub_questions`,
  `Source.{provider, kind, retrieved_at, content_sha256, page_artifact}`, `ResearchBrief.follow_up_of`.
- **Event:** `research.completed {task_id, report_ref, stop_reason, claims, evidence, sources, coverage, covered,
  sub_questions}`.
- **API:** `GET /api/research/runs/{project_id}[/{task_id}]`, `GET /api/research/pages/{project_id}/{artifact_id}
  ?task_id=` (text + the evidence spans), `POST /api/research/runs/{project_id}` (questions), `GET
  /api/research/providers`.
- **Inputs of `research.run`:** `research_questions`, `budget` (`ResearchBudget`), `follow_up_of` (a
  `research-report` ref), `research_mode`. Failure-injection hooks `stub_fail` / `stub_delay_s` are honoured, as the
  stub did (chaos tests, the mid-eval failure injection).
- **DB:** migration `005_sprint_5_research` (`research_chunks`; `MEMBER_TABLES` in `hmap/db/tables.py`).
- **Config:** `HMAP_RESEARCH_MODE` (`cached` | `online` | `local`), `HMAP_RESEARCH_PROVIDERS`,
  `HMAP_RESEARCH_CACHE_DIR`, `HMAP_RESEARCH_MAX_FETCH_MB`, `HMAP_RESEARCH_RATE_PER_HOST`.
  `HMAP_LLM_RECORD_MISSING` now fills missing embeddings too.
- **Libraries:** `ddgs` 9.16, `trafilatura` 2.2.0, `protego` 0.7, `rank-bm25` 0.2.2.

## How the next member plugs in (Member 6)
- **The report:** listen to `research.completed`, or take the `research-report` ref the Manager hands the verify
  step (it depends on the research step). Every `Evidence` has `quote`, `url`, `content_sha256` and `page_artifact`.
  - **L1 (mechanical) check:** load the page artifact, check `sha256(page.text) == content_sha256`, then
    `hmap.agents.research.quotes.locate(quote, page.text)`.
  - Claims cite evidence ids; `sub_question` links evidence to the plan of the research.
- **Independent retrieval (6.4):** `from hmap.agents.research.providers import get_providers`, plus `Fetcher` and
  `index.HybridIndex`. Write your own query generator; do not reuse the researcher's queries.
- **Follow-up research (6.8):** create a `research.run` task with `inputs={"follow_up_of": <report ref>,
  "research_questions": [gaps]}`. The agent keeps the earlier evidence (same ids) and researches only the gaps.
  Bound the loop yourself.
- **Injection suite (6.13):** reuse `samples/research/adversarial/` (4 poisoned pages) and
  `tests/research/test_adversarial_pages.py`.
- **Mid-evaluation readiness (6.21–6.24):** `scripts/demo_sprint_5.sh` already runs upload → plan → approve →
  research (offline) → stubs → complete. Add your verification step and `demo_chaos.sh`.
- Before handing back: `scripts/precommit.sh --member 6 --base <this handoff folder>`.

## How later members plug in
- **Member 7:** `hmap.agents.research.index.HybridIndex` (chunk + embed + hybrid search; memory or Postgres) can
  index any text.
- **Member 10:** the report as review evidence; the M5 → M6 pair in the contract suite.
- **Member 11:** `samples/research/gold/questions.jsonl` + `tests/research/eval/run_eval.py` (fact coverage,
  citation validity) for the model benchmark; `--local-only` never records.

## Known limitations (Sprint 5)
- **Local-only research is weak:** qwen3.5:9b returned no quotes in a 3-question run, so everything ended
  `no_sources`. With keys, the cloud models do the work. Recommended next step (Member 11 or a later pass): a
  rule-quote fallback when the model returns none, or a larger local `reasoner` for research.
- **The offline corpus** is only what one online harvest found and may be redistributed (76 of 105 pages are
  Wikipedia). Questions whose answers live in blogs or third-party docs cannot be answered offline (e.g. "pytest +
  coverage in one command").
- **Claim support is checked only loosely** (the citation check needs shared words); a marginal page can count
  towards "answered". Entailment is Member 6's job.
- **Questions only the team can answer** ("which Python version do we use?") get "No sourced answer found".
- **DuckDuckGo** rate-limits; Wikipedia and arXiv carry most online searching. `online` mode sends the questions
  (from private documents) to search engines, which is why `cached` is the default.
- **Recordings take 11 MB** (`samples/llm_cache/research`, mostly embeddings).

## Test status (Sprint 5)
`scripts/check_sprint.sh 5` -> PASS (2026-10-14): secret scan, ruff, mypy, 968 backend tests (incl. integration on
RabbitMQ + Postgres + pgvector; none skipped), frontend lint / typecheck / 130 tests / build, and
`scripts/demo_sprint_5.sh` in memory and on RabbitMQ + Postgres with agents in a separate process (same results; 0
missing recordings). Member 5's own tests: `backend/tests/research/` (57), `frontend/src/features/research/` (9);
Member 1 tests changed: `tests/db/test_migrations.py`, `tests/core/llm/test_gateway.py` (+2). Demo:
`scripts/demo_sprint_5.sh` (`--live` for real models, `--record-missing` to fill gaps).

---

# Handoff — end of Sprint 4 (Member 4: self-reflection and refinement + observability)

Status: **accepted by `scripts/check_sprint.sh 4` on 2026-10-14** (all checks PASS).

## What now works (Sprint 4)
- **"Check and improve results"** (project setting, off by default; per task `inputs["refine"]`). With it on:
  1. Member 2's requirements and Member 3's plan are checked, code checks first (quotes found in the document,
     marks add up, priority matches the modal verb, the plan is valid and covers every requirement), then a judge
     model with a rubric.
  2. Problems are labelled with 10 kinds × 4 severities and revised only where they were flagged (targeted).
     Reflexion notes switch to a full rework when the same kind of problem comes back.
  3. The loop stops by a clear rule: score ≥ 0.9, no major issue, plateau, budget, or 3 rounds.
  4. The best version is kept and stored as the next version of the same artifact. Members 2 and 3's folders are
     untouched: they are refined through the new runtime hook `Plugin.refiners`.
- **Refinement tab** on every project: each check's rounds, problems grouped by kind with evidence, score curve,
  stop reason, and what changed (diff). The dashboard toggle is on project creation and in the project's menu.
- **Measured** (details in `docs/members/4/eval.md`):
  - On weaker, rule-made outputs: requirements F1 0.959 → 0.976, constraints 0.842 → 0.889, plan must-have
    dependencies 0.886 → 0.971 (long lab 19/27 → 27/27).
  - On the already-good recorded cloud outputs: almost no change (honest null).
  - Error labelling: 97.5 % on 80 labelled issues (rules, then the `classify` model).
- **Observability** (`make obs-up`, one command, 127.0.0.1 only, memory-capped):
  - One trace per task in Jaeger: Manager → bus → agent → refinement → model calls. Retries and replays land in the
    same trace.
  - Prometheus `/metrics` on the API and the agents process.
  - A Grafana dashboard (queues, task states, retries / dead letters / replays, heartbeats, model latency / tokens /
    errors, refinement, RAM).
  - 6 alert rules, each linked to `docs/members/4/runbook.md`.
- **Operations page:**
  - "Why did this task fail?" gives a verdict, the facts, every attempt, and the trace link. It is checked on every
    chaos scenario.
  - The dead-letter list.
  - **"Replay as a new attempt"**: needs a reason and a confirmation, creates a new execution with a fresh retry
    budget, and writes the `task.replayed` event.
- **Load / soak** (`infra/observability/load/soak.py`, stub agents): 540 projects (4 320 steps) in 3 minutes on
  RabbitMQ + Postgres, 0 failures, p95 4.0 s per 8-step project, 185 MB RSS.

## Public interfaces added (Sprint 4)
- **Library** `hmap.agents.refine`:
  - `Refiner`, `ProgrammaticCritic`, `LLMRubricCritic` + `Rubric` / `Criterion`, `CompositeCritic`.
  - `TargetedReviser` / `FullRewriteReviser` / `SchemaReviser` / `StrategicReviser`.
  - Stop rules `MaxIters`, `Threshold`, `NoCritical`, `Plateau`, `Budget`, `TestsPass`, `any_of` / `all_of`,
    `default_policy()`, `best_index`.
  - `ReflectionMemory`, `IssueClassifier`, `RefinementMixin` / `@refinable` / `RefineSetup`, `CapabilityAdapter`.
  - Guide: `docs/members/4/integration.md`.
- **Runtime hook (Member 1 area):** `Plugin.refiners: dict[capability, RefineAdapter]`. The worker runs the
  adapter on a successful result when `task.refine` is true; on error the original result is reported.
  `AgentContext.progress(..., artifact_refs=)`.
- **Manager (Member 1 area):**
  - `ProjectRecord.refine` (API create / patch `refine`), copied into `TaskAssign.refine` (task `inputs["refine"]`
    wins).
  - `Manager.replay_dead_letter(task_id, operator=, reason=)` with `OPERATOR_TRANSITIONS`
    (`DEAD_LETTERED → READY`, `BLOCKED → CREATED`), `TaskRecord.replays`, `InvalidTaskState`.
  - Event `task.replayed`.
- **Events:** `refine.iteration`, `refine.stopped` (from the refine plug-in), `task.replayed`.
- **Artifacts:** `refinement-trace` (`rf-<task_id>`), `refine-output`, `refinement-progress`, `reflection-memory`.
- **Capability:** `refine.run` (RefineAgent: any JSON artifact + a rubric; `requirement-set` / `task-graph` use the
  built-in adapters).
- **API:** `/api/refine/policy`, `/api/refine/runs/{project_id}[/{run_id}[/diff?a=&b=]]`,
  `POST /api/refine/runs/{project_id}`; `/api/ops/overview|failures|explain/{task_id}|dlq`,
  `POST /api/ops/replay/{task_id}`; `GET /metrics`.
- **Telemetry** `hmap.obs`: `span(name, attrs)` (attributes filtered by `safe_attrs`), `task_trace_id`, metrics
  registry. Off unless `HMAP_OTEL_ENDPOINT` is set.
- **Config:**
  - `HMAP_REFINE_DEFAULT`, `HMAP_OTEL_ENDPOINT`, `HMAP_METRICS_PORT` (9464), `HMAP_METRICS_INTERVAL_S`,
    `HMAP_RETRY_DELAYS_S`, `HMAP_LLM_RECORD_MISSING=<plugin,...>` (replay, and record only the missing answers).
  - `HMAP_GRAFANA_PASSWORD`, `HMAP_JAEGER_URL` / `HMAP_GRAFANA_URL` / `HMAP_PROMETHEUS_URL`.
  - `make obs-up` / `obs-down` / `obs-open`.
- **Libraries:** `opentelemetry-api` / `-sdk` / `-exporter-otlp-proto-http` 1.45.1, `prometheus-client` 0.26,
  `psutil` 7.2.2. Containers: Jaeger 2.22.0, Prometheus 3.13.4, Grafana 13.0.1.

## How the next member plugs in (Member 5)
- **Synthesis with citations (item 5.9)** in 7 lines (executed in `backend/tests/refine/test_dry_run_member5.py`):

  ```python
  class ResearchAgent(RefinementMixin, BaseAgent):
      def refine_setup(self, task, ctx):
          return RefineSetup(artifact_type="research-report", load=json.loads,
                             critics=[ProgrammaticCritic(check_citations), LLMRubricCritic(RESEARCH_RUBRIC)],
                             reviser=TargetedReviser())
      # end of handle():  return await self.refine(task, ctx.result([ref]), ctx)
  ```
- `check_citations(report, task_input) -> list[Issue]`: one `Issue` per claim without an evidence id or with an
  unverified quote, with `location="/claims/3"`. Code finds these, so it runs first and overrules the judge. Use the
  judge rubric only for completeness.
- Record the refine calls with `HMAP_LLM_RECORD_MISSING=<your plugin>` (cloud first), so tests and the demo replay
  offline.
- Add spans with `hmap.obs.span("research.search", {"hmap.results": n})`: ids and counts only, never query text or
  page content.
- Before handing back: `scripts/precommit.sh --member 5 --base <this handoff folder>`.

## How later members plug in
- **Members 7 / 8:** use `StopPolicy` on its own (`any_of(TestsPass(fn), Plateau(...), MaxIters(4))`) and
  `ReflectionMemory` for the debug loop. **Members 6, 9, 10:** `Refiner` with your own programmatic critic.
- **Member 10:** the Operations explain view and `replay_dead_letter` are the manual counterpart of your recovery
  slot. Reuse `hmap.agents.ops.explain.explain()` for the "why".
- **Member 11:** taxonomy-labelled issues in `samples/refine/taxonomy_gold.jsonl` (+ `taxonomy_eval.py`) for the
  classifier; `infra/observability/load/soak.py` for the release gate.
- **Mid-evaluation:** a project with the toggle on vs off (Refinement tab), and `make obs-up` + `scripts/demo_sprint_4.sh`
  with `DEMO_OBS=1` for Jaeger / Grafana during failure injection.

## Known limitations (Sprint 4)
- The gain on good outputs is near zero. The clear gains are on weaker (rule-made) outputs, and on one messy
  brief's priority with the cloud producer.
- Locally the judge is the same `qwen3.5:9b` as the producer: a local-only run improved nothing (20–60 s per judge
  call; long cases stopped on the 180 s budget; eval.md §5). The gains need the cloud judge.
- Recorded answers cover the gold sets and the demo. On other inputs in replay mode the judge is skipped (code
  checks only).
- When the improved requirements are used, the planner replays have no recording for the new requirement set, so
  in replay mode Member 3's rules make that plan (one `ReplayMiss` log line).
- Jaeger keeps traces in memory, and there is no Alertmanager: alerts show in Prometheus / Grafana only.
- The Manager handles one message at a time (prefetch 1). That is the throughput limit seen in the soak test
  (≈ 24 steps / s on RabbitMQ + Postgres).

## Test status (Sprint 4)
`scripts/check_sprint.sh 4` -> PASS (2026-10-14, run with `DEMO_OBS=1` and `make obs-up`): secret scan, ruff,
mypy, 909 backend tests (incl. integration on RabbitMQ + Postgres; none skipped), frontend lint / typecheck / 121
tests / build, and `scripts/demo_sprint_4.sh` in memory and on RabbitMQ + Postgres with agents in a separate process
(Jaeger trace and firing alert checked). Member 4's own tests: `backend/tests/refine/` (64), `tests/obs/` (6),
`tests/ops/` (6), `tests/manager/test_replay_dead_letter.py` (5), `tests/core/runtime/test_worker_refine.py` (7),
`frontend/src/features/{refine,ops}/` (15). Demo: `scripts/demo_sprint_4.sh` (`--live` for real models;
`DEMO_OBS=1` adds the Jaeger / Prometheus checks).

---

# Handoff — end of Sprint 3 (Member 3: planning and task decomposition)

Status: **accepted by `scripts/check_sprint.sh 3` on 2026-10-13** (all checks PASS).

## What now works (Sprint 3)
- **Real `plan.generate` agent** (`backend/src/hmap/agents/planning/`, priority 100): the stub stands down. Upload →
  requirements → plan → approval with no manual step (the `pipeline` plug-in is unchanged).
- **Plans:** a template spine (research → verify → design → build / test per upload folder → documents → final
  review), the build and test steps from the `reasoner` model per part (≤ 15 requirements per call) or from rules
  when there is no model; every requirement covered by a step or flagged ("needs a person": a live demo, uploading
  to the portal); capabilities only from the six pipeline capabilities; acceptance criteria on every step (the
  constraints too); research questions on research steps; dependencies from the template, data flow, folders that
  name each other ("use the schema from Part A") and the model; validated and repaired by code (cycles, orphans,
  one final review, size ≤ 40); transitive reduction; parallel stages, critical path, slack, priorities.
- **Executor** (plug-in slot `executor`): a step starts when its dependencies are done; at most
  `HMAP_PLAN_MAX_PARALLEL` (4) plan steps per project at once, critical path first. Without the plug-in the naive
  executor stays.
- **Replanning:** feedback ("don't use threads"), failed steps or edited requirements → the next plan version;
  finished and running steps are kept (same ids → the Manager keeps their tasks and results); feedback after
  everything finished becomes a change-request step and the documents / review run again.
- **Plan tab** on every project: React Flow graph (live states, critical path), steps, roadmap, coverage matrix,
  versions with diffs; approve / reject with a comment; edit (add / remove / change steps, drag to connect); "Change
  plan…"; banners for edited requirements, failed steps, questions before approval and work only a person can do.
- **Quality on the gold set** (9 cases, `samples/planning/`, details in `docs/members/3/eval.md`): every plan valid,
  100 % covered or flagged, flags exactly right, no invented capability; dependency F1 0.93 and must-have
  dependencies 0.94 with the cloud model (rules alone: 0.91 / 0.89).

## Public interfaces added (Sprint 3)
- **Artifacts** from `plan.generate`: `task-graph` (`TaskGraph`, first) and `plan-report` (`PlanReport`, artifact id
  `<graph id>-report`: method, model, fallbacks, repairs, warnings, flagged requirements, deliverables → steps,
  questions, schedule). Edits and replans add versions of the same two artifacts; `TaskGraph.version` = the
  artifact version = the Manager's `graph_version`.
- **TaskGraph shape:** `tasks` are executable leaf steps only; the hierarchy (phase → part → feature group) is
  `roadmap.phases` with the new additive `Phase.parent_id` (snapshot accepted). Spine ids: `research`, `verify`,
  `design`, `review` (a re-run review after a replan: `review-v3`); other steps `T1..`.
- **Event:** `plan.approved {project_id, plan_ref, graph_version, auto}` (also for auto-approved projects).
- **API** (`/api/planning`, owner only, 404 otherwise): `GET|PUT /plan/{project_id}` (PUT needs `base_version`;
  stale → 409; problems → 422 `{message, issues}`), `POST /plan/{project_id}/approve` (`graph_version`; old version →
  409), `POST /plan/{project_id}/replan` (`feedback`, `failed`), `GET /plan/{project_id}/roadmap.md`,
  `GET /capabilities`.
- **Manager (Member 1, for everyone):** `Manager.replace_graph(project_id, graph, require_approval=True)` (also on
  `ManagerHandle`); `TaskRecord.replaced` (ignored by the executor and the outcome; hidden in the dashboard);
  `approve(..., graph_version=)` + `StaleGraph`; `approval.decided` carries `graph_version`; core
  `POST /api/projects/{id}/approval` accepts `graph_version`.
- **Config:** `HMAP_PLAN_MAX_PARALLEL` (default 4), `HMAP_STUB_DELAY_S` (default 0; demos).
- **Libraries:** `networkx==3.6.1`, dev `hypothesis`, frontend `@xyflow/react` 12.12.0.

## How the next member plugs in (Member 4)
- **Critics for plans:** `hmap.agents.planning.validate.validate_plan(graph, requirement_set, flagged=...)` returns
  `Issue{code, severity, message, task_id, requirement_id}` (errors and warnings) — a programmatic critic;
  `hmap.agents.planning.coverage.coverage(tasks, rs, flagged)` gives covered / flagged / missing.
- **Producer / reviser:** `hmap.agents.planning.pipeline.make_plan(rs, llm, ...)` produces a plan;
  `replan.replan(graph, rs, states={}, feedback=<critique text>, llm=...)` is a targeted revision that never touches
  frozen steps; `pipeline.finalize` re-validates any changed plan.
- **Ablation data:** `samples/planning/gold/` (inputs + reference plans) and `backend/tests/planning/eval/`
  (`run_eval.py`, `metrics.score_plan`): validity, coverage, step matching, dependency P/R/F1, must-edge recall.
  Recorded answers: `samples/llm_cache/planning/` (prompt v2).
- Wire refinement behind `refine=true` without editing the planner's internals: wrap `make_plan` / `replan` in your
  adapter (`agents/refine/adapters/`), as Sprint 4 item 4.10 says.
- Before handing back: `scripts/precommit.sh --member 4 --base <this handoff folder>`.

## How later members plug in
- **Member 5:** every `research.run` step carries `research_questions`; the task's `inputs` hold
  `requirement_ids`, `phase`, `plan_task_id`, `graph_version`.
- **Member 10:** `plan.replan` (create a task with the current `task-graph` + `requirement-set` refs and
  `inputs={feedback, failed, states}`) or call `Manager.replace_graph` from the recovery slot; the coverage matrix is
  in every `TaskGraph`.
- **Member 11:** "M3 validity" for the benchmark = `run_eval.py` (`--mode live --local-only` never records).

## Known limitations (Sprint 3)
- Recorded answers are Groq `gpt-oss-120b` (Gemini answered 503 on the recording day); two replanning scenarios are
  recorded, the demo's own replan is not (replay demos change that plan by rules).
- The local model takes ~2.5 minutes per call on the demo laptop (1–3 calls per plan); the cloud takes seconds.
- Effort estimates order the work; they are not promises. Human-only work is recognised by phrases plus the model.
- A requirement edit does not replan by itself (the Plan tab offers "Update the plan").
- The gold set and reference plans are ours; step-matching scores depend on how finely we split the references.

## Test status (Sprint 3)
`scripts/check_sprint.sh 3` -> PASS (2026-10-13): secret scan, ruff, mypy, 812 backend tests (incl. integration on
RabbitMQ + Postgres; none skipped), frontend lint / typecheck / 105 tests / build, and `scripts/demo_sprint_3.sh` in
memory and on RabbitMQ + Postgres with agents in a separate process. Member 3's own tests: `backend/tests/planning/` (57),
`backend/tests/manager/test_replace_graph.py` (4), `frontend/src/features/planning/` (15: logic + DOM). Demo:
`scripts/demo_sprint_3.sh`.

---

# Handoff — end of Sprint 2 (Member 2: document intelligence)

Status: **accepted by `scripts/check_sprint.sh 2` on 2026-10-12** (all checks PASS). Next: Sprint 3, Member 3 (planning and task decomposition).
The Sprint-1 platform handoff follows below this section and is still valid.

## What now works (Sprint 2)
- **Real `document.extract` agent** (`backend/src/hmap/agents/doc_intel/`, plug-in priority 100): the stub stands
  down automatically. Upload -> requirements -> plan without manual steps (the `pipeline` plug-in is unchanged).
- **Reads** native PDF (columns, running headers/footers, footnotes, tables), DOCX (styles, lists, tables), Markdown
  and text, scanned PDFs and photos. A page without a text layer goes to OCR: the vision model (Gemini, through the
  team key pool) first, local Tesseract second. Native PDFs never trigger OCR.
- **Extracts** requirements, constraints, deliverables and marking criteria. Marks, totals and rubric levels are read
  from tables by code; the `reasoner` model extracts the rest per section-sized chunk. Every item quotes its source
  sentence, and the quote is checked against the document. Items from folders keep their folder ("Part A").
- **Checks:** the criteria must add up to the stated total (otherwise `total_marks` is withheld and a question is
  asked); unverifiable quotes lower the confidence; anything unclear goes to `open_questions`. If the model fails,
  the chunk falls back to keyword rules and the set says so.
- **Dashboard tab "Requirements"** on every project: grouped by folder, confidence in words, open questions,
  marking scheme, inline edit / add / remove, saved as a new version (old versions kept), and a source view that
  outlines the sentence on the page image (PDF, scan, photo) or highlights it in the text (DOCX, text).
- **Quality on the gold set** (10 authored documents, `samples/doc_intel/`; details in `docs/members/2/eval.md`):
  requirements F1 0.98, deliverables 1.00, constraints 0.91, marking criteria 0.98, rubric marks 100 %, priority
  0.94 (cloud models, replayed offline; Tesseract for scans: 0.974 words). Rules alone: requirements F1 0.96.
- **Confirm** per requirement (or "Confirm all") marks it as checked by a person (confidence 1.0), saved as a new
  version. Developer mode shows which model answered each part, quote checks and the OCR engine.

## Public interfaces added (Sprint 2)
- **Artifacts** from `document.extract`: `requirement-set` (`RequirementSet`, first) and `document-model`
  (`DocumentModel`: pages, blocks with page / bbox / section path / text offsets, tables).
- **Contract (additive):** `SourceRef.folder`. Snapshot accepted.
- **Event:** `project.requirements_ready {project_id, task_id, requirement_set_ref}`.
- **API** (`/api/doc_intel`, owner only, 404 otherwise): `GET|PUT /requirements/{project_id}` (PUT needs the
  `base_version`; a stale one gets 409), `GET /document-model/{project_id}`,
  `GET /pages/{project_id}/{artifact_id}/{page}` (PNG).
- **LLM gateway (Member 1, for every member):** `ctx.llm.read_images(prompt, images)` (role `vision`, cloud only,
  raises `VisionUnavailable` for local-only projects or without keys; `FakeLLM.on_vision(...)` for tests);
  `HMAP_OLLAMA_NUM_CTX` (default 8192; Ollama's own default of 4096 cut long prompts). Fixed for everyone: Gemini
  never got seeded calls (`seed` is rejected, now not sent) and thinking models' hidden reasoning cut answers off
  (reasoning is now off / low unless `think=True`).
- **`DocumentModel.extraction`:** which model answered each part, quote checks, OCR engines, prompt version.
- **Frontend (Member 1):** feature folders may use `_` (`frontend/src/features/doc_intel/`), and vitest also runs
  `src/features/**/*.test.ts`.

## How the next member plugs in (Member 3)
- Your `plan.generate` task's `artifact_refs` hold the `requirement-set` and the `document-model` artifacts. Take
  the one with `artifact_type == "requirement-set"` (`ctx.get_json(ref, RequirementSet)`).
- Guarantees: every requirement has `id` (R1..), `text`, `type`, `priority` (must/should/could), `source_ref`
  (with `folder` for multi-part uploads) and `confidence` (1.0 confirmed by a person, 0.95 table or verified and
  agreed by the rules, 0.9 verified, 0.7 approximate, 0.6 rules only, 0.4 unverified). Items from a list under a
  lead-in ("your code needs to support:") are separate requirements. `total_marks` is set only when the criteria add up to it. Treat each folder as one part of
  the work, and show `open_questions` before approval.
- People can edit the requirements in the UI after the plan was made: the newest version is
  `GET /api/doc_intel/requirements/{project_id}`. "Run again" re-extracts.
- `project.requirements_ready` is emitted for the UI and for you; the `pipeline` plug-in already starts your task.
- Start with `docs/sprints/sprint-03-*.md` and `CONTRIBUTING.md` §3. Before handing back:
  `scripts/precommit.sh --member 3 --base <this handoff folder>`.

## Known limitations (Sprint 2)
- Without the cloud, scans are read by Tesseract (installed on the demo laptop; weaker on ruled tables).
- Recorded answers come from Groq, not Gemini (its free daily quota ran out); no vision answers are recorded yet.
- The local model is slow on the demo laptop (about 2.5 minutes per chunk); the cloud route takes seconds.
- OCR and chunk answers are cached in the agent's memory only (cached text must not outlive a deleted project).
- The gold set is ours and was used while tuning the prompt; expect lower scores on real documents.
- A human edit does not re-plan automatically.

## Test status (Sprint 2)
`scripts/check_sprint.sh 2` -> PASS (2026-10-12, final): secret scan, ruff, mypy, 751 backend tests (incl.
integration on RabbitMQ + Postgres and the Tesseract test; none skipped), frontend lint / typecheck / 90 tests /
build, and `scripts/demo_sprint_2.sh` in memory and on RabbitMQ + Postgres with agents in a separate process.
Member 2's own tests: `backend/tests/doc_intel/` (55) and `frontend/src/features/doc_intel/logic.test.ts` (7).
Scores: `docs/members/2/eval.md`.

---

# Handoff — end of Sprint 1 (Member 1: communication layer, Manager core, platform skeleton)

Status: accepted by `scripts/check_sprint.sh 1` on 2026-10-11 (all checks PASS).

## What now works
- Stub agents for all 9 capabilities exchange validated messages over **RabbitMQ**. Task state lives in **PostgreSQL**
  (transactional outbox, inbox dedup, CAS on `state_version`), and artifacts are write-once files with SHA-256.
- Manager: guarded task state machine, assignment, classified retries with backoff → dead-letter queue, watchdog
  (leases, timeouts), DAG executor, hooks, cancellation.
- Approval is per project. Either a human approves the plan, or **auto mode** (the default in the dashboard) shows the
  requirements and plan and continues on its own. A red **Stop** button cancels all unfinished work at any time.
- Default pipeline: **upload → document.extract → plan.generate → approval → all plan tasks → COMPLETED**.
- LLM gateway: roles, modes `live | record | replay | fake`, schema-constrained JSON with repair, per-plug-in replay
  cache, team cloud key pool (Groq/Gemini, local fallback). Checked live against Ollama `qwen3.5:9b`.
- **Accounts and private workspaces:** sign up, sign in/out, sessions, profile, password change and reset. Every
  project has an owner, and the API checks it on every request: projects, runs, tasks, files, events, the live
  WebSocket and dead letters. Someone else's project answers 404, exactly like a missing one. Two-user isolation is
  tested against the backend.
- **Runs:** typing a goal or uploading a document starts a numbered run. "Run again" starts a new one, and earlier
  runs, tasks and files stay in the history. Projects can be archived or deleted (deletion stops running work and
  erases the files).
- **Dashboard redesign (Next.js):**
  - pages: sign-in pages, a workspace ("What would you like your AI team to do?"), a project workspace (pipeline
    stages, plan dependency graph, step inspector, requirements, results and files, run history), AI team,
    Activity, Issues and Settings;
  - light/dark/system themes on design tokens;
  - Simple and Developer modes;
  - honest labelling of placeholder (stub) agents and their sample output.
- Team tooling: `make precommit`, regression attribution ("it wasn't me"), ownership check, contract snapshot,
  plug-in conformance tests, secret scan, handoff snapshots.

**Demo (one command):** `scripts/demo_sprint_1.sh` (in memory, ~10 s). On the real stack:
`make infra-up`, then `DEMO_SPLIT=1 HMAP_BUS=rabbitmq HMAP_STORE=postgres scripts/demo_sprint_1.sh`.
**Live, with the UI:**
1. `make infra-up`
2. `HMAP_BUS=rabbitmq HMAP_STORE=postgres HMAP_RUN_AGENTS=false make api`
3. `HMAP_BUS=rabbitmq HMAP_STORE=postgres make agents`
4. `cd frontend && npm run dev`
5. Open http://localhost:3000 and create an account. Or run `scripts/seed.sh` and sign in as the seed account
   (`demo@example.test` / `hmap local walkthrough` by default, local demo only).

Without Postgres (`HMAP_STORE=memory`), accounts and projects are forgotten when the API restarts.

## Public interfaces added
- **Contracts** (`backend/src/hmap/core/contracts/`; 31 JSON Schemas exported by `make schemas` to
  `backend/src/hmap/core/contracts/schemas/`, frozen in `backend/tests/contracts/snapshots/`):
  - the envelope and 15 message types: `task.assign|ack|started|progress|result|completed|cancel`, `error`,
    `retry.request`, `revision.request`, `feedback`, `context.request`, `agent.register|heartbeat|deregister`;
  - cross-member types: `RequirementSet`, `TaskGraph`, `RefinementSpec`, `RefinementTrace`, `ResearchBrief`,
    `ResearchReport`, `VerificationReport`, `CodeChangeSet`, `TestReport`, `DocBundle`, `ReviewReport`, `ModelSpec`,
    `RouteDecision`, `BenchmarkResult`;
  - additive change (snapshot accepted): `task.assign.cloud_ok` (default true). False means a local-only project;
    the runtime already gives such a task a never-cloud `ctx.llm`, so **always call models through `ctx.llm`**,
    never through a client you build yourself;
  - `CAPABILITY_OUTPUTS` maps each capability to its output artifact type.
- **Capabilities:** `document.extract`, `plan.generate`, `research.run`, `verify.claims`, `code.implement`,
  `test.run`, `docs.generate`, `review.final`, `echo`.
- **Events** (topic exchange `hmap.events`):
  - `task.*` (created … dead_lettered), `agent.registered|offline|recovered`, `artifact.created`,
    `context.updated`;
  - `project.created|planning|executing|completed|failed`, `document.uploaded`, `approval.requested|decided`;
  - cross-member events: `project.requirements_ready`, `plan.approved`, `research.completed`, …
- **API** (`/api`; everything except `/health` and the sign-in calls needs a session; state-changing calls need the
  `X-CSRF-Token` header):
  - accounts: `POST /auth/register|login|logout|logout-all|password|forgot|reset|ws-ticket`, `GET|PATCH /auth/me`;
  - `GET /health` (public), `GET /agents`, `GET /agents/capabilities`, `GET /llm/usage`;
  - `GET /events`, `GET /dead-letters`: filtered to the user's projects plus platform events;
  - `GET|POST /projects`: own projects only, `?q=` search, `?archived=true`; create takes `goal`,
    `auto_approve` and `cloud_ok`;
  - `GET|PATCH|DELETE /projects/{id}`;
  - `POST /projects/{id}/runs` (run again), `GET|POST /projects/{id}/tasks` (`?run=`), `POST /projects/{id}/documents`;
  - `POST /projects/{id}/plan|approval|stop`;
  - `GET /projects/{id}/artifacts`, `GET /projects/{id}/artifacts/{artifact_id}?version=&download=`;
  - `GET /tasks/{id}`, `POST /tasks/{id}/cancel`;
  - WebSocket `/ws/events?ticket=&after_seq=&project_id=`;
  - plug-in routers are mounted at `/api/<plugin>/…` and require a session. A plug-in's project data must still be
    checked with `hmap.api.routers.projects.owned_project`.
- **DB:**
  - Alembic `001`: `projects`, `documents`, `tasks`, `executions`, `approvals`, `messages`, `inbox`, `outbox`,
    `events` (append-only), `agents`, `contexts`, `artifacts`, `errors`.
  - Alembic `001b` (`001_sprint_1_accounts.py`): `users`, `sessions`, `password_resets`, and `projects.owner_id`
    with an index.
  - Runs (`ProjectRecord.runs`, `TaskRecord.run`) live in the `data` jsonb columns.
  - **The migration head is `001b`**, so Member 2's `002` must set `down_revision = "001b"`.
- **Stopped projects:** `create_task` / `submit_graph` raise `ProjectStopped`. Hooks may let it propagate; it is
  logged, not counted as a hook failure.
- **Plug-in API:** `hmap/agents/<name>/plugin.py` exports `PLUGIN = Plugin(...)` with agents, router, `@hook`s,
  strategy slots (`executor`, `recovery`, `llm_provider`), priority. UI: `frontend/src/features/<name>/index.ts`
  with `defineFeature({...})`.

## How the next member plugs in (Member 2) — done in Sprint 2
- Create `backend/src/hmap/agents/doc_intel/plugin.py` with an agent declaring **`document.extract`** at a priority
  above 0. The stub (priority 0) stands down automatically; `GET /api/agents/capabilities` shows it as real.
- **Input:** `TaskAssign` whose artifact refs are the uploaded documents (`ctx.artifacts.get(ref)`). One upload can
  hold up to 20 documents, and it may come as folders (an assignment in `Part A/`, `Part B/`, `Part C/`).
  `inputs["documents"]` lists `{artifact_id, name, folder, path}` per document in upload order (absent for a typed
  request). Keep each requirement's folder in its source reference so the planner can treat a folder as one part of
  the work.
- **Output:** `TaskResult(outcome="success", artifact_refs=[<RequirementSet JSON artifact>])` (artifact type
  `requirement-set`). The `pipeline` plug-in already creates the extract task on upload and the plan task afterwards;
  **do not add hooks for these steps**.
- **LLM:** `ctx.llm.generate(role="reasoner", messages, schema=RequirementSet)` and
  `ctx.llm.classify(state, questions)`. Record your replay cache into `samples/llm_cache/doc_intel/`.
- **Database:** your migration is `backend/alembic/versions/002_sprint_2_*.py` with `down_revision = "001b"`.
- **UI panel:** `frontend/src/features/doc_intel/index.ts`.
- Start with `CONTRIBUTING.md` §3 (a dry run took under 30 minutes) and `docs/sprints/sprint-02-*.md`.
- Before handing back, run `scripts/precommit.sh --member 2 --base <this handoff folder>`.

## Config / env vars added (`.env.example` documents all)
`cp .env.example .env`: the backend reads `<repo>/.env` automatically, and real environment variables win over
it. `HMAP_ENV_FILE` points to a different file; `none` turns it off, and the test suite always does that.
- **Stack:** `HMAP_BUS=memory|rabbitmq`, `HMAP_STORE=memory|postgres`, `HMAP_RABBITMQ_URL`,
  `HMAP_DATABASE_URL` (Postgres on host port **5433**), `HMAP_RUN_AGENTS`.
- **Paths:** `HMAP_ARTIFACT_ROOT`, `HMAP_LLM_CACHE_DIR`. Relative paths are resolved from the repo root; `HMAP_ROOT`
  overrides the root.
- **Plug-ins and LLM:** `HMAP_PLUGINS`, `HMAP_LLM_MODE`, `HMAP_ROLE_MAP`, `OLLAMA_BASE_URL`,
  `HMAP_LLM_MAX_CONCURRENCY`.
- **Key pool:** `HMAP_GROQ_API_KEYS`, `HMAP_GEMINI_API_KEYS`, `HMAP_CLOUD_ROLE_MAP` (empty = built-in default: every
  chat role cloud-first; `none` = all local), `HMAP_CLOUD_OK`. Keys live only
  in `.env`.
- **Accounts:** `HMAP_PUBLIC_URL` (reset links), `HMAP_COOKIE_SECURE` (true behind HTTPS), `HMAP_SESSION_DAYS`,
  `HMAP_ALLOW_REGISTRATION`, `HMAP_SMTP_HOST|PORT|USERNAME|PASSWORD|FROM|STARTTLS`. Without SMTP, reset emails go
  to `data/dev_mailbox/*.eml`.
- **Frontend** (`frontend/.env.example`): `HMAP_API_ORIGIN` (server-side `/api` proxy target), `NEXT_PUBLIC_WS_URL`
  (live updates; default page host on port 8000), optional `NEXT_PUBLIC_API_URL`.

## Known limitations / tech debt
- **One Manager per database:** replies use prefetch 1 plus a process-local lock. Several Managers would need
  per-task ordering.
- **No `agent.registered` reply:** a rejected agent is not told and could still take work from its queue.
- **`cloud_ok`:** the per-project switch (`POST|PATCH /projects` `cloud_ok`, "Keep on this computer" in the UI)
  applies to steps assigned after it changes; a step already running keeps its setting.
- **No broker-level DLX on capability queues:** dead-lettering is done by the Manager/retry path and the adapter.
- **Broker-restart test:** restarts the shared dev RabbitMQ container (marked `slow`).
- **Regression check:** a flaky test that passes on both first runs is not re-run.
- **Context store:** returns the full pinned snapshot; selective, token-budgeted views are a stretch item.

**Accounts and security (laptop demo; read before any real deployment):**
- Passwords are hashed with scrypt (Python standard library; no external identity provider). Sessions are opaque
  random tokens in an HttpOnly, SameSite=Lax cookie; only SHA-256 hashes are stored. CSRF uses a double-submit token.
- **No email verification.** Addresses are not confirmed.
- **No social login.**
- **No roles or admin:** every signed-in user sees the shared platform pages (agents, capabilities).
- **Rate limits and WebSocket tickets are kept in process memory,** so a multi-process deployment needs a shared
  store.
- **Production needs HTTPS** and `HMAP_COOKIE_SECURE=true`, plus a real SMTP server for password resets.
- **Projects created before accounts** (`owner_id` NULL) are visible to nobody.
- **Delete** stops the work and erases the files. Task, execution, approval and event records stay as the audit
  trail (events are append-only), unreachable through the API.
- **Not supported by the backend, so not offered in the UI:**
  - editing a plan ("request changes"): reject the plan, then run again with a changed request;
  - replaying dead letters (Member 4, Sprint 4);
  - a demo mode.

## Test status
`scripts/check_sprint.sh 1` → see the latest run in `docs/members/1/eval.md`. It covers:
- secret scan, ruff, mypy;
- all backend tests, including accounts, two-user isolation and the restart-persistence test on RabbitMQ + Postgres;
- frontend lint, typecheck, unit tests and build;
- both demos.

`scripts/llm_check.sh` (with Ollama running) → LLM CHECK PASS (live = replay).
`make cloud-check` (team keys in `.env`) → CLOUD CHECK PASS on 2026-10-12: 8/8 keys, 12/12 cloud routes.

Details and failure scenarios: `docs/members/1/eval.md`.

## Deferred (receiving member / sprint)
| Item | Owner |
|---|---|
| OpenTelemetry / Prometheus / Grafana, DLQ replay UI, load and soak tests | Member 4, Sprint 4 |
| Security: service tokens, policy table (`core/policy.py` is `allow_all` today), input limits, audit log | Member 6, Sprint 6 |
| One-command demo packaging with reset (`make demo`) | Member 9, Sprint 9 |
| Context selective/token-budgeted views (stretch) | Member 1 backlog / Member 11 |
| `agent.registered` reply | Member 1 backlog (on request in `core-requests.md`) |
| Model routing with Laya (optional), speed re-run, LoRA trial | Member 11, Sprint 11 |
