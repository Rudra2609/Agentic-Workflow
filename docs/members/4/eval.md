# Evaluation — does refinement help, what does it cost, and does the platform hold up? (Member 4)

All numbers come from `samples/refine/eval_results/*.json` (written by the commands below, 2026-10-14). Quality is
scored with **Members 2 and 3's own metrics**, against their gold sets: 10 documents and 9 plans. The judge's own
score is never used as the measure.

```bash
cd backend
uv run python -m tests.refine.eval.run_eval --suite all --producer rules    # rules.json
uv run python -m tests.refine.eval.run_eval --suite all --producer replay   # replay.json
uv run python -m tests.refine.eval.taxonomy_eval                            # taxonomy.json
```

Three conditions: **base** (the output as produced), **Self-Refine** (critique → revise → stop), and **+ Reflexion**
(also notes and a strategy change). Two producers:

- **replay**: the shipped cloud outputs (Groq `gpt-oss-120b`), already good.
- **rules**: Members 2 and 3's rule-based fallbacks, with no model. This is weaker, so there is more room to
  improve, and it is what a laptop without keys gets.

In both, the refinement uses the recorded cloud judge and reviser: judge Groq `qwen/qwen3.8-27b`, a different
family from the producer; reviser `gpt-oss-120b`. Base numbers reproduce the published ones: Member 2 cloud
0.98 / 0.91 / 1.00 / 0.98, rules 0.96 / 0.84 / 0.94 / 0.98; Member 3 cloud dependency F1 0.93, must-have 0.94,
rules 0.91 / 0.89.

## 1. Quality: base vs Self-Refine vs + Reflexion

### Extraction (Member 2's `document.extract`, 10 documents)

| Producer | Condition | Req F1 | Req P / R | Con F1 | Del F1 | Crit F1 | Priority |
|---|---|---|---|---|---|---|---|
| rules | base | 0.959 | 1.000 / 0.921 | 0.842 | 0.941 | 0.985 | 1.000 |
| rules | Self-Refine | **0.976** | 1.000 / 0.952 | **0.889** | 0.941 | 0.985 | 0.983 |
| rules | + Reflexion | **0.976** | 1.000 / 0.952 | **0.889** | 0.941 | 0.985 | 0.983 |
| replay (cloud) | base | 0.984 | 0.969 / 1.000 | 0.909 | 1.000 | 0.985 | 0.937 |
| replay (cloud) | Self-Refine | 0.984 | 0.969 / 1.000 | 0.909 | 1.000 | 0.985 | **0.952** |
| replay (cloud) | + Reflexion | 0.984 | 0.969 / 1.000 | 0.909 | 1.000 | 0.985 | **0.952** |

Where it changed (rules producer):

