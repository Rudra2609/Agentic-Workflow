"""Sprint 6 (Member 6): the security audit log (``hmap.core.policy.PgAudit``) — one row per refused message (and per
agent registration): who sent what, which policy rule refused it and why. Append-only; read by the Verify tab's
security view and ``docs/members/6/security-report.md``. Verification results themselves are artifacts (no table).

Revision ID: 006
Revises: 005
Create Date: 2026-10-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE security_audit (
            id            bigserial   PRIMARY KEY,
            at            timestamptz NOT NULL DEFAULT now(),
            decision      text        NOT NULL,          -- allow | deny
            rule          text        NOT NULL,          -- auth | token | identity | assigned | table | size
            reason        text        NOT NULL DEFAULT '',
            sender        text        NOT NULL,
            message_type  text        NOT NULL,
            message_id    text        NOT NULL,
            task_id       text,
            execution_id  text,
            project_id    text,
            enforced      boolean     NOT NULL DEFAULT true
        )""")
    op.execute("CREATE INDEX ix_security_audit_at ON security_audit (at DESC)")
    op.execute("CREATE INDEX ix_security_audit_sender ON security_audit (sender, at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS security_audit")
