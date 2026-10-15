"""Sprint 5 (Member 5): the research index — text chunks of fetched pages with embeddings (pgvector) and a keyword
index, namespaced by project (``hmap.agents.research.index.PgBackend``).

The ``vector`` extension is created in ``public`` (every connection's search_path ends with ``public``), so the type
is found from any schema, including the per-test schemas. The vector column is untyped: its dimension follows the
embedding model (768 for ``nomic-embed-text``); search is an exact cosine scan per project (see the module above).
Rows are deleted when their project is deleted (plug-in hook on ``project.deleted``).

Revision ID: 005
Revises: 001b
Create Date: 2026-10-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "005"
down_revision: str | None = "001b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
    op.execute("""
        CREATE TABLE research_chunks (
            project_id      text        NOT NULL,
            chunk_id        text        NOT NULL,
            url             text        NOT NULL,
            title           text        NOT NULL DEFAULT '',
            kind            text        NOT NULL DEFAULT 'web',
            content_sha256  text        NOT NULL,
            start_char      integer     NOT NULL,
            end_char        integer     NOT NULL,
            text            text        NOT NULL,
            embedding       vector,                     -- NULL: indexed without embeddings (keyword only)
            tsv             tsvector    GENERATED ALWAYS AS (to_tsvector('english', title || ' ' || text)) STORED,
            created_at      timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (project_id, chunk_id)
        )""")
    op.execute("CREATE INDEX ix_research_chunks_page ON research_chunks (project_id, url, content_sha256)")
    op.execute("CREATE INDEX ix_research_chunks_tsv ON research_chunks USING gin (tsv)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS research_chunks")
    # the extension stays: other schemas (or a later sprint) may use it
