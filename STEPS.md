# Sprint 6 (Member 6): how to commit this

This zip holds **only the files Sprint 6 adds or changes** compared with the team repo's `main` (commit `0c20ab6`,
"Merge pull request #10 from Rudra2609/prep-member-8"). Paths inside `files/` are repository paths. `FILES.txt` lists all 567 of them.
`HANDOFF.md` is for reading only (it is git-ignored in the repo; do not copy it in).

There is no `.env` and no key in this zip; never add your `.env` to the commit.

## Steps (macOS / Linux / Git Bash)

```bash
# 1. get an up-to-date main
git clone https://github.com/Rudra2609/Agentic-Workflow.git     # skip if you already have it
cd Agentic-Workflow
git checkout main
git pull origin main

# 2. your branch
git checkout -b sprint-6-member-6

# 3. copy the Sprint 6 files over the repo (adjust the path to where you unzipped)
rsync -a ~/Downloads/IT_314_Project_Group23_Member6_Sprint6/files/ ./

# 4. stage them; .gitignore hides samples/llm_cache/ (since Sprint 5) and every file named CONTRIBUTING.md, so these two need -f
git add -A
git add -f samples/llm_cache/verify samples/verify/injection/repo/CONTRIBUTING.md

# 5. check: exactly the 567 listed files, nothing else (no output from the diff = good)
git diff --cached --name-only | sort > /tmp/staged.txt
sort ~/Downloads/IT_314_Project_Group23_Member6_Sprint6/FILES.txt | diff - /tmp/staged.txt && echo "OK: matches FILES.txt"

# 6. commit (message below) and push
git commit -F ~/Downloads/IT_314_Project_Group23_Member6_Sprint6/COMMIT_MESSAGE.txt
git push -u origin sprint-6-member-6
```

Then open a pull request `sprint-6-member-6` → `main` on GitHub (title: the first line of the commit message).

**Windows without Git Bash:** in step 3 copy the *contents* of `files\` into the repo folder in Explorer and choose
"Replace the files in the destination"; run the git commands in PowerShell. Step 5's check: `git diff --cached
--stat` should end with "567 files changed". The `.sh` scripts must stay executable: after `git add`, run
`git update-index --chmod=+x scripts/demo.sh scripts/stop.sh scripts/demo_chaos.sh scripts/demo_sprint_6.sh
scripts/security_check.sh scripts/check_sprint.sh`.

## If step 5 shows a difference
- **Extra files** (something you had locally): `git restore --staged <file>` to leave them out.
- **Missing files**: check that the copy in step 3 went into the repo root (you should have
  `backend/src/hmap/agents/verify/agent.py` in the repo after it).
- **A shared file shows a conflict-looking change** (e.g. `manager.py`, `Makefile`): `main` changed after this zip
  was made. Stop and tell Member 1 before committing.

## Running it after the commit
Tests: `cd backend && uv sync && uv run pytest -q -m "not integration"` passes on `main` + this commit (checked on a
fresh clone: 923 passed, 3 known xfails). `scripts/demo_sprint_6.sh` (and `make demo`) also need **Member 5's
research recordings** (`samples/llm_cache/research/`, `samples/research/search_cache/`), which are not in the team
repo yet (git-ignored since Sprint 5). Without them the demo fails with "0 finding(s) flagged"; with them it passes.
That is Member 5's / Member 1's to commit, not part of this commit; ask Member 1 for a copy to run the demo.

## What is in it
- Own folders (537 files): `backend/src/hmap/agents/verify/`, `backend/tests/verify/`, `frontend/src/features/verify/`,
  `docs/members/6/`, `samples/verify/`, `samples/llm_cache/verify/` (483 replay recordings, no keys),
  `backend/alembic/versions/006_sprint_6_verify.py`.
- Shared paths approved by Member 1 in the plan (30 files, listed in the commit message): the security hooks in
  `core/` and `manager/`, the API limits, `Makefile` (`make demo` / `make stop` / `make security`), the demo, chaos
  and security scripts, `samples/demo/`, `README.md`, `docs/sprints/mid-evaluation.md`, `ownership.toml`.