- **g10 long lab:** requirements 14 → 15 found (the judge spotted the missing "For each actor, describe at least two
  goals"; the reviser added it with a verified quote). Two non-constraints were dropped ("the lecture slides use a
  simpler garage…", "discuss your ideas with your lab partner…"): constraints F1 0.50 → 1.00.
- **g02 lab manual:** a missing requirement was added (6/6 found). But its priority differs from the gold set's, which
  is why priority accuracy drops 1.000 → 0.983. **One real mistake.**
- **g04 scanned:** two rounds, no gain, plateau. The original was kept (the regression guard worked).

With the cloud producer, only **g07 messy brief** changed: a priority fixed, 4/5 → 5/5 (this is the demo case).

**Bug found and fixed during evaluation:** on **g03 rubric** (a marking rubric with no requirements), an earlier
build flagged "no requirements" as major, and the reviser copied the 6 marking criteria in as requirements:
requirements precision 1.00 → 0.91. Now a pure rubric is not flagged, and an item that repeats a marking criterion
is refused. Covered by a test.

### Plan (Member 3's `plan.generate`, 9 plans)

| Producer | Condition | Valid | Coverage | Deps P / R / F1 | Must-have deps | Steps F1 |
|---|---|---|---|---|---|---|
| rules | base | 9/9 | 100 % | 0.935 / 0.894 / 0.914 | 0.886 | 0.754 |
| rules | Self-Refine | 9/9 | 100 % | 0.937 / 0.934 / **0.936** | **0.971** | 0.754 |
| rules | + Reflexion | 9/9 | 100 % | 0.937 / 0.934 / **0.936** | **0.971** | 0.754 |
| replay (cloud) | base | 9/9 | 100 % | 0.921 / 0.935 / 0.928 | 0.935 | 0.746 |
| replay (cloud) | Self-Refine | 9/9 | 100 % | 0.925 / 0.933 / 0.929 | 0.935 | 0.746 |
| replay (cloud) | + Reflexion | 9/9 | 100 % | 0.925 / 0.933 / 0.929 | 0.935 | 0.746 |

Where it changed:

- **rules long lab:** must-have dependencies 19/27 → **27/27**, dependency F1 0.77 → 0.89. The judge's P1 criterion
  ("does each step come after the steps whose results it needs?") found the build-order links "R7 needs R3–R6".
  The patch reviser added them, and Member 3's `finalize` re-validated the plan.
- **rules tcp chat:** 11/12 → 12/12.
- **cloud project brief:** dependency F1 0.867 → 0.873 (one round).
- **cloud long lab:** two rounds, no gain (plateau); the original was kept.

### What this says, plainly
- **Refinement helps where the output is weak**, and mostly with what code or a judge can point at: missing items
  with a quotable sentence, wrong-kind items, missing build-order links. On the rule-made outputs, all four headline
  metrics moved up and none went down, except priority accuracy, by one item.
- **On already-good cloud outputs it is close to a null result.** The judge mostly agrees, and the loop stops after
  one check (threshold). That is the honest finding, and it matches the literature: self-correction gains shrink
  when the first answer is good (research §4). It costs one judge call per step.
- **Reflexion = Self-Refine on these sets.** Its notes and strategy change only matter when a problem survives a
  round. That happened 4 times (g04 with both producers, g10, cloud long lab), and switching to "full" did not find
  anything that "targeted" missed. It costs 5–27 % more tokens. Kept on by default because it is cheap, but no measured gain.

## 2. Cost: rounds, tokens, calls, time

| Producer | Suite | Rounds / step (mean) | Tokens / step (mean) | Model calls (all) | Stop reasons | Improved |
|---|---|---|---|---|---|---|
| rules | extraction, Self-Refine | 0.4 | 3 337 | 16 | threshold 9, plateau 1 | 2 / 10 |
| rules | extraction, + Reflexion | 0.5 | 4 238 | 23 | threshold 9, plateau 1 | 2 / 10 |
| rules | plan, Self-Refine | 0.22 | 3 118 | 13 | threshold 9 | 2 / 9 |
| rules | plan, + Reflexion | 0.22 | 3 267 | 15 | threshold 9 | 2 / 9 |
| replay | extraction, Self-Refine | 0.3 | 2 446 | 13 | threshold 9, plateau 1 | 1 / 10 |
| replay | extraction, + Reflexion | 0.3 | 2 610 | 16 | threshold 9, plateau 1 | 1 / 10 |
| replay | plan, Self-Refine | 0.33 | 3 604 | 16 | threshold 8, plateau 1 | 1 / 9 |
| replay | plan, + Reflexion | 0.33 | 3 796 | 18 | threshold 8, plateau 1 | 1 / 9 |

- **Time** (from the live recording run, Groq):
  - Check only (one judge call): 0.8–1.6 s.
  - Check + one revision (3 calls): ≈ 7.7 s.
  - Two revisions that did not help (6 calls): ≈ 9.4 s.
  - Replayed: milliseconds.
  - Local model: 20–60 s per judge call; long cases hit the 180 s budget (§5).
- **No loop hit the budget or the 3-round cap**, and no run ended with an error.

## 3. Error labelling (taxonomy, item 4.7)

80 labelled issues in `samples/refine/taxonomy_gold.jsonl` (30 from real critic output on the gold sets, 50
hand-written), covering all 10 categories and 4 severities. The rules were tuned on the first half (dev) and checked
on the second half (held out).

| Labeller | Labelled | Right | Accuracy over all 80 |
|---|---|---|---|
| Rules only | 76 (95 %) | 75 (precision 98.7 %) | 93.8 % |
| Rules only, held-out half | 36 / 40 | 36 (100 %) | 90 % |
| Model only (`classify`, recorded) | 80 | 52 | 65 % |
| **Rules, then the model for the rest (shipped)** | 80 | **78** | **97.5 %** (dev 97.5 %, held-out 97.5 %) |
| The critic's own label (on the 24 real critic issues) | 24 | 16 | 67 % |
| Our classifier on the same 24 | 24 | 23 | 96 % |

The two remaining errors: an OMISSION labelled LOGIC (a missing dependency), and a SCHEMA labelled FACTUAL. The
model alone is weak (65 %), so rules go first and the model only fills the gaps. Every decision is logged
(rule / model / critic), so Member 11 has labelled data.

## 4. Critic calibration (stretch)

The judge's findings, checked against the gold labels:

| Producer / suite | Judge said "missing" | Judge said "drop this" | Dependency findings | Found only by judge / only by code / both |
|---|---|---|---|---|
| rules, extraction | 2 right, 0 wrong | 3 right, 0 wrong | — | 4 / 1 / 0 |
| rules, plan | — | — | 1 right, 0 wrong | 5 / 0 / 0 |
| replay, extraction | 0 | 0 | — | 0 / 1 / 1 (+3 other) |
| replay, plan | — | — | 2 not in the gold set (neither right nor wrong) | 6 / 0 / 0 (+5 other) |

When the judge said something concrete enough to check, it was right (6 / 6). It also raised "other" findings, such
as style and granularity, that the gold sets cannot score. The code checks found what the judge missed in 1–2
cases, which is why both run.

## 5. Local model only (not recorded)

`uv run python -m tests.refine.eval.run_eval --suite all --producer rules --refine-local --mode live --only
g02_lab_manual g10_long_lab tcp_chat long_lab` → `rules-local.json`. The rule-made outputs were refined by the local
`qwen3.5:9b` alone (judge, reviser, notes; no cloud) on an M-series laptop with 16 GB. The 4 cases were the ones
where the cloud judge found something. Live, not recorded.

| Case | Cloud judge (above) | Local judge | Rounds | Time (Self-Refine / + Reflexion) | Stop |
|---|---|---|---|---|---|
| g01 tcp chat (extraction) | nothing to fix | nothing to fix | 0 | 42 s / 19 s | threshold |
| g02 lab manual (extraction) | found the missing requirement → added | **missed it** (scored 1.0) | 0 | 34 s / 61 s | threshold |
| g10 long lab (extraction) | +1 requirement, 2 wrong constraints dropped | flagged 1 right drop, but its revision did not score higher | 1 | **332 s / 306 s** | **budget** (180 s) |
| tcp chat (plan) | 11/12 → 12/12 | nothing found | 0 | 59 s / 43 s | threshold |
| long lab (plan) | must-have 19/27 → 27/27 | **2 of its dependency findings were wrong** (0 right); no revision before the budget ran out | 0 | 217 s / 183 s | **budget** |

**Local result: no gain on any case, and no harm.** Keep-best kept every original, and no quality metric moved. One
local call takes 20–60 s for a judge check, and the 180 s budget stopped both long cases. The 9B judge is the same
model as the local producer, so it missed what the cloud judge found, and on the long plan it suggested wrong
dependencies. Local refinement is therefore not worth turning on as it is. A bigger local judge, or a longer budget
for the demo, are options for Member 11. With cloud keys present the `judge` role goes to the cloud first, which is
where the gains above come from.

## 6. Load and soak (item 4.20, stub agents, `infra/observability/load/soak.py`)

Each project is an 8-step plan (research → verify → design → 2 parallel builds → test → docs → review), auto-approved.
Each stub step takes 0.05 s, and there are two sets of agents.

| Stack | Projects | At once | Steps / s | Project time p50 / p95 / max | Failures | Max queue depth | Peak RSS | Free RAM (min) |
|---|---|---|---|---|---|---|---|---|
| in memory | 40 | 20 | 139 | 0.90 / 1.48 / 1.48 s | 0 | 45 | 147 MB | 3.5 GB |
| RabbitMQ + Postgres | 40 | 20 | 21.6 | 6.46 / 11.0 / 11.1 s | 0 | 122 | 179 MB | 4.5 GB |
| RabbitMQ + Postgres, **3-minute soak** | 540 (27 rounds) | 10 | 23.9 | 3.11 / 3.97 / 4.58 s | **0** | 85 | **185 MB** | 4.4 GB |

- **No failures, no leak:** RSS stayed flat at 179–185 MB over 3 minutes, and the latency did not drift between
  rounds.
- **The limit is the Manager, not the agents.** It takes one message at a time (prefetch 1, Sprint 1's ordering
  guarantee), and each step costs about 6 messages plus their Postgres writes. So ≈ 24 steps / s on the real stack
  vs 139 in memory.
- With 20 projects at once, p95 grows to 11 s while the queue depth reaches 122. With 10 at once it is 4 s. For a
  laptop with real model calls (seconds to minutes per step) this is far beyond what is needed. Member 11's release
  gate can reuse the script with `--soak-minutes`.

## 7. Honest weak spots
- Small gold sets (10 + 9). One item changes a percentage by several points. The gains above are real but counted
  in single items.
- The gold sets and rubrics are ours, and the extraction rubric's conventions (e.g. setup steps are not
  requirements) were written while looking at these documents.
- The judge on the cloud is a different family. Locally it is the same 9B model; it found nothing useful and 2
  of its plan findings were wrong (§5), so on a laptop without keys refinement is cost without gain.
- The priority mistake on g02 shows the reviser can add a right item with a wrong attribute. Keep-best only
  protects the **score**, and the score did not see the wrong priority.
- Recorded runs measure quality, not latency: replay takes milliseconds. Real latencies come from the recording
  run and the local run.
