# Prompt-injection regression suite (Sprint 6, item 6.13)

Poisoned inputs for every way untrusted text enters the platform. Written for this project (no third-party content).
Tests: `backend/tests/verify/security/test_injection.py` (runs with the rest of the suite; no model, no network).

| Entry point | Files | Owner of the reading code | What must hold |
|---|---|---|---|
| Uploaded documents (Member 2) | `documents/*.pdf`, `documents/*.docx` (+ `attacks.json`) | Member 2 | attack text never becomes a requirement; the real requirements are still found |
| Web pages (Member 5) | `samples/research/adversarial/*.html` (Member 5's, read only) | Member 5 | no instruction line survives cleaning; quotes stay verbatim |
| Repository files (Members 7 / 9) | `repo/` | Members 7 / 9 (Sprints 7 / 9) | the platform sanitizer drops the AI-directed lines; switched on for `code.implement` / `docs.generate` when they are real |
| Agent messages | `messages/poisoned_results.json` | Member 1 (Manager), Member 6 (verifier) | a report's text never drives the Manager; the verifier treats quotes as data |

Build the documents again: `cd backend && uv run python ../samples/verify/injection/build_injection.py`.
Known findings (attacks that still get through) are listed in `docs/members/6/security-report.md`.
