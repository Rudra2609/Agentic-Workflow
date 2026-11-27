# Final slides / Q&A pack (item 11.23)

Compiled by Member 11. Each member writes **their own** slide (60 seconds: what you built, one number, one honest
limit), in their own words; the numbers below are where each eval lives. `make report` builds the long report from
every member's research / design / eval docs (`reports/final-report.md`).

| # | Member | Subsystem | Their numbers | Slide (the member fills it in) |
|---|---|---|---|---|
| 1 | Member 1 | communication layer, Manager, platform | docs/members/1/eval.md | |
| 2 | Member 2 | document intelligence | docs/members/2/eval.md | |
| 3 | Member 3 | planning | docs/members/3/eval.md | |
| 4 | Member 4 | refinement + observability | docs/members/4/eval.md | |
| 5 | Member 5 | research | docs/members/5/eval.md | |
| 6 | Member 6 | verification + security | docs/members/6/eval.md | |
| 7 | Member 7 | autonomous coding | docs/members/7/eval.md | |
| 8 | Member 8 | automated testing | docs/members/8/eval.md | |
| 9 | Member 9 | documentation + one-command demo | docs/members/9/eval.md | |
| 10 | Member 10 | final review + recovery + end-to-end | docs/members/10/eval.md | |
| 11 | Member 11 | local models, routing, release gate | docs/members/11/eval.md | |

## Demo order (suggested, ~10 min)
1. `make demo` → upload the TCP chat PDF → requirements (M2) → plan + approval (M3).
2. Research + verification (M5, M6), coding + tests (M7, M8), docs (M9), the review (M10).
3. The Models page: which model answered each step and why (M11).
4. Failure: kill an agent (`scripts/demo_chaos.sh`), the Operations page (M4).
5. Offline: `make demo-replay` with Wi-Fi off.

## Q&A notes
- Why cloud-first? the team's decision (doc 02 §2.5): the local 9B model takes ~15 min per coding step on this
  laptop (Member 10 eval §6); the platform still runs with no keys at all.
- Is the LLM judge biased? objective checks first, order swap, votes (Members 6, 10).
