# hmap — developer commands. Run `make help`.
BACKEND := backend
UV := uv --directory $(BACKEND)
COMPOSE := $(shell docker compose version >/dev/null 2>&1 && echo 'docker compose' || echo docker-compose)

.PHONY: help setup doctor cloud-check test test-unit lint fmt typecheck schemas contracts-snapshot check precommit regression infra-up infra-down obs-up obs-down obs-open agents api demo demo-replay demo-final reset-demo report stop security coding-venv sandbox-image

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-12s %s\n", $$1, $$2}'

setup: ## install backend dependencies (uv)
	$(UV) sync --all-extras

doctor: ## check the local toolchain
	@bash scripts/doctor.sh

cloud-check: ## which team cloud keys work, and does every cloud route answer (uses .env keys; no Ollama)
	@scripts/cloud_check.sh

test: ## run all backend tests (integration tests skip if infra is down)
	$(UV) run pytest

test-unit: ## run tests that need no Docker infra
	$(UV) run pytest -m "not integration"

lint: ## ruff lint
	$(UV) run ruff check src tests

fmt: ## ruff format
	$(UV) run ruff format src tests

typecheck: ## mypy (strict on hmap.core)
	$(UV) run mypy src/hmap/core

schemas: ## export JSON Schemas for every contract
	$(UV) run python -m hmap.core.contracts.export

contracts-snapshot: ## ACCEPT the current contracts as the new baseline (review the diff first!)
	$(UV) run python -m hmap.core.contracts.export tests/contracts/snapshots
	@echo "contract snapshot updated - mention it in your commit / HANDOFF.md"

check: lint typecheck test ## lint + typecheck + tests

precommit: ## everything before a commit/handoff: secrets, lint, types, all tests, frontend (scripts/precommit.sh)
	@scripts/precommit.sh

regression: ## did MY change break a test? usage: make regression BASE=../hmap_handoff/sprint-1_<date>
	@scripts/regression_check.sh --base $(BASE)

infra-up: ## start Postgres + RabbitMQ (Phase B)
	$(COMPOSE) -f infra/docker-compose.yml up -d --wait
	@scripts/infra_init.sh

infra-down: ## stop infra
	$(COMPOSE) -f infra/docker-compose.yml down

OBS_COMPOSE := $(COMPOSE) -f infra/docker-compose.obs.yml

obs-up: ## start Jaeger + Prometheus + Grafana (traces, metrics, alerts; Sprint 4) and print how to send data
	@HMAP_GRAFANA_PASSWORD="$${HMAP_GRAFANA_PASSWORD:-$$(grep -s '^HMAP_GRAFANA_PASSWORD=' .env | cut -d= -f2-)}"; \
	 HMAP_GRAFANA_PASSWORD="$${HMAP_GRAFANA_PASSWORD:-$$(openssl rand -hex 12)}" $(OBS_COMPOSE) up -d --build --wait --quiet-pull
	@echo "observability is up: Jaeger http://127.0.0.1:16686  Prometheus http://127.0.0.1:9090/alerts  Grafana http://127.0.0.1:3001"
	@echo "send traces from the app: export HMAP_OTEL_ENDPOINT=http://127.0.0.1:4318 (or put it in .env), then restart make api / make agents"

obs-down: ## stop the observability stack (its data is kept in a volume until infra is pruned)
	$(OBS_COMPOSE) down

obs-open: ## open Jaeger, Prometheus alerts and the Grafana dashboard in the browser
	@for u in http://127.0.0.1:16686 http://127.0.0.1:9090/alerts http://127.0.0.1:3001/d/hmap-overview; do \
	  (command -v open >/dev/null && open "$$u") || (command -v xdg-open >/dev/null && xdg-open "$$u") || echo "$$u"; done

agents: ## run every discovered agent in one process
	$(UV) run hmap-agents run --all

api: ## run the FastAPI app with reload
	$(UV) run uvicorn hmap.api.app:create_app --factory --reload --port 8000

demo: ## the whole platform on this laptop, live (cloud keys, then Ollama), pre-flight first: http://127.0.0.1:3000 (Sprint 9)
	@DEMO_MODE=live scripts/demo.sh

demo-replay: ## the same demo offline: recorded answers + saved pages, works with Ollama stopped and Wi-Fi off
	@DEMO_MODE=replay scripts/demo.sh

demo-final: ## the three golden end-to-end scenarios on the whole platform, replayed (Sprint 10; --record: see the script)
	@scripts/demo_final.sh

models-pull: ## local models for a tier: make models-pull TIER=lite|1|2 (0 = replay only; Sprint 11)
	@scripts/pull_models.sh --tier $(or $(TIER),1)

bench: ## model benchmark, replayed (quick set, every recorded model) + the router's quality table (Sprint 11)
	@cd backend && for f in ../samples/models/bench/results/quick_*.json; do m=$$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['model'])" $$f); \
	  HMAP_ENV_FILE=none $(UV) run --frozen python -m hmap.agents.models.bench.run quick --mode replay --models $$m; done; \
	  $(UV) run --frozen python -m hmap.agents.models.bench.run table >/dev/null && echo "table: samples/models/bench/table.json"

release-matrix: ## final release gate: every sprint's tests x LLM mode x router on/off x tier (Sprint 11; long)
	@scripts/release_matrix.sh

reset-demo: ## back to the demo state: empty database + no artifacts (asks first; the next make demo seeds again)
	@scripts/reset_demo.sh

report: ## final-report skeleton from every member's research / design / eval docs -> reports/final-report.md
	@$(UV) run --frozen python -m hmap.agents.docgen.compile_report

stop: ## stop everything `make demo` started
	@scripts/stop.sh

security: ## security checks: secrets, leaks, dependency audit, security tests (scripts/security_check.sh)
	@scripts/security_check.sh

CODING_VENV := data/coding/venv

coding-venv: ## interpreter for the coding agent's generated code: pytest + fastapi + httpx, no hmap, no keys (Sprint 7)
	uv venv --quiet --allow-existing --python 3.11 $(CODING_VENV)
	uv pip install --quiet --python $(CODING_VENV)/bin/python pytest==9.1.1 fastapi==0.143.0 httpx==0.28.1 \
	  starlette==1.7.0 pydantic==2.14.0
	@echo "coding venv ready: $(CODING_VENV) (used automatically unless HMAP_CODING_PYTHON is set)"

sandbox-image: ## Docker images the testing agent runs generated code in: Python + Node (needs the internet once; Sprint 8)
	docker build -t hmap-sandbox-py:1 backend/src/hmap/agents/testing/sandbox
	docker build -t hmap-sandbox-node:1 -f backend/src/hmap/agents/testing/sandbox/Dockerfile.node \
	  backend/src/hmap/agents/testing/sandbox
