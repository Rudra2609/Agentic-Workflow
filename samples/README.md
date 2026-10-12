# samples/

| Folder | Owner | Content |
|---|---|---|
| `demo/` | Member 1 | input documents for the demos (`tcp_chat_assignment.txt` is used by `scripts/demo_sprint_1.sh` and `scripts/seed.sh`) |
| `llm_cache/<plugin>/` | the plug-in's owner | LLM replay cache, one JSON file per request (see `llm_cache/README.md`) |
| `<plugin>/` (e.g. `doc_intel/`, `planning/`) | the plug-in's owner | evaluation inputs and expected outputs for that member's `eval.md` |
| `model_bakeoff/` | Member 1 / 11 | the model bake-off datasets and results (`docs/members/11/model-choice.md`) |

Never put API keys, `.env` content or personal data in this folder: `scripts/secret_scan.sh` checks it before every
handoff.
