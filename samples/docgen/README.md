# Documentation-grounding prep (Member 9, prepared ahead of Sprint 9)

A working prototype of the core of Sprint 9: **documentation may only claim what the code really contains**
("if there's no Redis in the code, never say Redis"). Plain Python 3.11, standard library only: no Docker, no model,
no project code.

```bash
python3 samples/docgen/check_grounding.py                         # the whole check; prints OK
python3 samples/docgen/inspect_repo.py samples/docgen/repos/todo_api            # facts of one repo (JSON)
python3 samples/docgen/inspect_repo.py samples/docgen/repos/todo_api --mermaid  # its component diagram
python3 samples/docgen/grounding.py samples/docgen/repos/todo_api               # check its README claim by claim
python3 samples/docgen/draft_readme.py samples/docgen/repos/todo_api            # facts-first README draft
```

## Pieces
| File | Sprint 9 item | What it does |
|---|---|---|
| `inspect_repo.py` | 9.1, 9.2 | Reads the code with `ast` (nothing is run): files, functions, classes, imports, dependencies (`requirements.txt`, `pyproject.toml`), FastAPI / Flask routes, argparse flags and choices, environment variables, ports, entry points, tests. Draws the import graph as Mermaid. |
| `grounding.py` | 9.6 | Pulls technical claims out of Markdown (technologies, endpoints, env vars, paths, functions and classes, flags, commands, ports, versions) and checks each against the facts. Says *why* a claim is ungrounded. |
| `draft_readme.py` | 9.4 | A README draft built only from facts, so it is grounded by construction; a model writes only the prose paragraph later. |
| `check_grounding.py` | 9.12 | Runs everything on the sample repos and the seeded false claims; writes `out/<repo>/{facts.json, architecture.mmd, README.draft.md}`. |
| `repos/` | 9.11 | Three small hand-written projects with correct READMEs: `tcp_chat` (sockets + threads), `todo_api` (FastAPI + SQLite), `csv_report` (argparse CLI + a Flask view). |
| `seeded.json` | 9.12 | 34 hand-written false sentences, one at a time appended to a correct README. |

## Results (`check_grounding.py`)
| Check | Result |
|---|---|
| Hand-written READMEs (3 repos, 63 claims) | **63/63 grounded**: no false alarm |
| Facts-first drafts (80 claims) | **80/80 grounded** |
| Seeded false claims | **31/31 caught**: TECH 8/8 (Redis, PostgreSQL, JWT, Docker, asyncio, pandas, Django), COMMAND 5/5, ENDPOINT 4/4, ENV 3/3, PATH 3/3, PORT 3/3, SYMBOL 3/3, VERSION 2/2 |
| Behaviour claims ("nicknames are case-sensitive") | **0/3**: expected, rules cannot read behaviour |

Some catches are subtle: `asyncio` in a threaded server, `PUT` on a path that only has `GET`/`DELETE`,
`--format pdf` when the option accepts only `md`/`html`, port 5000 (Flask's default) when the code says 5001,
`pip install -e ".[docs]"` when the only extra is `dev`. Negations are respected: "does not need Docker" is not a
claim of Docker.

## Honest limits
- The rules were written next to these seeds, so 31/31 is an upper bound. Sprint 9 must measure on documents a
  model wrote for repos the rules have never seen (item 9.12).
- Behaviour claims need a model (claim → evidence → verdict, the same NLI-style check as Member 6's verifier).
- Python only. On the platform's own backend the extractor runs in 0.3 s (190 modules, 59 routes), but it finds only
  5 environment variables: settings read through pydantic-settings (`HMAP_` prefix) are not recognised yet.
- Code examples are only checked for existence (script, module, flags), not run. Running them is item 9.7, in
  Member 8's sandbox.
