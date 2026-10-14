# 03 — Sprint Process & Handoff Procedure

## 1. Sequential rule

```text
Sprint 1 (M1) ──► Sprint 2 (M2) ──► … ──► Sprint 6 (M6) ──► MID-EVAL ──► Sprint 7 (M7) ──► … ──► Sprint 11 (M11) ══► FINAL RELEASE GATE (end of Sprint 11)
```
- Member *N+1* starts coding only when Sprint *N* is **accepted** (all Definition-of-Done items ticked).
- Research documents are written in parallel from day 0 (see doc 00 §F).
- If a sprint overruns, the next one slips — so each sprint file separates **Must** from **Stretch**; Stretch items go to the owner-named backlog in `HANDOFF.md` (or to the cross-cutting owner listed in `sprints/README.md`) rather than blocking handoff.

## 2. Handoff procedure (what happens after each sprint)

1. Sprint owner (or the assistant, when it builds that sprint) finishes code + tests + docs.
2. Run `scripts/check_sprint.sh <n>` (created in Sprint 1): lint, type-check core, all tests up to sprint *n*, demo smoke test.
3. Write/refresh `HANDOFF.md` (template below).
4. **Assistant tells you the sprint is done.** You then duplicate the folder:
   ```bash
   scripts/make_handoff.sh <n>      # creates ../hmap_handoff/sprint-<n>_<date>/ (excludes .venv, node_modules, .next, caches, .env, large model files)
   ```
   (or copy the folder manually — the script just does it consistently.)
5. Give that folder to Member *n+1*. They work **in their copy**, then return **only their changed folders** (the ownership rule in doc 01 §2 makes this a clean diff). Before returning them they run `scripts/precommit.sh --member <n+1> --base <the folder they received>` and attach the `reports/regression-*.md` it writes.
6. You merge their folders back into the master folder and run `scripts/regression_check.sh --base ../hmap_handoff/sprint-<n>_<date> --member <n+1>`, then `check_sprint.sh`, and the cycle repeats. If something broke, the report shows whether it was caused by the merge (`NEW_FAILURE`, with a **Likely cause** section naming the changed files and their owners) or was already broken in the snapshot (`PRE_EXISTING`). Flaky tests are reported separately as `FLAKY`. See `CONTRIBUTING.md` §6.

> No git operations are performed by the assistant. If the team later wants to push, that is a deliberate separate step by you.

### `HANDOFF.md` template
```markdown
# Handoff — end of Sprint N (Member N: <area>)
## What now works            (bullets + how to run the demo: one command)
## Public interfaces added   (contracts, capabilities, API routes, events, DB tables)
## How the next member plugs in   (exact stub to replace, exact input/output types)
## Config / env vars added
## Known limitations / tech debt
## Test status               (command + result)
## Deferred (name the receiving member/sprint)
```

## 3. Definition of Done (every sprint)

- [ ] Research doc: `docs/members/<n>/research.md` (concepts, approaches, trade-offs, chosen approach, sources)
- [ ] Design doc: `docs/members/<n>/design.md` (I/O, data structures, interfaces, failure modes)
- [ ] Implementation matches the contracts in doc 01 (JSON-Schema-validated in tests)
- [ ] Agent registered via its `plugin.py` with correct capabilities; its stub yields automatically; works over the real bus; **no file outside the member's own folders changed**
- [ ] Uses LLM only through the gateway roles; works in `fake` and `replay` modes
- [ ] Unit tests + ≥1 integration test over RabbitMQ/Postgres; evaluation metrics recorded in `docs/members/<n>/eval.md`
- [ ] API router + minimal UI panel for the subsystem
- [ ] Demo script `scripts/demo_sprint_<n>.sh` runs end-to-end
- [ ] Previous sprints' tests still green (no regressions)
- [ ] `HANDOFF.md` updated; `README` of the member folder explains run/inputs/outputs/limitations (matches "What every member should deliver" in the team guide)

## 4. Branch/merge discipline without git
- Master folder = single source of truth, held by you.
- Members never edit `core/` or `manager/` — they file a request to Member 1 (a note in `docs/members/<n>/core-requests.md`). Agents, routers, Manager hooks, UI panels and compose services are auto-discovered from their folders (Sprint 1 §3.5), so a returned folder set never touches a shared file.
- Replay-cache fixtures live in `samples/llm_cache/<plugin>/` (one file per request), so merging them is a plain folder copy.
- DB migrations: one file per sprint, named `NNN_sprint_<n>_<topic>.py`, linear chain, so merges can't conflict.

## 5. Assessment hooks (per member, for the team's own grading)
Each member can show: research doc, design doc, working subsystem demo, eval numbers, and an explanation of how it connects to the platform — mirrors the "What Every Member Should Deliver" list in the team guide.
