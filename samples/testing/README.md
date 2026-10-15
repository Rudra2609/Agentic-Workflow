# Testing & execution prep (Member 8, prepared ahead of Sprint 8)

Two working pieces for Sprint 8, built ahead and runnable today with only Python 3.11 and Docker (no project code):

1. **`sandbox/`:** a prototype of the Docker sandbox that will run generated code (item 8.1), with an **abuse
   check that proves every limit**.
2. **`seeded_failures/`:** the seeded-failure suite (item 8.12): a known-good module + **15 broken variants**, each
   labelled, and a first rule-based failure classifier (item 8.8) that runs them all through the sandbox.

```bash
python3 samples/testing/sandbox/check_sandbox.py             # builds the image once; 8/8 limits hold
python3 samples/testing/seeded_failures/check_seeded.py      # 16/16 classified as labelled
python3 samples/testing/sandbox/run_sandbox.py <folder>      # run any folder's tests in the sandbox
```

## 1. The sandbox
`docker run` with: **no network** (`--network none`), a **read-only** root filesystem, the code in a size-capped
writable copy (`/work` tmpfs, never a host folder), a **non-root user** (uid 10001), **no capabilities**
(`--cap-drop ALL`, `no-new-privileges`), **memory** 256 MB with no swap, **1 CPU**, at most **64 processes**, a hard
**time limit** (the container is killed), and at most **64 KB of output** kept. The code is streamed in as a tar on
stdin, so nothing on the host is mounted. That also makes it work on Colima, which cannot mount external drives.

Inside, `stages.py` runs the pipeline: **static** (ruff, explicit rules), **security** (bandit), **unit** (pytest),
each with its own time limit, and prints one JSON summary.

Proof (`check_sandbox.py`, each case in `abuse/` attacks one limit):

| Case | Attack | Result |
|---|---|---|
| ok | a normal program | runs, output returned |
| network | DNS lookup + direct connection to 1.1.1.1 | both refused |
| write_outside | write to /etc, /usr, /opt, /, /home | all denied; /work and /tmp writable |
| not_root | check the user | uid 10001 |
| fork_bomb | fork 500 processes | stopped at 63 (pids limit) |
| infinite_loop | `while True` | killed at the 5 s limit |
| memory_hog | allocate 32 MB blocks forever | OOM-killed at about 224 MB |
| big_output | write 204 MB | 64 KB kept |

## 2. The seeded-failure suite
`good/chatproto.py` is a small TCP-chat protocol module (commands, unique nicknames across threads, message
framing) with 8 tests (`good/test_chatproto.py`). `build_variants.py` makes 15 variants, each with **one**
hand-written fault, and writes `labels.json`:

| Category | Variants | Caught by |
|---|---|---|
| SYNTAX | syntax_error | unit (collection fails) |
| IMPORT | import_error | unit |
| CRASH | name_error, recursion, type_error, not_implemented | unit (an exception other than an assertion) |
| ASSERTION | off_by_one, swapped_arguments, race_condition, swallowed_error | unit (a test's check fails) |
| TIMEOUT | infinite_loop | unit stage time limit |
| SECURITY | insecure_eval, shell_injection, hardcoded_secret | security stage (bandit); **the tests still pass** |
| LINT | lint_unused_import | static stage (ruff); the tests still pass |

`check_seeded.py` copies each version + the tests into the sandbox, runs the three stages, and classifies with
simple rules (time-out → TIMEOUT, `SyntaxError` → SYNTAX, import errors → IMPORT, a failed check → ASSERTION, any
other exception → CRASH, then bandit → SECURITY, then ruff → LINT). Result: **16/16 as labelled** (the good version
passes everything). The race-condition variant was caught 5 runs out of 5.

## Honest limits
- A prototype: Docker CLI calls, not the Docker SDK; one image (Python only); no integration stage (multi-process
  TCP server + clients); no coverage report.
- The classifier is rules only and was written next to these variants. Sprint 8 adds file/line hints, the
  `classify` model for unclear cases, and must be measured on failures it has not seen.
- Containers share the host kernel: this stops accidents and casual abuse, not a kernel exploit. gVisor or
  Firecracker would be the next step (Sprint 8 stretch).
- The sandbox image is built from the internet once (`python:3.11.17-slim`, pytest 9.1.1, ruff 0.16.9,
  bandit 1.9.4). Every run is then offline.
