"""Account store behaviour (in-memory here; re-run against Postgres in tests/db/test_pg_accounts.py)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from hmap.services.accounts.base import EmailTaken, PasswordReset, Session, User
from hmap.services.accounts.memory import InMemoryAccountStore

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def _user(email: str | None = None) -> User:
    return User(user_id=f"U-{uuid.uuid4().hex}", email=email or f"{uuid.uuid4().hex}@example.test", name="Ada",
                password_hash="scrypt$x", created_at=NOW, updated_at=NOW)


def _session(user: User, h: str | None = None) -> Session:
    return Session(session_hash=h or uuid.uuid4().hex * 2, user_id=user.user_id, created_at=NOW,
                   expires_at=NOW + timedelta(days=1), last_seen_at=NOW)


@pytest.fixture
def store() -> InMemoryAccountStore:
    return InMemoryAccountStore()


async def test_users_unique_by_email(store) -> None:
    u = await store.create_user(_user())
    assert (await store.get_user_by_email(u.email)).user_id == u.user_id
    assert (await store.get_user(u.user_id)).email == u.email
    with pytest.raises(EmailTaken):
        await store.create_user(_user(u.email))
    renamed = await store.update_user(u.model_copy(update={"name": "Ada L.", "password_hash": "scrypt$y"}))
    got = await store.get_user(u.user_id)
    assert got.name == renamed.name == "Ada L." and got.password_hash == "scrypt$y"
    assert await store.get_user("U-missing") is None and await store.get_user_by_email("no@example.test") is None


async def test_sessions_touch_and_delete(store) -> None:
    u = await store.create_user(_user())
    s1, s2 = _session(u), _session(u)
    await store.create_session(s1)
    await store.create_session(s2)
    later = NOW + timedelta(hours=1)
    await store.touch_session(s1.session_hash, later, later + timedelta(days=1))
    assert (await store.get_session(s1.session_hash)).last_seen_at == later
    assert await store.delete_user_sessions(u.user_id, except_hash=s1.session_hash) == 1
    assert await store.get_session(s2.session_hash) is None and await store.get_session(s1.session_hash)
    await store.delete_session(s1.session_hash)
    assert await store.get_session(s1.session_hash) is None


async def test_reset_tokens_are_single_use_and_expire(store) -> None:
    u = await store.create_user(_user())
    good = PasswordReset(token_hash=uuid.uuid4().hex * 2, user_id=u.user_id, created_at=NOW,
                         expires_at=NOW + timedelta(minutes=30))
    old = PasswordReset(token_hash=uuid.uuid4().hex * 2, user_id=u.user_id, created_at=NOW,
                        expires_at=NOW - timedelta(seconds=1))
    await store.create_reset(good)
    await store.create_reset(old)
    used = await store.use_reset(good.token_hash, NOW)
    assert used is not None and used.user_id == u.user_id and used.used_at == NOW
    assert await store.use_reset(good.token_hash, NOW) is None          # second use
    assert await store.use_reset(old.token_hash, NOW) is None           # expired
    assert await store.use_reset("0" * 64, NOW) is None                 # unknown
