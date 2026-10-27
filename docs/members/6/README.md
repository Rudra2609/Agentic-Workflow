# Member 6 — research verification (+ security, + mid-evaluation readiness)

Sprint 6 ([spec](../../sprints/sprint-06-member6-research-verification.md), [plan](plan.md)). Built 2026-10-18.

| Doc | |
|---|---|
| [research.md](research.md) | fact verification, NLI, hallucination detection, attribution, injection (written before the sprint) |
| [design.md](design.md) | the four layers, decision table, follow-up loop, API/UI, **security layer + threat model + TLS write-up**, demo packaging |
| [eval.md](eval.md) | the seeded-hallucination benchmark per layer, bias controls, calibration, real reports, local model |
| [testing.md](testing.md) | what is tested where |
| [security-report.md](security-report.md) | security checks and triaged findings (F1–F6) |

## Run

```bash
make demo                                   # the platform, offline: http://127.0.0.1:3000 (account in samples/demo/README.md)
scripts/demo_chaos.sh                       # kill the agents mid-research, 3 rounds; then: make stop
scripts/demo_sprint_6.sh                    # the scripted mid-eval storyline (own API on a spare port)
scripts/security_check.sh                   # secrets, leaks, dependency audit, security tests, listeners
cd backend && uv run python -m tests.verify.eval.run_eval --ablation   # the benchmark (replay)
python -m hmap.core.policy status|rotate|retire <kid>|revoke <agent>  # the agent keyring (from backend/, uv run)
```

## Inputs → outputs

- **In:** a `research-report` (claims citing evidence with verbatim quotes, page hashes and saved-page artifacts).
- **Out:** `verification-report` (`VerificationReport`: per claim VERIFIED / UNSUPPORTED / CONFLICTING /
  NEEDS_MORE_RESEARCH, confidence, supporting / contradicting evidence, explanation; follow-up questions),
  `verification-trace` (every layer's result), event `verification.completed`, and — for flagged claims — a
  follow-up `research.run` + a re-check (one round by default).

## Limitations

- L3 (own search) is the weak layer offline: it found 5 of 13 contradictions; with the counter-source in hand L4
  finds 12 of 13.
- Locally the judge is the same model as the researcher (`qwen3.5:9b` for every role).
- Offline, the demo's follow-up research finds nothing new (same 9 findings, same verdicts on re-check); its model
  answers are recorded in Member 5's replay folder (approved, HANDOFF.md).
- Security: one shared keyring per laptop; see [security-report.md](security-report.md) F5/F6 and design §7.4.
