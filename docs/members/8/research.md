# Research — automated testing & execution (Member 8, written ahead of Sprint 8)

The testing agent runs generated code safely, checks it (static → unit → integration → security), explains
failures, and drives a bounded code ↔ test loop with Member 7. Each topic below ends with **→ plan**: what it means
for Sprint 8. Working prototypes are ready in `samples/testing/`: the sandbox and the seeded-failure suite.

## 1. Testing levels and what to automate
- **Test pyramid** (Cohn; Fowler, "The Practical Test Pyramid"): many fast unit tests, fewer integration tests, very
  few end-to-end tests. Unit failures point to a line; e2e failures only say "something broke".
- **Property-based testing** (QuickCheck, Claessen & Hughes 2000; Hypothesis for Python) generates many inputs from
  a rule, and is good at finding edge cases a model would not think of.

**→ plan:** stages in order of cost: static → import / build → unit → integration (e.g. TCP server + N clients) →
security. Stop early on a cheap failure. Use Hypothesis for parsers and framing code (the seeded module's `unframe`
is a natural target).

## 2. LLM-generated tests and their pitfalls
- Models write tests quickly, but often **assert the current (buggy) behaviour** ("tests that assert bugs"),
  duplicate each other, or test nothing (Schäfer et al., 2023, "An empirical evaluation of using LLMs for automated
  unit test generation"; ChatUniTest, Chen et al., 2023).
- **Mutation testing** (DeMillo et al., 1978; mutmut for Python) measures whether tests catch planted faults, a
  better quality signal than coverage.

**→ plan:**
- Generated tests are marked "generated" and must pass a sanity gate: **fail on a known-bad version and pass on a
  known-good one** (item 8.7).
- The seeded variants are exactly that known-bad set, and mutation testing is a stretch.

## 3. Static analysis and security checks
- **Static analysis:** linters (ruff, pylint) and type checkers (mypy) find a class of bugs with no execution.
- **Security:** bandit (Python AST security rules: `eval`, `shell=True`, hard-coded passwords), semgrep (pattern
  rules), secret scanners, and dependency audits (pip-audit against advisory databases).

**→ plan:**
- Static stage = ruff with an **explicit** rule list (defaults change between versions; found while building the
  prototype) + mypy where configured.
- Security stage = bandit + a secret regex + pip-audit with an offline database.
- The 3 SECURITY variants pass all their unit tests, which is why this stage exists.

## 4. Container sandboxing
- **Linux isolation:** namespaces (what a process can see) and cgroups (what it may use: memory, CPU, pids);
  seccomp filters system calls; dropping capabilities and `no-new-privileges` stop privilege gain; **rootless**
  containers and user namespaces reduce the impact of an escape.
- Containers **share the host kernel**, so stronger isolation uses user-space kernels (gVisor) or micro-VMs
  (Firecracker; Agache et al., NSDI 2020).
- **Known abuse patterns:** network exfiltration, fork bombs, memory or disk exhaustion, endless loops, output
  floods, writing outside the workspace. The Docker socket (`/var/run/docker.sock`) inside a container is
  root-equivalent on the host.

**→ plan:**
- Every run: `--network none`, `--read-only` + a tmpfs workspace, uid 10001, `--cap-drop ALL`,
  `no-new-privileges`, memory without swap, CPU and pids limits, a hard timeout, an output cap.
- **The prototype proves each with an attack (8/8).**
- The testing agent runs **on the host** and talks to Docker directly (never a mounted socket in a container),
  which is the recommended choice in the sprint's §4. gVisor is a stretch.

## 5. Flaky tests
- Flaky tests pass and fail on the same code (Luo et al., 2014, "An empirical analysis of flaky tests"). Common
  causes: async waits, concurrency, test order, time, network.
- Detection: rerun failures (iDFlakies, Lam et al., 2019) and quarantine.

**→ plan:**
- A failed test is re-run once in a fresh container. Pass-then-fail is marked FLAKY (not sent to Member 7 as a
  bug) and reported separately.
- The race-condition variant uses a deliberate pause, so it fails deterministically (5/5 runs). Real races will be
  less polite.

## 6. Failure triage and classification
- Classify failures first, then explain them (fault localisation: Wong et al., 2016 survey). Categories that fit
  our pipeline: SYNTAX, IMPORT, ASSERTION, TIMEOUT, CRASH, SECURITY, LINT, ENV.
- Rules handle most cases from the error type and the stage; a model is useful only for the message and hint.

**→ plan:**
- `analyze.py`: rules first (exception type, stage, timeout), then `ctx.llm.classify` for unclear cases, with
  file / line from the traceback and a short hint.
- The prototype's rules already classify the 16 seeded cases correctly. They must be measured on unseen failures.

## 7. Test-driven repair loops
- **Self-Debugging** (Chen et al., 2023) and **Reflexion** (Shinn et al., 2023) show that models fix code better
  when given test feedback.
- SWE-bench-style agents iterate patch → test → patch. Without a stop rule they loop or regress.

**→ plan:**
- The `TestReport` → `revision.request` → re-run loop is bounded by Member 4's `StopPolicy` (max rounds, plateau,
  budget, `TestsPass`).
- Measure the fix rate on the seeded variants (item 8.9).

## 8. Fitting in 16 GB
Docker + the platform + Ollama share one laptop. The prototype uses 256 MB per run, one run at a time (concurrency 1
in item 8.11), and a pre-built image (the first build needs the internet; runs are offline).

## References
Claessen & Hughes 2000 (QuickCheck) · DeMillo, Lipton & Sayward 1978 (mutation testing) · Luo et al. 2014 (flaky
tests) · Lam et al. 2019 (iDFlakies) · Wong et al. 2016 (fault-localisation survey) · Schäfer et al. 2023 (LLM unit
test generation) · Chen et al. 2023 (ChatUniTest; Self-Debugging) · Shinn et al. 2023 (Reflexion) · Agache et al.
2020 (Firecracker) · Fowler, "The Practical Test Pyramid" · Docker security documentation (namespaces, cgroups,
seccomp, rootless mode).
