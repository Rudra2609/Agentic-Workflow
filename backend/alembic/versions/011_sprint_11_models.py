"""Sprint 11 (Member 11): the model registry, the router's decision log, benchmark results and fine-tune runs
(``hmap.agents.models.store``). No prompt or answer text is stored anywhere here: a route decision keeps the role,
plug-in, model, reason and outcome only.

Revision ID: 011
Revises: 006
Create Date: 2026-11-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "011"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE model_registry (
            id           text        PRIMARY KEY,           -- ollama name, provider:model, mlx:<path>
            spec         jsonb       NOT NULL,              -- ModelSpec
            digest       text,
            source       text        NOT NULL DEFAULT 'snapshot',
            pinned       boolean     NOT NULL DEFAULT false,
            resident_gb  real,
            details      jsonb       NOT NULL DEFAULT '{}'::jsonb,
            last_seen    timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("""
        CREATE TABLE route_decisions (
            id            text        PRIMARY KEY,
            at            timestamptz NOT NULL DEFAULT now(),
            role          text        NOT NULL,
            plugin        text        NOT NULL,
            model         text        NOT NULL,
            backend       text        NOT NULL,
            reason        text        NOT NULL DEFAULT '',
            rule          text        NOT NULL DEFAULT '',
            chain         jsonb       NOT NULL DEFAULT '[]'::jsonb,
            est_tokens    integer     NOT NULL DEFAULT 0,
            answered_by   text,
            ok            boolean,
            latency_s     real,
            input_tokens  integer     NOT NULL DEFAULT 0,
            output_tokens integer     NOT NULL DEFAULT 0,
            attempts      integer     NOT NULL DEFAULT 0,
            rate_limited  integer     NOT NULL DEFAULT 0,
            error         text        NOT NULL DEFAULT ''
        )""")
    op.execute("CREATE INDEX ix_route_decisions_at ON route_decisions (at DESC)")
    op.execute("""
        CREATE TABLE benchmark_results (
            id            bigserial   PRIMARY KEY,
            at            timestamptz NOT NULL DEFAULT now(),
            run_id        text        NOT NULL,
            set_name      text        NOT NULL,
            model         text        NOT NULL,
            quant         text,
            role          text        NOT NULL,
            task          text        NOT NULL,
            quality_score real        NOT NULL,
            tok_s         real,
            ttft_s        real,
            mem_gb        real,
            n             integer     NOT NULL DEFAULT 0,
            digest        text,
            seconds       real,
            notes         text        NOT NULL DEFAULT ''
        )""")
    op.execute("CREATE INDEX ix_benchmark_results_model ON benchmark_results (model, role, at DESC)")
    op.execute("""
        CREATE TABLE finetune_runs (
            id      text        PRIMARY KEY,
            at      timestamptz NOT NULL DEFAULT now(),
            skill   text        NOT NULL,
            base    text        NOT NULL,
            status  text        NOT NULL,                  -- prepared / trained / evaluated / failed
            config  jsonb       NOT NULL DEFAULT '{}'::jsonb,
            result  jsonb       NOT NULL DEFAULT '{}'::jsonb
        )""")


def downgrade() -> None:
    for table in ("finetune_runs", "benchmark_results", "route_decisions", "model_registry"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
