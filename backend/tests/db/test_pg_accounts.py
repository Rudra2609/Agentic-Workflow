"""Accounts and project ownership in PostgreSQL (migration 001b)."""

import pytest

from hmap.db import Database
from hmap.manager.pg_store import PostgresTaskStore
from hmap.manager.records import ProjectRecord
from hmap.services.accounts.pg import PostgresAccountStore
from tests.services.accounts.test_account_store import (  # noqa: F401  (re-collected against the Postgres store)
    NOW,
    test_reset_tokens_are_single_use_and_expire,
    test_sessions_touch_and_delete,
    test_users_unique_by_email,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def store(db: Database) -> PostgresAccountStore:
    return PostgresAccountStore(db)


async def test_project_owner_is_a_column_and_filters_listing(db: Database) -> None:
    tasks = PostgresTaskStore(db)
    async with tasks.transaction() as tx:
        for pid, owner in (("P-own-a", "U-a"), ("P-own-b", "U-b")):
            await tx.insert_project(ProjectRecord(project_id=pid, name=pid, owner_id=owner, created_at=NOW,
                                                  updated_at=NOW))
    mine = await tasks.list_projects(owner_id="U-a")
    assert [p.project_id for p in mine] == ["P-own-a"] and mine[0].owner_id == "U-a"
    rows = await db.fetch("SELECT owner_id FROM projects WHERE project_id = %s", ("P-own-b",))
    assert rows[0]["owner_id"] == "U-b"


async def test_passwords_and_tokens_are_never_stored_in_clear(db: Database) -> None:
    from hmap.services.accounts.memory import InMemoryAccountStore  # noqa: F401  (same service, Postgres store)
    from hmap.services.accounts.service import AccountService
    from tests.api.helpers import CapturingMailer

    mailer = CapturingMailer()
    svc = AccountService(PostgresAccountStore(db), mailer)
    _, token = await svc.register(name="Grace", email="grace.pg@example.test", password="a long secret phrase",
                                  client="t")
    await svc.request_reset(email="grace.pg@example.test", client="t")
    reset_token = mailer.reset_token("grace.pg@example.test")
    dump = str(await db.fetch("SELECT * FROM users")) + str(await db.fetch("SELECT * FROM sessions")) + \
        str(await db.fetch("SELECT * FROM password_resets"))
    assert "a long secret phrase" not in dump and token not in dump and reset_token not in dump
