# Research: autonomous coding (Member 7, written ahead of Sprint 7)

The coding agent takes a plan task, understands a small repository, finds the files to change, edits them with
tools, runs checks, debugs, and returns a `CodeChangeSet`, using the router's `coder` role (cloud keys first,
local `qwen3.5:9b` otherwise). Each topic ends with **→ plan**: what it means for Sprint 7. Working prototypes are in
`samples/coding/`: the mini benchmark, the jailed workspace, the edit applicator and the locator.

## 1. Coding agents
- **SWE-agent** (Yang et al., 2024): the **agent-computer interface** matters as much as the model. Small, clear
  commands (open a file window, search, edit a line range) with short, informative feedback beat a raw shell.
- **Aider** (Gauthier): a **repository map** of key symbols chosen with a graph ranking, and edit formats (search/
  replace blocks, unified diffs) chosen per model from its own edit benchmarks.
- **OpenHands** (Wang et al., 2024): an open platform where agents act through code and shell in a sandbox.
- **AutoCodeRover** (Zhang et al., 2024): program-structure-aware search (classes, methods) to find the code to
  change.
- **Agentless** (Xia et al., 2024): a fixed **localize → repair → validate** pipeline, without a free-form agent
  loop, is competitive and much cheaper.

**→ plan:**
- Follow the Agentless shape inside a bounded loop: locate → plan → edit → check → debug.
- Keep tools few and their feedback short (SWE-agent lesson). The prototype's errors are written to be acted on
  ("SEARCH matches 2 places; add the surrounding lines").

## 2. Understanding a repository
- **AST / tree-sitter** give exact symbols (functions, classes, imports) without running code.
- **Lexical retrieval:** BM25 (Robertson & Zaragoza, 2009) is strong when the task names the concept. **Embeddings**
  help when it doesn't. Retrieval-augmented code completion (RepoCoder, Zhang et al., 2023) shows that repository
  context improves results.
- A repo map must fit the model's context, so rank and cut.

**→ plan:**
- `repomap.py`: `ast` symbols + one-line summaries, cached by file hash.
- `locate.py`: BM25 (prototype: top-1 7/7 on the benchmark's modify / bug-fix tasks) + embeddings (`embed` role)
  + an LLM rerank of the top few. Measure top-3 on harder, bigger repos, since 7/7 on small repos is easy mode.

## 3. Edit formats
- Whole-file rewrites are simple but costly, and small models silently drop code. Search/replace blocks and unified
  diffs send only the change, but the model must quote the old code exactly.
- Aider's edit benchmarks show the best format depends on the model, and a **forgiving applicator** (whitespace
  tolerance) plus clear errors recovers many bad edits.

**→ plan:**
- `edits.py`: search/replace blocks; a unique exact match is required; a tolerant match is allowed only for
  trailing whitespace or a shifted block (and must also be unique); a syntax check runs after the edit; edits are
  atomic across files.
- Rejected edits go back to the model with the reason. The prototype covers each case (`check_tools.py`).

## 4. Debugging loops
- **Self-Debugging** (Chen et al., 2023) and **Reflexion** (Shinn et al., 2023): feeding back test output (and a
  short self-reflection) improves fixes over a few rounds. Without a stop rule, loops waste budget or make things
  worse.

**→ plan:**
- `debug.py`: parse the traceback (file, line, exception) → show that slice → one hypothesis → one edit → re-run.
- Bounded by Member 4's `StopPolicy` (max rounds, plateau, budget, tests pass).
- `code.revise` reuses the same loop with `revision.request` feedback.

## 5. Benchmarks and honest expectations
- **HumanEval** (Chen et al., 2021) and **MBPP** (Austin et al., 2021) are function-level. **pass@k** is
  estimated with the unbiased estimator from Chen et al. (2021).
- **SWE-bench** (Jimenez et al., 2024) uses real GitHub issues with hidden tests and is much harder. Lite and
  Verified are subsets.
- Small local models do well on function-level tasks and poorly on repository-level ones. So the planner keeps
  tasks small (Sprint 3 depth cap), and templates give greenfield work a head start.

**→ plan:**
- Item 7.12 is the prototype's 12 tasks (greenfield, modify-existing, bug-fix incl. multi-client TCP), each with
  hidden tests and a verified-fair starter.
- Item 7.13 reports pass@1 / pass@3, edit-apply rate, tokens and time for `coder` local vs cloud.

## 6. Safety
- The agent runs code a model wrote, so: confine file access (path jail incl. symlinks), allow-list commands (no
  shell, no `-c`, no package installs), drop the environment (no API keys), time and output limits, and audit every
  denial.
- **Prompt injection through repository content** (a comment saying "ignore your instructions") is a known risk
  for agents that read files. File content is data, never instructions.

**→ plan:**
- `workspace.py` (prototype: 32/32 attack and edge checks) is the Sprint 7 boundary.
- Member 8's Docker sandbox replaces the runner in Sprint 8 (no network, memory and process limits).
- Never pass `.env` or keys into a workspace.

## 7. Fitting on the laptop
- One file slice at a time; short prompts; temperature 0 for edits; the repo map cut to a token budget
  (`context_budget.py`).
- Successful trajectories (task → edits → passing tests) are recorded as fine-tune / benchmark data for Sprint 11.

## References
Yang et al. 2024 (SWE-agent) · Gauthier, Aider (repo map, edit formats, edit benchmarks) · Wang et al. 2024
(OpenHands) · Zhang et al. 2024 (AutoCodeRover) · Xia et al. 2024 (Agentless) · Robertson & Zaragoza 2009 (BM25) ·
Zhang et al. 2023 (RepoCoder) · Chen et al. 2023 (Self-Debugging) · Shinn et al. 2023 (Reflexion) · Chen et al. 2021
(HumanEval, pass@k) · Austin et al. 2021 (MBPP) · Jimenez et al. 2024 (SWE-bench).
