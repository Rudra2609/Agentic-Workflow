"""Postgres persistence (Sprint 1 item 1.5): connection pool, schema (``tables``) and migrations (``migrate``).

Composition root::

    from hmap.db import Database, upgrade_async
    await upgrade_async(settings.database_url)          # migrate on start (idempotent, advisory-locked)
    db = Database(settings.database_url)                # one per process / event loop
    store = PostgresTaskStore(db); outbox = PostgresOutboxStore(db); ...
    ...
    await db.close()                                    # on shutdown
"""

from hmap.db.database import DEFAULT_DATABASE_URL, Database, PoolTimeout, conninfo, database_url
from hmap.db.migrate import current_revision, downgrade, downgrade_async, upgrade, upgrade_async

__all__ = [
    "DEFAULT_DATABASE_URL", "Database", "PoolTimeout", "conninfo", "current_revision", "database_url", "downgrade",
    "downgrade_async", "upgrade", "upgrade_async",
]
