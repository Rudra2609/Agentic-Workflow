# Sprint 10 — Member 10: Autonomous Final Review & Recovery

**Owner:** Member 10 · **Needs:** Sprint 9 accepted · **Unblocks:** Sprint 11 (closed loop complete)
**Replaces stub:** `review.final` → `agents/review/`; provides recovery through the plug-in `recovery` slot (no `manager/` edit).

## 1. Goal
Evaluate completed work against the **original requirements and rubric**, using objective evidence first and LLM-as-a-Judge second; classify failures; **trace each failure to the responsible task**; and drive **targeted, bounded revision** through the Manager (autonomous recovery loop) with human escalation.

## 2. Provided
`RequirementSet` (+rubric), `TaskGraph` with **coverage matrix** (req→tasks), `TestReport`, `VerificationReport`, `DocBundle`, `CodeChangeSet`, `ResearchReport`, M4 Refiner, Manager state machine incl. `NEEDS_REVISION`, `revision.request`/`feedback` messages (M1), gateway (`judge`).

## 3. Research deliverable
LLM-as-a-Judge (MT-Bench/G-Eval/Prometheus), known biases (position, verbosity, self-preference) and mitigations, rubric-based scoring, reference-guided/evidence-grounded judging, completeness checking, root-cause/failure analysis, recovery strategies (retry, targeted revise, replan, escalate), cost-bounded loops, human-in-the-loop design.

## 4. Design

```text
Inputs: RequirementSet+rubric, TaskGraph(coverage), artifacts: CodeChangeSet, TestReport, VerificationReport, DocBundle, ResearchReport
 → [Evidence assembler] per requirement: gather objective signals (tests passed? claim verified? doc present? deliverable exists?)
 → [Deterministic checks] deliverable present, tests pass, verification verdicts, doc grounding, acceptance criteria satisfied (where machine-checkable)
 → [LLM judge] per requirement/rubric criterion, evidence-first prompt, constrained {PASS|PARTIAL|FAIL, rationale, cited_evidence}; swap-order & multi-sample vote; judge ≠ producer model
 → [Aggregator] objective signals override judge on conflict; rubric scores; completeness %
 → [Failure analyzer] classify {MISSING, INCORRECT, UNTESTED, UNSUPPORTED_CLAIM, DOC_MISMATCH, QUALITY} → responsible_task_id via coverage matrix
 → [Recovery planner] minimal RevisionRequest set: (task, required_changes, context_refs); choose action: revise | rerun | replan | ask human; respects round budget
 → ReviewReport  →  Manager: PASS → project COMPLETE | FAIL → create revision tasks → (code→test→docs→) → re-review (bounded N)
```

## 5. Work items

