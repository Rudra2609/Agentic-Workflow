# Mid-Evaluation Plan — Showing the Code of Members 1–5

**When:** after Sprint 5 is accepted + 2 buffer days (rehearsal, bug-fix only — no new features).
**What is evaluated:** Members 1, 2, 3, 4, 5 — each demonstrably contributes to *one* continuous run.

## 1. Demo storyline (≈12 min)

| Min | Step | Member shown | What the audience sees |
|---|---|---|---|
| 0–1 | Architecture slide + `docker compose up` / dashboard | **M1** | agents registering, heartbeats, queue depths |
| 1–3 | Upload a real assignment/lab-manual PDF (one scanned, one DOCX) | **M2** | parsing, OCR, requirements/constraints/deliverables/rubric highlighted in the source |
| 3–4 | Show structured `RequirementSet` JSON + source traceability | **M2** | each requirement links to page/span |
| 4–6 | Plan generated: DAG, roadmap, coverage matrix; **human edits & approves** | **M3** | React-Flow DAG, parallel layers, critical path, human-in-the-loop |
| 6–8 | Same extraction/plan **with vs without refinement**: critique → revise → stop reason | **M4** | RefinementTrace timeline + metric delta |
| 8–10 | Manager dispatches research tasks; research agent plans, searches, reads, cites, stops | **M5** | sub-questions, sources, evidence quotes, coverage, stop reason |
| 10–11 | **Failure injection**: kill the research agent mid-task → lease expiry → retry on new execution → DLQ view | **M1** | resilience story; idempotent duplicate demo |
| 11–12 | Stub agents (code/test/docs/review) complete the loop → "project complete" with the roadmap showing what is real vs stubbed | all | honest scoping |

## 2. Demo input set (prepared in Sprint 2/5, fixed before the eval)
- `samples/demo/tcp_chat_assignment.pdf` (native text), `samples/demo/lab_manual_scanned.pdf` (OCR), `samples/demo/requirements.docx`.
- Research questions derived from the plan (e.g., "TCP concurrency models in Python: threads vs asyncio") with a **cached corpus** so it works offline.

## 3. Evidence each member brings (rubric for the team)

| Member | Must show | Evidence artifact |
|---|---|---|
| M1 | bus + state machine + registry + artifacts + failure recovery live | `docs/members/1/eval.md`: test report, chaos scenarios passed, queue/latency numbers |
| M2 | extraction on ≥8 docs; precision/recall vs gold; OCR case | `docs/members/2/eval.md` |
| M3 | valid DAG (no cycles), 100 % requirement coverage, human approval gate | `docs/members/3/eval.md` |
| M4 | ablation: with/without refinement on M2/M3 outputs; stop-criteria behaviour | `docs/members/4/eval.md` |
| M5 | cited report; coverage; stop reason; offline replay | `docs/members/5/eval.md` |

## 4. Readiness gate (go/no-go checklist, 2 days before)
- [ ] `make demo` from a clean copy works on **Member 1's laptop** (the only demo machine)
- [ ] Demo runs in `HMAP_LLM_MODE=live` **and** `replay` with identical results
- [ ] Failure-injection script `scripts/demo_chaos.sh` works 3× in a row
- [ ] All Sprint 1–5 tests green (`scripts/check_sprint.sh 5`)
- [ ] 2-minute **recorded video backup** of the full run
- [ ] Each member can explain their interface to the next/previous subsystem in 60 s
- [ ] README "What is real vs stub" table accurate

## 5. Integration work scheduled for the buffer (not new features)
- Wire M4's Refiner into M2/M3/M5 behind a `refine=true` flag if not already done in Sprint 4.
- Dashboard polish: single "Run demo" button, clean event log.
- Performance pass: model preload/warm-up so first call is not 30 s.
- Seed script resets the DB and the artifacts volume to a known state.

## 6. After mid-eval
Feedback is triaged into `docs/sprints/mid-eval-feedback.md`; items affecting later sprints are added to those sprint files; nothing blocks Sprint 6.
