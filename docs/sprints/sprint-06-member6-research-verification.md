# Sprint 6 — Member 6: Research Verification

**Owner:** Member 6 · **Needs:** Sprint 5 accepted + mid-eval feedback triaged · **Unblocks:** Sprint 10 (review uses verdicts)
**Replaces stub:** `verify.claims` → `agents/verify/`

## 1. Goal
An **independent** validator that takes a `ResearchReport`, checks each claim against evidence, compares sources, detects conflicts/unsupported claims, and returns a `VerificationReport` — plus a feedback path that makes the Manager create follow-up research when needed.

## 2. Provided
`ResearchReport` (claims, evidence with quote + content hash, cached page artifacts), gateway (`judge`, `embed`), M4 Refiner, M5 search providers (reusable), UI shell.

## 3. Research deliverable
Fact verification & claim checking (FEVER-style), NLI/entailment, retrieval-augmented verification, attribution/citation evaluation, hallucination taxonomy & detection (SelfCheckGPT-style consistency, quote-grounding), source credibility/comparison, independence principles (verifier must not share the researcher’s reasoning).

## 4. Design — layered, cheapest/most reliable first

```text
ResearchReport
 → [Claim normalizer] atomic claims (split compound), check-worthiness
 → L1 MECHANICAL: quote exists verbatim in stored page (sha256 match)?  evidence URL/hash consistent?  (deterministic)
 → L2 ENTAILMENT: does the quote support the claim? (LLM judge w/ constrained verdict+rationale; different model/family from researcher)
 → L3 INDEPENDENT RETRIEVAL: verifier runs its OWN searches (query rewrite, never sees researcher’s queries) → counter-evidence/support
 → L4 CROSS-SOURCE: agreement/conflict across ≥2 independent sources (domain-diversity, date precedence)
 → [Aggregator] verdict ∈ {VERIFIED, UNSUPPORTED, CONFLICTING, NEEDS_MORE_RESEARCH} + confidence + explanation + pointers
 → VerificationReport  (+ follow-up research suggestions: sub-questions for gaps)
```
Verdict rules documented as a decision table (e.g., L1 fail ⇒ at best UNSUPPORTED; L2 supports ∧ no conflict ⇒ VERIFIED).

## 5. Work items

### MUST
| # | Item | Files (`agents/verify/`) | Acceptance |
|---|---|---|---|
| 6.1 | Claim extraction/atomization | `claims.py` | gold atomic splits |
| 6.2 | L1 mechanical quote/hash verifier | `mechanical.py` | catches 100 % injected fake quotes |
| 6.3 | L2 entailment judge (schema verdict + rationale), different model role, bias controls (position/verbosity) | `entail.py` | accuracy on labelled pairs |
| 6.4 | L3 independent retrieval (reuse M5 providers via public interface; separate query generator) | `independent.py` | finds contradicting source on seeded cases |
| 6.5 | L4 cross-source comparison & conflict detector (dates, numbers, negation) | `compare.py` | |
| 6.6 | Aggregator + confidence calibration + decision table | `aggregate.py` | table-driven tests |
| 6.7 | `VerifyAgent` capability `verify.claims` | `agent.py` | on bus; idempotent |
| 6.8 | Feedback loop: `NEEDS_MORE_RESEARCH`/`UNSUPPORTED` → Manager creates follow-up research task with targeted sub-questions (bounded rounds) | `hooks.py`, registered in `plugin.py` | one loop demo |
| 6.9 | **Seeded-hallucination benchmark**: take good reports, inject (a) fake quotes, (b) wrong numbers, (c) unsupported claims, (d) contradicting-source cases; ≥60 items | `samples/verify/` | |
| 6.10 | Eval: precision/recall of flagged errors per type, false-alarm rate, agreement with human labels; compare layers (ablation L1 only → +L2 → +L3/L4) | `tests/verify/eval/` | `eval.md` |
| 6.11 | API + UI: claim table with verdict chips, evidence side-by-side, conflict view, “request more research” button | `agents/verify/router.py` (auto-mounted), `frontend/src/features/verify/` (auto-registered) | |
| 6.12 | Tests (unit, contract, integration, replay) | `tests/verify/` | green |

### STRETCH
Calibrated confidence via held-out set; multi-judge ensemble; temporal-validity checking; claim-to-claim consistency (contradictions inside the report).

## 5b. Platform-wide responsibility: Security Hardening (also owned by Member 6)

Why here: this member's whole subject is *not trusting* generated/retrieved content. **The basic security layer moved here from Sprint 1** (item 6.20); Sprint 1 only leaves a no-op `core/policy.py` hook for it (M1 signs off the `core/` change).

| # | Item | Acceptance |
|---|---|---|
| 6.13 | **Prompt-injection regression suite**: poisoned PDFs (M2), poisoned web pages (M5), poisoned repo files/READMEs (M7/M9), poisoned agent messages | suite runs in CI; known attacks fail |
| 6.14 | AuthN/Z review & tests: capability→message policy, project-scoped artifact access, denied/audited cases (research §30) | negative tests green |
| 6.15 | Token lifecycle: rotation, expiry, revocation, no secrets in logs/traces/context (secret-scan test on logs) | rotation without downtime |
| 6.16 | Dependency/secret scanning of the repo (`pip-audit`, `npm audit`, secret regex) + report | findings triaged |
| 6.17 | Input limits: upload size/type allow-list, message size caps, rate limits on API; every service binds to `127.0.0.1` only (laptop-only run) | tested |
| 6.18 | TLS/mTLS **evaluation write-up**: why they are deferred for a single-laptop, localhost-only run, and what would change if it were ever deployed | doc |
| 6.19 | Security section of `docs/members/6/design.md`: threat model (STRIDE-lite) for the whole platform | reviewed by team |
| 6.20 | **Basic security layer (moved from Sprint 1, item 1.18)**: per-agent service token issued at registration, capability→allowed-message policy table, input size/schema limits, audit log — implemented behind the `core/policy.py` hook | unauthorized command denied + audited; existing agents keep working with seeded tokens |

Definition of Done addition: `scripts/security_check.sh` exists and is included in `check_sprint.sh` from Sprint 6 on.

## 6. Local-LLM notes
Use **a different model family than the researcher** for `judge` (reduces correlated errors); constrained verdict enum; short inputs (claim + quote only) so 7–8B models do well; L1 is free (no LLM).

## 7. Interface handed to Sprint 10 / Manager
```text
Artifact: VerificationReport.json   claim_verdicts[{claim_id, verdict, confidence, supporting[], contradicting[], explanation}]
Event: verification.completed {task_id, report_ref, summary{verified,unsupported,conflicting,needs_more}}
Manager policy: verdicts → accept claims / follow-up research / flag to human
```

## 8. Definition of Done (additions)
- [ ] Benchmark metrics reported per layer; L1 recall on fake quotes = 100 %
- [ ] Follow-up research loop works and terminates (max rounds)
- [ ] Demo `demo_sprint_6.sh`: research → verification → flagged claim → follow-up research → re-verify

## 9. Risks
Verifier agrees with researcher’s errors → independent retrieval + different model; judge bias → calibration; over-flagging → track false-alarm rate, human review UI.
