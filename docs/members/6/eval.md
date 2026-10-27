# Evaluation — research verification (Member 6, Sprint 6, item 6.10)

Data: the seeded-hallucination benchmark `samples/verify/benchmark.jsonl`: **86 labelled items, 60 seeded errors**
(20 clean, 15 fake quotes, 15 wrong numbers, 15 unsupported claims, 15 contradictions with a synthetic counter-source,
6 natural over-reaches from Sprint 5 output). Labels are ours (human). Plus the 10 real Sprint 5 reports (43 claims).

Run (offline, from the recordings in `samples/llm_cache/verify/`, 0 network calls, same numbers every time):

```bash
cd backend && uv run python -m tests.verify.eval.run_eval --ablation     # -> samples/verify/eval_results/replay.json
```

Models (recorded 2026-10-18 with the team keys, cloud-first per `DEFAULT_CLOUD_ROLE_MAP`): `judge` = Groq
`qwen/qwen3.8-27b`, `fast` (L3 queries) = Groq `openai/gpt-oss-20b`. The researcher's `reasoner` is Gemini /
gpt-oss, so judge and researcher are different model families.

## 1. Ablation per layer (the sprint's table)

"Flagged" = any verdict other than VERIFIED. Recall = flagged / items of that kind; false alarms = flagged clean items.

| Configuration | Accuracy | κ vs human | Error recall | False alarms (20 clean) | fake quote | wrong number | unsupported | contradiction | natural | Model calls |
|---|---|---|---|---|---|---|---|---|---|---|
| L1 only | 0.407 | 0.16 | 0.227 | **0 %** | **15/15** | 0/15 | 0/15 | 0/15 | 0/6 | 0 |
| L1 + L2 | 0.767 | 0.58 | 0.803 | 20 % | 15/15 | **15/15** | **15/15** | 2/15 | **6/6** | 144 |
| L1–L4 (own search finds the counter-page) | 0.826 | 0.69 | 0.879 | 20 % | 15/15 | 15/15 | 15/15 | 7/15 | 6/6 | 220 |
| L1–L4 + counter-source handed in | **0.907** | **0.84** | **0.985** | 20 % | 15/15 | 15/15 | 15/15 | **14/15** | 6/6 | 227 |

What each layer contributes — the expected shape from `research.md` §8 holds:
- **L1 is free and exact:** 15/15 fake quotes caught (**100 %**, the DoD), 0 false alarms; nothing else.
- **L2 catches what L1 cannot:** every wrong number (15/15), unsupported claim (15/15) and natural over-reach (6/6).
- **Only L4 finds contradictions.** With the verifier's own search (L3: claim-only queries over Member 5's corpus +
  the real benchmark pages + the item's counter-page) it found 5 of the 13 contradictions L2 let through; when the
  counter-source is handed in, 12 of 13. The gap is **L3's retrieval** (FEVER's lesson: most misses are retrieval
  misses), not the comparison: **L4 never raised a false conflict** (R6 right 12/12).

Per-kind exact verdicts (L1–L4 + counter): clean 16/20, fake quote 15/15, wrong number 14/15 (one became NEEDS MORE
RESEARCH), unsupported 15/15, contradiction 12/15, natural 6/6.

## 2. Bias controls (6.3)

| Variant | Accuracy | False alarms | Error recall | Calls |
|---|---|---|---|---|
| default (position swap on, number guard on) | 0.907 | 20 % | 0.985 | 227 |
| no position swap | **0.942** | **10 %** | 0.970 | 164 |
| no number guard | 0.907 | 20 % | 0.985 | 227 |

- **Position swap:** the judge gave the same answer in both orders for **91.7 %** of judgements. The 4 disagreements
  became NEEDS_MORE_RESEARCH: 2 clean items (V009, V012), 1 wrong number (V050), 1 contradiction. Without the swap,
  accuracy is higher on *this* benchmark (no item is labelled NEEDS_MORE_RESEARCH, so "unsure" is never counted right)
  but one wrong number (V050) slips through as VERIFIED. We keep the swap on: an unsure verdict sends the claim to
  follow-up research instead of letting a changed figure through. Cost: +63 calls.
- **Number guard:** no effect with this judge (it already catches every changed figure); it is kept for weaker
  judges (it is what the rules fallback relies on, see §5).

## 3. Decision-table rows (= the aggregator's confidence)

How often the verdict reached through each row was right (L1–L4 + counter):

