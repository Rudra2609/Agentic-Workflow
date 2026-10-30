# Design — research verification, security, mid-eval readiness (Member 6, Sprint 6)

Spec: [`sprint-06`](../../sprints/sprint-06-member6-research-verification.md) · Plan: [plan.md](plan.md) ·
Research: [research.md](research.md) · Numbers: [eval.md](eval.md) · Tests: [testing.md](testing.md) ·
Security findings: [security-report.md](security-report.md)

## 1. Verification: input, output, where it runs

| | |
|---|---|
| Capability | `verify.claims` — `VerifyAgent` (`agents/verify/agent.py`, priority 100; the stub stands down) |
| Input | the newest `research-report` among the step's `artifact_refs` (the Manager hands a dependent step its upstream results), or `inputs.research_report`; `inputs.verify_round`, `inputs.follow_up_of_verification`, optional `inputs.layers`, `inputs.research_mode` |
| No report | (a document project's *test* step is also `verify.claims`; a stub upstream) → an empty `VerificationReport` with the note "nothing to verify"; the step succeeds |
| Output | `verification-report` (`vr-<task_id>`, the contract `VerificationReport`) + `verification-trace` (`vt-<task_id>`: every layer's result per claim, for the UI and the eval) |
| Event | `verification.completed {task_id, report_ref, research_report_ref, summary, round, follow_up}` |
| LLM roles | `judge` (L2, L4), `fast` (L3 queries); replay cache `samples/llm_cache/verify/` |
| Idempotency | a redelivered task whose report was already checked returns the stored artifacts (looked up in the artifact store, so it holds across agent restarts) |
| Failure injection | honours `stub_fail` / `stub_delay_s` like the stub (chaos tests, `demo_chaos.sh`) |

## 2. The layers (cheapest and most reliable first)

```text
ResearchReport.claims ─► claims.atomize ─► per atomic claim:
   L1 mechanical.check_claim   every cited evidence: page artifact exists, sha256(text) = page hash = evidence hash,
                               URL = page URL, quote verbatim (Member 5's quotes.locate)          (no model)
   L2 entail.judge             judge(claim, quotes) → supports | refutes | not_enough + rationale;
                               asked twice (claim first / passages first): disagreement = unsure;
                               number guard: a figure the quotes never mention turns "supports" into "not_enough"
   L3 independent.retrieve     ONLY if L2 supports: own queries (role fast, sees the claim only), Member 5's providers
                               behind the verifier's OWN search cache, cited pages excluded → best sentences
   L4 compare.compare          rule signals (number / year / negation) + judge on ≤ 3 passages → conflict / agreement
 ─► aggregate.decide (decision table) ─► roll_up (worst atom wins) ─► ClaimVerdict
 ─► follow_up_questions (flagged claims → research questions, ≤ 3)
```

Independence from the researcher: a different model family on the cloud (`judge` = Groq qwen, researcher `reasoner` =
Gemini / gpt-oss: `DEFAULT_CLOUD_ROLE_MAP`), the verifier never sees the brief, sub-questions or queries, and its
searches exclude the pages the claim already cites. **Locally every role is `qwen3.5:9b`**, so judge and researcher
are the same model there (a known limit; routing is Member 11's).

Untrusted text: quotes and passages are wrapped with Member 5's `sanitize.wrap` (delimiters escaped) and the system
prompt says they are data. Inputs are short: claim + ≤ 4 quotes of ≤ 600 characters.

Atomization (6.1) is rules only: split at sentence ends, `;` and the joints `, while / whereas / but / so / although`;
a fragment of < 3 words or starting with *not / only / no …* is glued back; questions and "no answer" notes are not
check-worthy. Ids keep the claim id (`C3.a`). 25/25 gold splits (`samples/verify/atomic_gold.jsonl`). The plan's
`fast` model for long claims was dropped: a wrong split creates claims nobody made, and rules are reproducible.

## 3. Decision table (`aggregate.TABLE`, first match wins)

| Row | Condition | Verdict | Confidence |
|---|---|---|---|
| R1 | L1 fails (a quote / hash / URL does not check out) | UNSUPPORTED | 0.98 |
| R2 | L1 passes, L2 off (ablation "L1 only") | VERIFIED | 0.30 |
| R3 | L2: the quotes contradict the claim | UNSUPPORTED | 0.95 |
| R4 | L2 unsure (the two orders disagree) | NEEDS_MORE_RESEARCH | 0.50 |
| R5 | L2: the quotes do not state the claim | UNSUPPORTED | 0.85 |
| R6 | L2 supports, L4 finds a conflicting source | CONFLICTING | 0.90 |
| R7 | L2 supports, another site agrees, no conflict | VERIFIED | 0.90 |
| R8 | L2 supports, nothing else found (or L3/L4 off) | VERIFIED | 0.80 |

Confidence = the measured per-row accuracy on the benchmark (eval.md §3), rounded down, capped at 0.98; a judgement
made by the fallback rules (no model answered) is capped at 0.6. It is never a number the model reports.
Roll-up: UNSUPPORTED > CONFLICTING > NEEDS_MORE_RESEARCH > VERIFIED.

## 4. Feedback loop (6.8)

`hooks.on_verified` (Manager hook, `task.completed` of `verify.claims`):

1. read the report, emit `verification.completed`;
2. if there are follow-up questions, a research report and `round < HMAP_VERIFY_MAX_ROUNDS` (default 1, hard cap 3):
   create `research.run` with `{"follow_up_of": <research report>, "research_questions": [...]}` (Member 5's
   follow-up mode keeps the earlier evidence) and a `verify.claims` re-check that `depends_on` it, with
   `verify_round + 1`; both are children of the verify step.

Decided with Member 1 (Q1): the plan's later steps are **not** held back; they already depend on the first check,
and the re-check's report is the newest. The loop terminates because the round travels in the task inputs.
"Request more research" in the Verify tab calls the same function (`POST /api/verify/runs/{p}/{t}/follow-up`).

## 5. API and UI (6.11)

`/api/verify/runs/{project}`, `/runs/{project}/{task}` (trace + each claim's evidence + follow-up steps),
`POST …/follow-up`, `/table` (decision table), `/security` (policy table, key ids + fingerprints, recent refusals).
Every project route checks ownership (404). The Verification tab (`frontend/src/features/verify/`, order 27): steps
as cards (counts per verdict), the claim table flagged-first with verdict chips, per claim each layer in plain words,
conflicting sources, the quote next to the saved page (Member 5's page endpoint, read only) and the follow-up box.

## 6. Failure modes

| Failure | Behaviour |
|---|---|
| no model answers (fake mode, all keys cooling down, no Ollama) | rules decide L2/L4 (overlap + number guard), marked `by: rules`, confidence ≤ 0.6, a trace note |
| replay miss | same as above (the gateway raises; the layer falls back) |
| page artifact missing / changed | L1 fails: UNSUPPORTED with the reason |
| a provider is down | L3 skips it; other providers and the local corpus still answer |
| cancelled | `check_cancelled` between claims and layers |
| follow-up research fails | the re-check stays waiting on it (`depends_on`); the first report stands |

---

## 7. Security (items 6.13–6.20; `backend/src/hmap/core/policy.py`)

### 7.1 Basic layer (6.20)

- **Per-agent service token**, derived when the agent registers: `v1.<kid>.<exp>.<sig>`, `sig = HMAC-SHA256(key,
  "v1|kid|agent_id|exp")`. Keys come from a keyring: `HMAP_AGENT_SECRETS` (newest first) or the seeded dev file
  `data/security/agent_keys.json` (0600, git-ignored), shared by every process on the laptop. **The token never
  travels**: every envelope built by `make_envelope` carries `auth = v1.<kid>.<exp>.<HMAC(token, message_id | type
  | sender | task | execution | sha256(payload))>`, so a bus reader can neither forge nor reuse it, and a changed
  message fails. Replays are absorbed by the inbox's message-id dedup.
- The **Manager** checks every report before any state change (`Manager.handle_delivery` → `policy.check_report`);
  the **agent runtime** checks every command (`AgentWorker._on_command` → `policy.check_command`). Stateless: the
  Manager re-derives tokens, so its restart logs nobody out.
- **Capability → message policy table** (`policy.POLICY_TABLE`): agents may send only the report types; agent.* must
  speak for the sender (*identity*); task reports must be about an execution assigned to the sender, for a
  capability it registered (*assigned*); commands only from the Manager.
- **Limits**: 256 KiB per message (*size*); uploads: the existing type allow-list and 25 MB / 100 MB caps, plus
  **content sniffing** (`policy.content_matches`: a `.pdf` must start `%PDF-`, text must be UTF-8 without NUL);
  **rate limit** on state-changing API requests (token bucket per client, `HMAP_API_WRITE_RATE` 20/s, burst 200).
- **Audit log**: every refusal and every registration → `AuditEntry` in memory + table `security_audit`
  (migration 006) on Postgres. `HMAP_SECURITY_ENFORCE=false` = audit only.
- Existing agents keep working unchanged: the runtime signs for them; tests' hand-made envelopes go through
  `make_envelope` too. Messages applied directly with `Manager.handle_message` (tests, an HTTP fallback) bypass the
  bus check by design.

### 7.2 Token lifecycle (6.15)

`python -m hmap.core.policy rotate | retire <kid> | revoke <agent> | unrevoke <agent> | status`. Rotation adds a key
in front; signers switch on their next message (they re-derive when the newest kid changes), the old key verifies
until retired: **no downtime** (test: rotate while a task runs, retire, keep working). Expiry `HMAP_AGENT_TOKEN_TTL_S`
(7 days), renewed at half-life. Revocation refuses an agent at once. Logs show key ids and 8-character
fingerprints only; a test runs a flow with fake keys and checks logs, events, the agents page, every bus message and
every artifact for keys, the agent secret and the tokens.

### 7.3 Threat model (6.19, STRIDE-lite, the whole platform on one laptop)

Assets: the user's documents and plans, the team's cloud keys, the accounts, the integrity of task state and of
research claims. Trust boundary: the laptop; inside it, the browser ↔ API (HTTP on 127.0.0.1), processes ↔ RabbitMQ
/ Postgres (127.0.0.1, dev credentials), agents ↔ web / cloud LLMs (outbound HTTPS).

| | Threat | Where | Mitigation (owner) | Left |
|---|---|---|---|---|
| **S**poofing | a script on the bus pretends to be an agent or the Manager | bus | signed envelopes, identity + assigned rules (M6) | a process that can read the keyring file (same OS user) can sign; in-process plug-ins are trusted code |
| | another user's session | API | scrypt passwords, HttpOnly SameSite cookies, CSRF double-submit (M1) | no MFA |
| **T**ampering | a message changed in transit / replayed | bus | MAC over the payload; inbox dedup by message id (M1/M6) | — |
| | an artifact changed after the fact | artifacts | content hashes; L1 re-checks research pages (M1/M6) | other artifact types are not re-checked by readers |
| | **prompt injection** in documents, pages, repos, messages | every model input | sanitizer + wrapped, labelled untrusted text; page text never becomes a query or task (M5); injection suite (M6) | **F1–F3** in security-report.md |
| **R**epudiation | "that agent never reported this" | Manager | audit log of refusals + registrations; append-only events (M1/M6) | allowed reports are in events, not in the audit table |
| **I**nformation disclosure | keys in logs / traces / recordings / artifacts | everywhere | keys only in `.env`, SecretStr, fingerprints in logs; leak scan in `security_check.sh` (M1/M6) | — |
| | another user's project | API | ownership check on every project route (404) (M1, each member's router) | — |
| | questions from private documents sent to search engines | research | `cached` mode is the default (M5) | `online` mode sends them |
| **D**enial of service | flood of API writes / huge messages / huge uploads | API, bus | rate limit, 256 KiB messages, 25/100 MB uploads (M1/M6) | in-memory limiter is per process |
| **E**levation of privilege | an agent reports on work of another capability; commands from an agent | bus | policy table (M6) | — |
| | network exposure | all listeners | everything binds 127.0.0.1 (test) | — |

### 7.4 TLS / mTLS (6.18): why deferred, and what changes if this is ever deployed

Every connection is on the loopback interface of one laptop (doc 02 §3: no deployment). Traffic on `127.0.0.1`
never leaves the machine, so TLS would protect against nobody who could not already read the processes' memory or
the keyring file. It would add certificate generation and rotation, a local CA the browser trusts, and failure modes
during the demo, for no security gain. Message integrity and sender authentication are already provided at the
application layer by the signed envelopes, which TLS would not replace (TLS authenticates a connection, not a
message that sits in a queue).

If the platform were ever deployed beyond one machine:
1. **TLS everywhere**: HTTPS on the API and dashboard (`HMAP_COOKIE_SECURE=true`, HSTS), AMQPS for RabbitMQ,
   `sslmode=verify-full` for Postgres;
2. **mTLS between services** (API, agent hosts, broker) with short-lived certificates from an internal CA, so
   identity does not rest on one shared keyring;
3. **per-host secrets**: a secret manager instead of `data/security/agent_keys.json`, one key per agent host, and
   tokens issued by the Manager in a registration reply (today there is no `agent.registered` reply);
4. per-user broker / database credentials instead of the dev `hmap/hmap`; network policies; a shared store for rate
   limits and WebSocket tickets.

## 8. Mid-evaluation readiness (6.21–6.24)

- `make demo` → `scripts/demo.sh`: Colima (if needed) + Postgres + RabbitMQ, API (Manager, migrations on start) on
  127.0.0.1:8000, the agents in **their own process** (so they can be killed), the dashboard on 127.0.0.1:3000 and a
  demo account; replay + cached research by default. `make stop` → `scripts/stop.sh` stops what it started. Minimal
  on purpose: reset / seed / config reference are Member 9's (Sprint 9).
- `scripts/demo_chaos.sh`: kills the agents process during a research step, restarts it, and checks the step is
  retried as a new execution on a new agent and completes; 3 rounds.
- `samples/demo/`: the three inputs (README lists sources and hashes).
- `scripts/demo_sprint_6.sh`: the storyline (inputs → plan → research → verification → flagged → follow-up →
  re-check → complete; security summary).
