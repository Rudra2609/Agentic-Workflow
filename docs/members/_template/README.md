# Member <N> — <subsystem>

Copy this folder to `docs/members/<N>/` and fill every section. Keep it short and factual.

| | |
|---|---|
| Plug-in | `backend/src/hmap/agents/<name>/` |
| Capability(ies) | `<capability>` → returns `<artifact type>` / `<Contract>` (`CAPABILITY_OUTPUTS`) |
| Inputs | what arrives in `TaskAssign` (artifact refs, inputs) |
| UI panel | `frontend/src/features/<name>/` |
| API | `/api/<name>/...` |

## Run
```bash
cd backend && uv run pytest tests/<name> -q          # unit + replay tests
HMAP_LLM_MODE=replay make agents                      # run your agent with recorded answers
scripts/demo_sprint_<N>.sh                             # your sprint demo
```

## Limitations
- …
