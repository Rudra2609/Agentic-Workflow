"""SQLAlchemy Core table models of the Sprint 1 schema (mirrors ``alembic/versions/001_sprint_1_core.py``).

The migration is the source of truth for the database; this ``metadata`` is the in-code description used by
Alembic autogenerate (``target_metadata``) and checked against the migrated database by
``tests/db/test_migrations.py``. Change both together (and add a new revision, never edit 001 after release).

The ``pg_*`` stores issue plain SQL through psycopg (see ``hmap.db.database``); table/column names here are the
contract they rely on.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

# pg_advisory_xact_lock keys (bigint). Fixed values so every process agrees.
MIGRATION_LOCK_KEY = 0x686D_6170_0001        # "hmap" + 1: serialises concurrent migrate-on-start
OUTBOX_LOCK_KEY = 0x686D_6170_0002           # "hmap" + 2: outbox seq order == commit order (see pg_stores)

metadata = sa.MetaData()

TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")
EMPTY_JSON = sa.text("'{}'::jsonb")

projects = sa.Table(
    "projects", metadata,
    sa.Column("project_id", sa.Text(), primary_key=True),
    sa.Column("name", sa.Text(), nullable=False),
    sa.Column("state", sa.Text(), nullable=False),
    sa.Column("state_version", sa.Integer(), nullable=False),
    sa.Column("graph_version", sa.Integer()),
    sa.Column("created_at", TS, nullable=False),
    sa.Column("updated_at", TS, nullable=False),
    sa.Column("data", pg.JSONB(), nullable=False, server_default=EMPTY_JSON),
    sa.Column("owner_id", sa.Text()),                      # 001b
    sa.Index("ix_projects_owner", "owner_id", "created_at"),
)

documents = sa.Table(
    "documents", metadata,
    sa.Column("document_id", sa.Text(), primary_key=True),
    sa.Column("project_id", sa.Text(), nullable=False),
    sa.Column("filename", sa.Text(), nullable=False),
    sa.Column("media_type", sa.Text()),
    sa.Column("artifact_id", sa.Text()),
    sa.Column("artifact_version", sa.Integer()),
    sa.Column("status", sa.Text(), nullable=False, server_default="uploaded"),
    sa.Column("created_at", TS, nullable=False, server_default=NOW),
    sa.Column("data", pg.JSONB(), nullable=False, server_default=EMPTY_JSON),
    sa.Index("ix_documents_project", "project_id"),
)

tasks = sa.Table(
    "tasks", metadata,
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
    sa.Column("data", pg.JSONB(), nullable=False, server_default=EMPTY_JSON),
    sa.Index("ix_tasks_project", "project_id", "created_at"),
    sa.Index("ix_tasks_state", "state"),
)

executions = sa.Table(
    "executions", metadata,
    sa.Column("execution_id", sa.Text(), primary_key=True),
    sa.Column("task_id", sa.Text(), nullable=False),
    sa.Column("attempt", sa.Integer(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("agent_id", sa.Text()),
    sa.Column("lease_until", TS),
    sa.Column("created_at", TS, nullable=False),
    sa.Column("updated_at", TS, nullable=False),
    sa.Column("data", pg.JSONB(), nullable=False, server_default=EMPTY_JSON),
    sa.UniqueConstraint("task_id", "attempt", name="uq_executions_task_attempt"),
    sa.CheckConstraint("attempt >= 1", name="ck_executions_attempt_positive"),
    sa.Index("ix_executions_status", "status"),
    sa.Index("ix_executions_agent", "agent_id"),
)

approvals = sa.Table(
    "approvals", metadata,
    sa.Column("approval_id", sa.Text(), primary_key=True),
    sa.Column("project_id", sa.Text(), nullable=False),
    sa.Column("graph_version", sa.Integer()),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("requested_at", TS, nullable=False),
    sa.Column("decided_at", TS),
    sa.Column("data", pg.JSONB(), nullable=False, server_default=EMPTY_JSON),
    sa.Index("ix_approvals_project", "project_id"),
)

messages = sa.Table(
    "messages", metadata,
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
    sa.Column("body", pg.JSONB(), nullable=False, server_default=EMPTY_JSON),
    sa.Index("ix_messages_task", "task_id"),
)

inbox = sa.Table(
    "inbox", metadata,
    sa.Column("consumer_id", sa.Text(), nullable=False),
    sa.Column("message_id", sa.Text(), nullable=False),
    sa.Column("processed_at", TS, nullable=False, server_default=NOW),
    sa.PrimaryKeyConstraint("consumer_id", "message_id", name="pk_inbox"),
)

outbox = sa.Table(
    "outbox", metadata,
    sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
    sa.Column("kind", sa.Text(), nullable=False),
    sa.Column("capability", sa.Text()),
    sa.Column("message_id", sa.Text(), nullable=False),
    sa.Column("aggregate_id", sa.Text()),
    sa.Column("body", pg.JSONB(), nullable=False),
    sa.Column("created_at", TS, nullable=False, server_default=NOW),
    sa.Column("published_at", TS),
    sa.CheckConstraint("kind IN ('event', 'command')", name="ck_outbox_kind"),
    sa.CheckConstraint("kind <> 'command' OR capability IS NOT NULL", name="ck_outbox_command_capability"),
    sa.Index("ix_outbox_unpublished", "seq", postgresql_where=sa.text("published_at IS NULL")),
)

events = sa.Table(
    "events", metadata,
    sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
    sa.Column("event_id", sa.Text(), nullable=False, unique=True),
    sa.Column("event_type", sa.Text(), nullable=False),
    sa.Column("aggregate_id", sa.Text(), nullable=False),
    sa.Column("aggregate_version", sa.Integer(), nullable=False),
    sa.Column("project_id", sa.Text()),
    sa.Column("correlation_id", sa.Text()),
    sa.Column("occurred_at", TS, nullable=False),
    sa.Column("recorded_at", TS, nullable=False, server_default=NOW),
    sa.Column("body", pg.JSONB(), nullable=False, server_default=EMPTY_JSON),
    sa.Index("ix_events_aggregate", "aggregate_id", "aggregate_version"),
    sa.Index("ix_events_project", "project_id", "seq"),
)

agents = sa.Table(
    "agents", metadata,
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
    sa.Index("ix_agents_capabilities", "capabilities", postgresql_using="gin"),
    sa.Index("ix_agents_lease", "lease_until"),
)

contexts = sa.Table(
    "contexts", metadata,
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
    sa.Index("ix_contexts_project", "project_id"),
)

artifacts = sa.Table(
    "artifacts", metadata,
    sa.Column("artifact_id", sa.Text(), nullable=False),
    sa.Column("version", sa.Integer(), nullable=False),
    sa.Column("project_id", sa.Text(), nullable=False),
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
    sa.Index("ix_artifacts_project", "project_id", "created_at"),
)

errors = sa.Table(
    "errors", metadata,
    sa.Column("error_id", sa.Text(), primary_key=True),
    sa.Column("execution_id", sa.Text()),
    sa.Column("task_id", sa.Text()),
    sa.Column("project_id", sa.Text()),
    sa.Column("code", sa.Text(), nullable=False),
    sa.Column("retryable", sa.Boolean(), nullable=False),
    sa.Column("message", sa.Text(), nullable=False, server_default=""),
    sa.Column("details_ref", sa.Text()),
    sa.Column("occurred_at", TS, nullable=False, server_default=NOW),
    sa.Column("details", pg.JSONB(), nullable=False, server_default=EMPTY_JSON),
    sa.Index("ix_errors_execution", "execution_id"),
)

# ------------------------------------------------------------------ accounts (migration 001b)

users = sa.Table(
    "users", metadata,
    sa.Column("user_id", sa.Text(), primary_key=True),
    sa.Column("email", sa.Text(), nullable=False),
    sa.Column("name", sa.Text(), nullable=False),
    sa.Column("password_hash", sa.Text(), nullable=False),
    sa.Column("created_at", TS, nullable=False),
    sa.Column("updated_at", TS, nullable=False),
    sa.Index("ux_users_email", "email", unique=True),
)

sessions = sa.Table(
    "sessions", metadata,
    sa.Column("session_hash", sa.String(64), primary_key=True),
    sa.Column("user_id", sa.Text(), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
    sa.Column("created_at", TS, nullable=False),
    sa.Column("expires_at", TS, nullable=False),
    sa.Column("last_seen_at", TS, nullable=False),
    sa.Column("user_agent", sa.Text(), nullable=False, server_default=""),
    sa.Index("ix_sessions_user", "user_id"),
)

password_resets = sa.Table(
    "password_resets", metadata,
    sa.Column("token_hash", sa.String(64), primary_key=True),
    sa.Column("user_id", sa.Text(), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
    sa.Column("created_at", TS, nullable=False),
    sa.Column("expires_at", TS, nullable=False),
    sa.Column("used_at", TS),
)

ALL_TABLES: tuple[str, ...] = tuple(metadata.tables)

# Tables that members' own migrations add (no SQLAlchemy model here: the member's plug-in owns the SQL). The
# migration test expects exactly ALL_TABLES + these, and ignores them when comparing the models with the schema.
MEMBER_TABLES: dict[str, str] = {
    "research_chunks": "Member 5, migration 005 (hmap.agents.research.index)",
    "security_audit": "Member 6, migration 006 (hmap.core.policy.PgAudit)",
}
