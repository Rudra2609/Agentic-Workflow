"""Programmatic Alembic: migrate on start, and test helpers.

    from hmap.db.migrate import upgrade, upgrade_async
    upgrade()                                   # sync: alembic upgrade head on $HMAP_DATABASE_URL
    await upgrade_async(url, schema="t_1234")   # from async code (runs Alembic in a worker thread)

Alembic itself is synchronous (SQLAlchemy + psycopg sync driver); ``*_async`` wrappers keep the event loop free.
Concurrent callers are safe: ``alembic/env.py`` takes a transaction-scoped advisory lock around the upgrade.
"""

import asyncio
from pathlib import Path

from alembic.command import downgrade as alembic_downgrade
from alembic.command import upgrade as alembic_upgrade
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, pool

from hmap.db.database import check_schema_name, database_url, session_options

BACKEND_DIR = Path(__file__).resolve().parents[3]          # backend/ (src/hmap/db/migrate.py -> ../../..)
DEFAULT_SCRIPT_LOCATION = BACKEND_DIR / "alembic"


def alembic_config(url: str | None = None, *, schema: str | None = None,
                   script_location: str | Path | None = None) -> Config:
    location = Path(script_location) if script_location else DEFAULT_SCRIPT_LOCATION
    if not (location / "env.py").is_file():
        raise FileNotFoundError(f"alembic scripts not found at {location} (run from a source checkout)")
    ini = BACKEND_DIR / "alembic.ini"
    cfg = Config(str(ini)) if ini.is_file() and script_location is None else Config()
    cfg.set_main_option("script_location", str(location))
    cfg.attributes["url"] = database_url(url)
    cfg.attributes["skip_logging"] = True          # do not reconfigure the app's logging
    if schema:
        cfg.attributes["schema"] = check_schema_name(schema)
    return cfg


def upgrade(url: str | None = None, *, schema: str | None = None, revision: str = "head") -> None:
    """``alembic upgrade <revision>``. Blocking; from async code use :func:`upgrade_async`."""
    alembic_upgrade(alembic_config(url, schema=schema), revision)


def downgrade(url: str | None = None, *, schema: str | None = None, revision: str = "base") -> None:
    alembic_downgrade(alembic_config(url, schema=schema), revision)


def current_revision(url: str | None = None, *, schema: str | None = None) -> str | None:
    """The revision the database is at (``None`` = empty / never migrated)."""
    engine = create_engine(database_url(url), poolclass=pool.NullPool,
                           connect_args={"options": session_options(schema)})
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={"version_table_schema": schema})
            return ctx.get_current_revision()
    finally:
        engine.dispose()


async def upgrade_async(url: str | None = None, *, schema: str | None = None, revision: str = "head") -> None:
    await asyncio.to_thread(upgrade, url, schema=schema, revision=revision)


async def downgrade_async(url: str | None = None, *, schema: str | None = None, revision: str = "base") -> None:
    await asyncio.to_thread(downgrade, url, schema=schema, revision=revision)