| Row | Verdict | Items | Right | Confidence used |
|---|---|---|---|---|
| R1 L1 fails | UNSUPPORTED | 15 | 100 % | 0.98 (capped) |
| R3 quotes contradict | UNSUPPORTED | 16 | 100 % | 0.95 |
| R4 judge unsure | NEEDS_MORE_RESEARCH | 4 | — (no such label) | 0.50 (by design) |
| R5 quotes do not state it | UNSUPPORTED | 22 | 86.4 % | 0.85 |
| R6 another source conflicts | CONFLICTING | 12 | 100 % | 0.90 (small n) |
| R7 independent agreement | VERIFIED | 0 | — | 0.90 (never reached; judgement) |
| R8 quotes support, nothing else | VERIFIED | 17 | 94.1 % (66.7 % without counter-sources) | 0.80 |

R7 was never reached: L4 judges at most 3 passages, and the other sites' best sentences rarely *state* the same claim.
The stretch item "held-out calibration" would need a second labelled set; these numbers come from the same 86 items.

## 4. Real research output (the 10 Sprint 5 reports, all layers)

| | Value |
|---|---|
| Claims | 43 |
| Quotes re-checked by L1 | 48, **100 % pass** (Member 5's quote check holds up independently) |
| Verified | 23 (citation recall **53.5 %**) |
| Unsupported | 18 |
| Needs more research | 2 |
| Conflicting | 0 |

About half of the real findings say more than their quotes do: the over-reach `research.md` §4 cites from Liu et al.
(≈ half of generative-search sentences not fully supported). The 6 `natural` items were hand-picked from these.
For the mid-eval demo report (TCP chat, 9 findings): 5 verified, 3 unsupported, 1 needs more research → follow-up
research on 3 questions (2 more search rounds, nothing new offline) → re-check (round 1): the same 9 verdicts.

## 5. Without a model, and on the local model

| Run | Accuracy | False alarms | Error recall | Notes |
|---|---|---|---|---|
| rules only (no model: fake mode, all keys busy and no Ollama) | 0.663 | 70 % | 0.939 | word overlap + number guard; flags too much, misses little; confidence capped at 0.6 |
| local `qwen3.5:9b`, sample of 6 (one per kind; L1–L4 + counter, not recorded) | 5 / 6 | 0 / 1 | 4 / 5 | missed the contradiction; ~70 s per call |

### 5.1 Local-only run
`uv run python -m tests.verify.eval.run_eval --mode live --local-only --configs L1-L4+counter --no-reports
--per-kind 1 --name local-sample` (2026-10-18, Ollama on this laptop with Docker running): **17 calls, mean 70 s per
call** (~5 tokens/s), so the full 86-item run (≈ 230 calls) would take about 4.5 hours and was not done. On the
sample the local judge agreed with itself in both orders every time, caught the fake quote (L1), the changed number,
the unsupported claim and the natural over-reach, and kept the clean claim — but called the JWT contradiction
(V066) VERIFIED: it judged the counter-source "keep a server-side session record … in practice stateful" as not
contradicting "JWTs are stateless". Locally the judge is also the researcher's model, which is exactly the
correlated-error case `research.md` §7 warns about. Recommendation for Member 11: a bigger or different-family local
judge, or keep `judge` cloud-first.

## 6. Cost and time

L1–L4 + counter: 227 judge/fast calls for 86 items (2.6 calls per claim), ~102 k tokens (≈ 1.2 k per claim); replay
2.6 s for the benchmark. The demo report (9 findings): 30 calls; its re-check after the follow-up: 30 calls (same
findings). Live timing depends on the free-tier rate limits (one recording run hit a Groq cooldown, the key pool moved
on).

## 7. Honest limits

- The benchmark is ours: 86 items, one topic area, fairly visible planted errors; the same claim appears under several
  kinds on purpose. Synthetic counter-sources (`*.example.test`) make contradictions easy to *compare*, hard to *find*.
- Confidence values are measured on the same items they are used for (no held-out set).
- L3 retrieval is the weak layer (5/13 contradictions found by the verifier's own search, offline corpus only).
- The demo's follow-up research (recorded into Member 5's folder with Member 1's approval, HANDOFF.md) finds nothing
  new in the offline corpus: it stops on "low novelty" with the same 9 findings, so the re-check repeats round 0's
  verdicts. Offline, the loop shows the mechanism, not an improvement.