### MUST
| # | Item | Files (`agents/review/`) | Acceptance |
|---|---|---|---|
| 10.1 | Evidence assembler (join requirements ↔ tasks ↔ artifacts ↔ reports) | `evidence.py` | complete on sample projects |
| 10.2 | Deterministic checkers (deliverables, tests, verification verdicts, doc grounding) | `checks/` | |
| 10.3 | LLM judge: evidence-grounded rubric prompts, constrained verdict, bias controls (order swap, multi-sample vote), different model | `judge.py` | agreement with human labels |
| 10.4 | Aggregation & scoring (objective-first precedence, rubric marks, completeness) | `aggregate.py` | table-driven tests |
| 10.5 | Failure analyzer + taxonomy + **responsible-task attribution** via coverage matrix | `failure.py` | correct attribution on seeded failures |
| 10.6 | Recovery planner → targeted `RevisionRequest`s; actions (revise/rerun/replan/escalate); round budget & loop guard | `recovery.py` | converges or escalates |
| 10.7 | Manager integration: review task at graph sink; on FAIL create revision executions, mark affected tasks `NEEDS_REVISION`, re-run downstream (test→docs→review) minimal set; preserve evidence | `recovery.py`, registered as plug-in strategy slot `recovery` in `plugin.py` | closed loop works; no file under `manager/` edited |
| 10.8 | `ReviewAgent` capability `review.final` | `agent.py` | on bus |
| 10.9 | Human-in-the-loop: review results screen, override verdicts, accept-with-notes, request changes → Manager | `router.py` (auto-mounted via `plugin.py`) | |
| 10.10 | **Judge calibration set**: ≥30 (requirement, evidence) pairs human-labelled; measure agreement, bias | `samples/review/` | report κ / accuracy |
| 10.11 | **Seeded end-to-end failures** (e.g., multi-client unsupported — guide §32; missing deliverable; hallucinated doc claim; failed test) with expected recovery path | `samples/review/e2e/` | each recovers or escalates correctly |
| 10.12 | UI: requirement PASS/PARTIAL/FAIL matrix, rubric score card, failure → task links, recovery timeline | `frontend/src/features/review/` | |
| 10.13 | Eval: judge accuracy vs human, attribution accuracy, recovery success rate, avg rounds, cost | `tests/review/eval/` | `eval.md` |
| 10.14 | Tests (unit/contract/integration/e2e loop with stubs+real agents, replay) | `tests/review/` | green |

### STRETCH
Judge ensemble with disagreement escalation; learning recovery policy from history; cost-aware recovery (cheapest fix first); explanation reports for graders.

## 5b. Platform-wide responsibility: End-to-End Integration (also owned by Member 10)

Why here: the review/recovery loop is the last piece that closes Plan→Assign→Execute→Review→Revise, so this member is the first able to prove the whole system.

| # | Item | Acceptance |
|---|---|---|
| 10.15 | **Golden scenario 1 — "TCP chat app"** (guide §32): PDF → requirements → plan → research → code → test (multi-client failure) → revision → pass → docs → review PASS | `scripts/demo_final.sh` green in `live` and `replay` |
| 10.16 | **Scenario 2** — non-code, research/report-heavy assignment | completes |
| 10.17 | **Scenario 3** — human change request mid-run ("don't use X") → replan from that point, completed work preserved | completes |
| 10.18 | **Cross-agent contract suite**: every producer→consumer pair (M2→M3, M5→M6, M7→M8, M8→M10, …) on real JSON | green |
| 10.19 | "No silent stubs" check: reads `GET /agents/capabilities` (real vs stub, from plug-in discovery); fails CI if a stub is unflagged | green |
| 10.20 | Fix integration defects found; file owner-targeted notes in `HANDOFF.md` | list closed |

Definition of Done addition: all three scenarios pass with the **single-model tier** (doc 02 §2.2b) as well as the full tier.

## 6. Local-LLM notes
Judge prompts short + evidence quoted; objective signals reduce reliance on weak judge; consider `judge` role on larger/different model for this sprint only (M11 benchmarks decide).

## 7. Interface handed to Member 11
```text
Artifact: ReviewReport {requirement_results[], rubric_scores[], failures[{category,responsible_task_id}], revision_requests[], overall, recommendation}
Event: review.completed {project_id, report_ref, outcome: PASS|REVISE|ESCALATE}
Manager recovery loop is now complete: Plan→Assign→Execute→Review→Revise.
```
All agent traces produced so far (LLM `record` cache) are available to M11 as benchmark/fine-tune data.

## 8. Definition of Done (additions)
- [ ] Seeded failure scenarios all handled (recovered within N rounds or escalated with clear reason)
- [ ] Judge agreement with human labels reported; bias mitigations demonstrated
- [ ] Full-system run: PDF → plan → research/code/test/docs → review FAIL → targeted revision → PASS
- [ ] Demo `demo_sprint_10.sh`

## 9. Risks
Infinite revise loops → round budget, plateau detection, human escalation; judge unreliability → objective-first, calibration; wrong attribution → coverage-matrix tests, confidence-gated actions.
