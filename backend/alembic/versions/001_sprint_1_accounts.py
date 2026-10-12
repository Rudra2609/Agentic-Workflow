"""Sprint 1 accounts: users, sessions, password resets, and project ownership.

``projects.owner_id`` is the authoritative owner (the API checks it on every project-scoped request). Existing rows
keep ``NULL`` and are visible to nobody through the API (they predate accounts). Sessions and reset tokens store only
SHA-256 hashes of the secrets. Emails are stored normalised (lower-case), unique.

Next migration (Sprint 2) revises "001b".

Revision ID: 001b
Revises: 001
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "001b"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id", sa.Text(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_index("ux_users_email", "users", ["email"], unique=True)
    op.create_table(
        "sessions",
        sa.Column("session_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("last_seen_at", TS, nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index("ix_sessions_user", "sessions", ["user_id"])
    op.create_table(
        "password_resets",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("used_at", TS),
    )
    op.add_column("projects", sa.Column("owner_id", sa.Text()))
    op.create_index("ix_projects_owner", "projects", ["owner_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_projects_owner", table_name="projects")
    op.drop_column("projects", "owner_id")
    op.drop_table("password_resets")
    op.drop_index("ix_sessions_user", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ux_users_email", table_name="users")
    op.drop_table("users")
