# hmap — developer commands. Run `make help`.
BACKEND := backend
UV := uv --directory $(BACKEND)
COMPOSE := $(shell docker compose version >/dev/null 2>&1 && echo 'docker compose' || echo docker-compose)

.PHONY: help setup doctor cloud-check test test-unit lint fmt typecheck schemas contracts-snapshot check precommit regression infra-up infra-down agents api

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

agents: ## run every discovered agent in one process
	$(UV) run hmap-agents run --all

api: ## run the FastAPI app with reload
	$(UV) run uvicorn hmap.api.app:create_app --factory --reload --port 8000
