# Seeded-hallucination benchmark (Member 6, prepared ahead of Sprint 6 — item 6.9)

**86 labelled items** for testing the research verifier: real claims from Sprint 5's research agent, plus 60 errors
planted by hand. Each item says what the verifier should answer.

| Kind | Items | What was done | Expected verdict | Mechanical (L1) check |
|---|---|---|---|---|
| `clean` | 20 | nothing: real claims that their real quotes support | `VERIFIED` | passes |
| `fake_quote` | 15 | a quote was altered (14) or invented (1); its page hash still points to the real page | `UNSUPPORTED` | **fails** |
| `wrong_number` | 15 | a number or detail in the claim was changed (3.4 → 3.7, 20 % → 5 %, SHA-256 → SHA-1, …) | `UNSUPPORTED` | passes |
| `unsupported_claim` | 15 | the claim was replaced by a plausible one the quotes do not say | `UNSUPPORTED` | passes |
| `contradiction` | 15 | the real, supported claim + a **synthetic** second source that says the opposite | `CONFLICTING` | passes |
| `natural` | 6 | not planted: real Sprint 5 claims that go beyond their quotes (found by hand) | `UNSUPPORTED` | passes |

So the layers each have work to do: L1 (verbatim quote + hash) should catch all 15 fake quotes; L2 (entailment)
should catch wrong numbers, unsupported and natural claims; L4 (cross-source) should catch contradictions; the 20
clean items measure false alarms.

## Files
| Path | What |
|---|---|
| `benchmark.jsonl` | one item per line (format below) |
| `source_reports/` | the 10 real `ResearchReport`s the items come from (Sprint 5, offline replay of its 10 gold questions + the TCP-chat demo brief) |
| `pages/<sha16>.json` | the 27 real pages the quotes come from (cleaned text, URL, licence, `content_sha256`): Wikipedia CC BY-SA 4.0, Python docs PSF licence, arXiv abstracts CC0, FastAPI docs MIT |
| `pages/synthetic-NN.json` | 15 contradicting pages **written for this benchmark** (`"synthetic": true`, host `*.example.test`); never real sources |
| `build_benchmark.py` | rebuilds `benchmark.jsonl` from the reports and the hand-written edits in the file (plain Python) |
| `check_benchmark.py` | validates everything: hashes, quotes present / absent, counts, labels (plain Python) |

```bash
python3 samples/verify/check_benchmark.py      # 86 items, 60 seeded ... OK
python3 samples/verify/build_benchmark.py      # rebuild after editing the lists in the script
```

## Item format
```json
{"id": "V021", "kind": "fake_quote", "difficulty": "easy",
 "source": {"report": "q06_token_scheme", "claim_id": "C4"},
 "claim": "Common JWT signing algorithms include HMAC-SHA256 (HS256) and RSA-SHA256 (RS256)",
 "evidence": [{"id": "E6", "url": "https://en.wikipedia.org/wiki/JSON_Web_Token", "quote": "…SHA-512 (HS512)…",
               "content_sha256": "…", "page": "pages/….json"}],
 "counter_evidence": [],
 "expected": {"verdict": "UNSUPPORTED", "l1_quotes_verbatim": false, "error_in": "evidence E6 quote"},
 "changed": {"field": "evidence E6 quote", "from": "SHA-256 (HS256) …", "to": "SHA-512 (HS512) …"},
 "explanation": "the quote is not in the saved page (its hash still points to the real page)"}
```
`claim` and `evidence` mirror Sprint 5's `Claim` / `Evidence`; `page` is the saved text the quote must be found in
(typography-insensitive: spaces, curly quotes and dashes are normalised). The verdicts are Sprint 6's
`ClaimVerdict.verdict` values.

## Scoring (for Sprint 6, item 6.10)
Per kind: recall of flagged errors; on `clean`: false-alarm rate; overall: accuracy of the verdict; per layer
(L1 only → + L2 → + L3/L4) as the sprint asks. Difficulty (`easy` / `medium` / `hard`) is our judgement.

## Honest limits
- The planted errors are ours and fairly visible; real hallucinations are subtler (the 6 `natural` items show
  what they look like).
- 86 items from 10 reports on one topic area (student software projects): small, and the same claim appears in
  several kinds (on purpose: one verifier must give different answers to the same claim under different
  evidence).
- The contradicting sources are synthetic. A verifier that downweights unknown hosts may still pass on them, which
  is a fair outcome to report.
