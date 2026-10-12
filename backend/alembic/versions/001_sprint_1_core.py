"""Sprint 1 core schema (item 1.5; research §17, §18, §22, §24, §34).

Manager-owned state (projects, tasks, executions, approvals) keeps the columns queries filter/sort on as typed
columns and the full record as ``data`` jsonb (the record model is the source of truth on read). The rest is
typed throughout. Unique keys from research §34: inbox ``(consumer_id, message_id)``, ``(task_id, attempt)``,
``(context_id, version)``, ``(artifact_id, version)``; task/project ``state_version`` is the CAS column.
``events`` is append-only (a trigger rejects UPDATE/DELETE). No foreign keys between Manager tables: the in-memory
store has none either and the Manager inserts in its own order inside one transaction.

Revision ID: 001
Revises:
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")


def _jsonb(name: str, *, default: str = "'{}'::jsonb") -> "sa.Column[object]":
    return sa.Column(name, pg.JSONB(), nullable=False, server_default=sa.text(default))


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("project_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("graph_version", sa.Integer()),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        _jsonb("data"),
    )

    op.create_table(
        "documents",
        sa.Column("document_id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text()),
        sa.Column("artifact_id", sa.Text()),
        sa.Column("artifact_version", sa.Integer()),
        sa.Column("status", sa.Text(), nullable=False, server_default="uploaded"),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        _jsonb("data"),
    )
    op.create_index("ix_documents_project", "documents", ["project_id"])

    op.create_table(
        "tasks",
        sa.Column("task_id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("capability", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("parent_task_id", sa.Text()),
        sa.Column("plan_task_id", sa.Text()),
        sa.Column("active_execution_id", sa.Text()),
        sa.Column("priority", sa.Text(), nullable=False),
        sa.Column("retry_at", TS),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        _jsonb("data"),
    )
    op.create_index("ix_tasks_project", "tasks", ["project_id", "created_at"])
    op.create_index("ix_tasks_state", "tasks", ["state"])

    op.create_table(
        "executions",
        sa.Column("execution_id", sa.Text(), primary_key=True),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("agent_id", sa.Text()),
        sa.Column("lease_until", TS),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        _jsonb("data"),
        sa.UniqueConstraint("task_id", "attempt", name="uq_executions_task_attempt"),
        sa.CheckConstraint("attempt >= 1", name="ck_executions_attempt_positive"),
    )
    op.create_index("ix_executions_status", "executions", ["status"])
    op.create_index("ix_executions_agent", "executions", ["agent_id"])

    op.create_table(
        "approvals",
        sa.Column("approval_id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("graph_version", sa.Integer()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("requested_at", TS, nullable=False),
        sa.Column("decided_at", TS),
        _jsonb("data"),
    )
    op.create_index("ix_approvals_project", "approvals", ["project_id"])

    # message log (commands the Manager sent; later: every envelope seen) — research §34
    op.create_table(
        "messages",
        sa.Column("message_id", sa.Text(), primary_key=True),
        sa.Column("message_type", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text()),
        sa.Column("execution_id", sa.Text()),
        sa.Column("project_id", sa.Text()),
        sa.Column("correlation_id", sa.Text()),
        sa.Column("sender", sa.Text()),
        sa.Column("receiver", sa.Text()),
        sa.Column("body_sha256", sa.String(64), nullable=False),
        sa.Column("occurred_at", TS, nullable=False),
        sa.Column("recorded_at", TS, nullable=False, server_default=NOW),
        _jsonb("body"),
    )
    op.create_index("ix_messages_task", "messages", ["task_id"])

    op.create_table(
        "inbox",
        sa.Column("consumer_id", sa.Text(), nullable=False),
        sa.Column("message_id", sa.Text(), nullable=False),
        sa.Column("processed_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("consumer_id", "message_id", name="pk_inbox"),
    )

    op.create_table(
        "outbox",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("capability", sa.Text()),
        sa.Column("message_id", sa.Text(), nullable=False),   # event_id (events) or message_id (commands)
        sa.Column("aggregate_id", sa.Text()),
        sa.Column("body", pg.JSONB(), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("published_at", TS),
        sa.CheckConstraint("kind IN ('event', 'command')", name="ck_outbox_kind"),
        sa.CheckConstraint("kind <> 'command' OR capability IS NOT NULL", name="ck_outbox_command_capability"),
    )
    op.create_index("ix_outbox_unpublished", "outbox", ["seq"], postgresql_where=sa.text("published_at IS NULL"))

    op.create_table(
        "events",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("event_id", sa.Text(), nullable=False, unique=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", sa.Text(), nullable=False),
        sa.Column("aggregate_version", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Text()),
        sa.Column("correlation_id", sa.Text()),
        sa.Column("occurred_at", TS, nullable=False),
        sa.Column("recorded_at", TS, nullable=False, server_default=NOW),
        _jsonb("body"),
    )
    op.create_index("ix_events_aggregate", "events", ["aggregate_id", "aggregate_version"])
    op.create_index("ix_events_project", "events", ["project_id", "seq"])
    op.execute("""
        CREATE FUNCTION hmap_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'events is append-only (% rejected)', TG_OP USING ERRCODE = 'restrict_violation';
        END $$
    """)
    op.execute("""
        CREATE TRIGGER events_append_only BEFORE UPDATE OR DELETE ON events
        FOR EACH ROW EXECUTE FUNCTION hmap_events_append_only()
    """)

    # registry projection (research §19-21): advisory for scheduling, rebuilt from registrations/heartbeats
    op.create_table(
        "agents",
        sa.Column("agent_id", sa.Text(), primary_key=True),
        sa.Column("plugin", sa.Text()),
        sa.Column("instance_id", sa.Text()),
        sa.Column("capabilities", pg.ARRAY(sa.Text()), nullable=False),
        sa.Column("protocol_version", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("max_slots", sa.Integer(), nullable=False),
        sa.Column("available_slots", sa.Integer(), nullable=False),
        sa.Column("current_execution_ids", pg.ARRAY(sa.Text()), nullable=False),
        sa.Column("lease_until", TS, nullable=False),
        sa.Column("last_heartbeat", TS, nullable=False),
        sa.Column("is_stub", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("registered_at", TS, nullable=False, server_default=NOW),
    )
    op.create_index("ix_agents_capabilities", "agents", ["capabilities"], postgresql_using="gin")
    op.create_index("ix_agents_lease", "agents", ["lease_until"])

    op.create_table(
        "contexts",
        sa.Column("context_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_version", sa.Integer()),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("content", pg.JSONB(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("uri", sa.Text()),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("context_id", "version", name="pk_contexts"),
        sa.CheckConstraint("version >= 1", name="ck_contexts_version_positive"),
    )
    op.create_index("ix_contexts_project", "contexts", ["project_id"])

    op.create_table(
        "artifacts",
        sa.Column("artifact_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),   # = ArtifactRef.access_scope
        sa.Column("artifact_type", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("supersedes", sa.Integer()),
        sa.PrimaryKeyConstraint("artifact_id", "version", name="pk_artifacts"),
        sa.CheckConstraint("version >= 1", name="ck_artifacts_version_positive"),
    )
    op.create_index("ix_artifacts_project", "artifacts", ["project_id", "created_at"])

    op.create_table(
        "errors",
        sa.Column("error_id", sa.Text(), primary_key=True),
        sa.Column("execution_id", sa.Text()),
        sa.Column("task_id", sa.Text()),
        sa.Column("project_id", sa.Text()),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("details_ref", sa.Text()),
        sa.Column("occurred_at", TS, nullable=False, server_default=NOW),
        _jsonb("details"),
    )
    op.create_index("ix_errors_execution", "errors", ["execution_id"])


def downgrade() -> None:
    for table in ("errors", "artifacts", "contexts", "agents"):
        op.drop_table(table)
    op.execute("DROP TRIGGER IF EXISTS events_append_only ON events")
    op.execute("DROP FUNCTION IF EXISTS hmap_events_append_only()")
    for table in ("events", "outbox", "inbox", "messages", "approvals", "executions", "tasks", "documents",
                  "projects"):
        op.drop_table(table)
