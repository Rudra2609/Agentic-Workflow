# Demo inputs (mid-evaluation, Sprint 6 item 6.23)

Fixed before the mid-evaluation. Copied unchanged from Member 2's gold set (`samples/doc_intel/gold/docs/`, written
for this project), so their extraction is measured in `docs/members/2/eval.md`.

| File | From | Shows |
|---|---|---|
| `tcp_chat_assignment.pdf` | `g01_tcp_chat/tcp_chat_assignment.pdf` | native-text PDF; the main storyline (plan → research → verification) |
| `lab_manual_scanned.pdf` | `g04_scanned/library_assignment_scan.pdf` | a scanned assignment: OCR (the gold set has no scanned *lab manual*; this is its scanned document) |
| `requirements.docx` | `g02_lab_manual/lab4_unit_testing.docx` | a Word lab manual |
| `tcp_chat_assignment.txt` | Member 1 (Sprint 1) | plain-text version used by `demo_sprint_1.sh` and `seed.sh` |

sha256 (first 12): `6f9a80cd5ae2` tcp_chat_assignment.pdf · `a20bd54075a6` lab_manual_scanned.pdf · `eecc3bd4e7b6`
requirements.docx — `scripts/demo_sprint_6.py` checks them.

`make demo` signs in a local demo account (test values for this laptop only, set in `scripts/demo.sh`:
`HMAP_DEMO_EMAIL` / `HMAP_DEMO_PASSWORD`, default `mid-eval@example.test` / `hmap-demo-2026`).
