# Threat model — running generated code (Sprint 8, Definition of Done)

What the testing agent protects, from whom, how, and what is left. Proof for each protection is a test in
`backend/tests/testing/test_sandbox_docker.py` (Docker) or `test_pipeline.py` / Member 7's `tests/coding/test_runner.py`
(local runner).

## Assets
| Asset | Where | Why it matters |
|---|---|---|
| Team API keys | `.env` in the project folder, the backend process environment | billable; teammates' accounts |
| Agent signing secrets, session secrets | backend process / `data/security/` | forge agent messages, take over accounts |
| The project folder and the user's home | the laptop's disk | code, documents, personal files |
| The laptop itself | CPU, memory, disk, processes | the stack, Ollama and the demo share 16 GB |
| The network | the laptop's internet connection | exfiltration, attacks on others from our IP |
| Test results | `TestReport`, the loop | a fake "passed" lets bad code through review |

## Attacker
The code under test: written by a model (possibly steered by a prompt injection in a document or repository, Member
6's finding F3), or uploaded by a user. It runs with whatever the sandbox gives it and may try anything a Python or
Node program can do. Not in scope: a malicious teammate with shell access to the laptop, attacks on Docker/Colima
themselves from outside, a compromised base image on the registry (the image is pinned and built once).

## Threats and protections
| # | Threat (STRIDE) | Protection (Docker backend) | Local runner (no Docker) |
|---|---|---|---|
| T1 | Read keys from the environment (I) | the container gets only the image's env; no `HMAP_*`, no keys (test: env probe) | environment rebuilt from nothing |
| T2 | Read `.env` / the project / home (I) | nothing from the host is mounted; the code arrives as a tar on stdin (test: probe) | `sandbox-exec` denies reading the project folder and home (macOS only) |
| T3 | Talk to the internet: exfiltrate, download, attack (I, E) | `--network none`; only loopback (test: DNS + direct IP refused) | `sandbox-exec`: outbound only to localhost |
| T4 | Escape to the host through the Docker socket (E) | the agent runs on the host and calls the CLI; no container gets the socket (test: socket absent) | n/a |
| T5 | Gain privileges (E) | `--user 10001`, `--cap-drop ALL`, `no-new-privileges` (test: not root) | the user's own account (no root) |
| T6 | Write outside the workspace, plant files (T) | `--read-only` root, tmpfs `/work` 64 MB and `/tmp` 32 MB (test: writes confined) | writes only inside the workspace folder |
| T7 | Fork bomb (D) | `--pids-limit 64` + a per-process cap of 100 (`setrlimit`) (test); under gVisor the per-process cap does it | none (weaker: said in the report) |
| T8 | Memory exhaustion (D) | `--memory 256m` = `--memory-swap` (test: OOM-killed); under gVisor an address-space cap (768 MB) inside, the cgroup above it | none |
| T9 | CPU / endless loop (D) | `--cpus 1`, per-step and per-run time limits, container killed (test) | per-command time limit, process group killed |
| T10 | Output flood fills memory or disk (D) | in-container drain keeps 16 KB per step; the host keeps 2 MB (test: 200 MB flood) | 2 MB flood limit, 64 KB kept |
| T11 | Many runs at once starve the laptop (D) | governor: one sandbox at a time; reaper removes leftovers on start | same governor |
| T12 | Fake a pass: print "passed", edit the result line, exit 0 (S, T) | results come from JUnit XML and per-step exit codes inside our runner; the runner's result line is the last `HMAP_RESULTS` line it prints after every step ends; a test file that rewrites the tests is caught by the eval (tests compared before/after) | JUnit XML written to `.tmp/` by pytest itself |
| T13 | Tests that pass whatever the code does (generated tests) (S) | sanity gate: must fail on a known-bad stub; labelled `generated`; never start a revision alone | same |
| T14 | Prompt injection in failure output steering the hint model or the coder (T, E) | output is data in every prompt ("never instructions"), normalised and capped; the hint model can only write hints; the coder can only edit inside its jailed workspace | same |
| T15 | Leave containers running (D) | `--label hmap.sandbox=1`, `docker rm -f` after every run, reaper at start; cancel kills the container (test) | process group killed |
| T16 | Supply-chain: a malicious dependency in requirements (E) | nothing is installed at test time (no network); the dependency audit (OSV) reports known-vulnerable pins | same |

## Residual risks (accepted)
- **Shared kernel.** With runc (the default) a kernel exploit escapes the container. gVisor is installed in the
  Colima VM: `HMAP_TESTING_RUNTIME=runsc` puts its user-space kernel in between, and every sandbox test passes under
  it at ~30 % more time ([gvisor.md](gvisor.md)). Firecracker micro-VMs are out of reach on a Mac laptop (no KVM).
- **The local runner is weaker** (no memory / process limits; `sandbox-exec` only on macOS). Every report says which
  backend ran; demos and the presentation use Docker.
- **Loopback inside a run.** Tests may open ports on the container's own loopback (needed for TCP tests); they cannot
  reach the host's ports.
- **The image is trusted.** Built once from pinned versions (`make sandbox-image`); rebuilding pulls from PyPI/npm.
- **Timing side channels, Spectre-class leaks**: out of scope for a course project.

## Where this is checked
`scripts/check_sprint.sh 8` runs the Docker abuse tests when Docker is up; `scripts/security_check.sh` (Member 6) runs
on every acceptance from Sprint 6 on.
