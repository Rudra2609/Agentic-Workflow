"""Shared pytest fixtures. Integration tests (marker ``integration``) skip themselves when infra is down."""

import os

# Never read the developer's .env in tests: it may hold the team's real cloud keys (CLAUDE.md: tests use fake/replay).
os.environ["HMAP_ENV_FILE"] = "none"
