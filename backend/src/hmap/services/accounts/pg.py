"""Account store in PostgreSQL (tables ``users``, ``sessions``, ``password_resets`` — migration ``001b``).

All statements are parameterised. Emails are stored normalised and are unique (``ux_users_email``).
"""

from datetime import datetime
from typing import Any

from psycopg import errors as pg_errors

from hmap.db.database import Database
from hmap.services.accounts.base import EmailTaken, PasswordReset, Session, User

_USER_COLS = "user_id, email, name, password_hash, created_at, updated_at"
_SESSION_COLS = "session_hash, user_id, created_at, expires_at, last_seen_at, user_agent"
_RESET_COLS = "token_hash, user_id, created_at, expires_at, used_at"


def _user(row: dict[str, Any]) -> User:
    return User.model_validate(dict(row))


class PostgresAccountStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create_user(self, user: User) -> User:
        try:
            await self.db.fetch(
                f"INSERT INTO users ({_USER_COLS}) VALUES (%s, %s, %s, %s, %s, %s) RETURNING user_id",
                (user.user_id, user.email, user.name, user.password_hash, user.created_at, user.updated_at))
        except pg_errors.UniqueViolation as exc:
            raise EmailTaken(user.email) from exc
        return user

    async def get_user(self, user_id: str) -> User | None:
        rows = await self.db.fetch(f"SELECT {_USER_COLS} FROM users WHERE user_id = %s", (user_id,))
        return _user(rows[0]) if rows else None

    async def get_user_by_email(self, email: str) -> User | None:
        rows = await self.db.fetch(f"SELECT {_USER_COLS} FROM users WHERE email = %s", (email,))
        return _user(rows[0]) if rows else None

    async def update_user(self, user: User) -> User:
        await self.db.fetch(
            "UPDATE users SET name = %s, password_hash = %s, updated_at = %s WHERE user_id = %s RETURNING user_id",
            (user.name, user.password_hash, user.updated_at, user.user_id))
        return user

    async def create_session(self, session: Session) -> None:
        await self.db.fetch(
            f"INSERT INTO sessions ({_SESSION_COLS}) VALUES (%s, %s, %s, %s, %s, %s) RETURNING session_hash",
            (session.session_hash, session.user_id, session.created_at, session.expires_at, session.last_seen_at,
             session.user_agent))

    async def get_session(self, session_hash: str) -> Session | None:
        rows = await self.db.fetch(f"SELECT {_SESSION_COLS} FROM sessions WHERE session_hash = %s", (session_hash,))
        return Session.model_validate(dict(rows[0])) if rows else None

    async def touch_session(self, session_hash: str, last_seen_at: datetime, expires_at: datetime) -> None:
        await self.db.fetch("UPDATE sessions SET last_seen_at = %s, expires_at = %s WHERE session_hash = %s"
                            " RETURNING session_hash", (last_seen_at, expires_at, session_hash))

    async def delete_session(self, session_hash: str) -> None:
        await self.db.fetch("DELETE FROM sessions WHERE session_hash = %s RETURNING session_hash", (session_hash,))

    async def delete_user_sessions(self, user_id: str, *, except_hash: str | None = None) -> int:
        rows = await self.db.fetch(
            "DELETE FROM sessions WHERE user_id = %s AND session_hash IS DISTINCT FROM %s RETURNING session_hash",
            (user_id, except_hash))
        return len(rows)

    async def create_reset(self, reset: PasswordReset) -> None:
        await self.db.fetch(
            f"INSERT INTO password_resets ({_RESET_COLS}) VALUES (%s, %s, %s, %s, %s) RETURNING token_hash",
            (reset.token_hash, reset.user_id, reset.created_at, reset.expires_at, reset.used_at))

    async def use_reset(self, token_hash: str, now: datetime) -> PasswordReset | None:
        rows = await self.db.fetch(
            f"UPDATE password_resets SET used_at = %s WHERE token_hash = %s AND used_at IS NULL AND expires_at > %s"
            f" RETURNING {_RESET_COLS}", (now, token_hash, now))
        return PasswordReset.model_validate(dict(rows[0])) if rows else None
