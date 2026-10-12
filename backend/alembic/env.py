"""Alembic environment for hmap.

Database URL: ``config.attributes["url"]`` (programmatic, see ``hmap.db.migrate``) > ``-x url=...`` >
``$HMAP_DATABASE_URL`` > the dev default. Optional schema (tests): ``config.attributes["schema"]`` or
``-x schema=...``; the schema is created if missing, used as ``search_path`` and holds ``alembic_version``.

A caller may also hand over an open connection in ``config.attributes["connection"]``.

Sync on purpose: SQLAlchemy's asyncio extension needs ``greenlet``, which is not installed, and migrations are a
one-shot startup step anyway. Async code calls ``hmap.db.migrate.upgrade_async`` (runs this in a worker thread),
so it is safe to use from inside a running event loop.
"""

import logging
from logging.config import fileConfig

from sqlalchemy import Connection, create_engine, pool, text

from alembic import context
from hmap.db.database import check_schema_name, database_url, session_options
from hmap.db.tables import MIGRATION_LOCK_KEY, metadata

config = context.config
if config.config_file_name is not None and not config.attributes.get("skip_logging"):
    fileConfig(config.config_file_name, disable_existing_loggers=False)
log = logging.getLogger("alembic.env")

x_args = context.get_x_argument(as_dictionary=True)
URL: str = database_url(config.attributes.get("url") or x_args.get("url"))
_schema = config.attributes.get("schema") or x_args.get("schema")
SCHEMA: str | None = check_schema_name(_schema) if _schema else None


def _configure(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=metadata, version_table_schema=SCHEMA,
                      transaction_per_migration=False, compare_type=True)
    with context.begin_transaction():
        # two processes migrating on start at once: the second waits, then sees the new head and does nothing
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
        context.run_migrations()


def run_migrations_offline() -> None:
    """``alembic upgrade head --sql``: emit SQL without a database."""
    context.configure(url=URL, target_metadata=metadata, literal_binds=True, version_table_schema=SCHEMA,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        if SCHEMA:
            context.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')
            context.execute(f'SET search_path TO "{SCHEMA}", public')
        context.run_migrations()


def run_migrations_online() -> None:
    given: Connection | None = config.attributes.get("connection")
    if given is not None:
        _configure(given)
        return
    engine = create_engine(URL, poolclass=pool.NullPool, connect_args={"options": session_options(SCHEMA)})
    try:
        if SCHEMA:
            with engine.begin() as conn:
                conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))
        with engine.connect() as conn:
            _configure(conn)
            conn.commit()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
