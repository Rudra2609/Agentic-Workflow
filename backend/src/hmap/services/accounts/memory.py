"""In-memory account store (tests and ``HMAP_STORE=memory``; forgets everything on restart)."""

import asyncio
from datetime import datetime

from hmap.services.accounts.base import EmailTaken, PasswordReset, Session, User


class InMemoryAccountStore:
    def __init__(self) -> None:
        self._users: dict[str, User] = {}
        self._by_email: dict[str, str] = {}
        self._sessions: dict[str, Session] = {}
        self._resets: dict[str, PasswordReset] = {}
        self._lock = asyncio.Lock()

    async def create_user(self, user: User) -> User:
        async with self._lock:
            if user.email in self._by_email:
                raise EmailTaken(user.email)
            self._users[user.user_id] = user.model_copy()
            self._by_email[user.email] = user.user_id
        return user.model_copy()

    async def get_user(self, user_id: str) -> User | None:
        u = self._users.get(user_id)
        return u.model_copy() if u else None

    async def get_user_by_email(self, email: str) -> User | None:
        uid = self._by_email.get(email)
        return await self.get_user(uid) if uid else None

    async def update_user(self, user: User) -> User:
        async with self._lock:
            self._users[user.user_id] = user.model_copy()
        return user.model_copy()

    async def create_session(self, session: Session) -> None:
        self._sessions[session.session_hash] = session.model_copy()

    async def get_session(self, session_hash: str) -> Session | None:
        s = self._sessions.get(session_hash)
        return s.model_copy() if s else None

    async def touch_session(self, session_hash: str, last_seen_at: datetime, expires_at: datetime) -> None:
        s = self._sessions.get(session_hash)
        if s is not None:
            self._sessions[session_hash] = s.model_copy(update={"last_seen_at": last_seen_at,
                                                               "expires_at": expires_at})

    async def delete_session(self, session_hash: str) -> None:
        self._sessions.pop(session_hash, None)

    async def delete_user_sessions(self, user_id: str, *, except_hash: str | None = None) -> int:
        doomed = [h for h, s in self._sessions.items() if s.user_id == user_id and h != except_hash]
        for h in doomed:
            del self._sessions[h]
        return len(doomed)

    async def create_reset(self, reset: PasswordReset) -> None:
        self._resets[reset.token_hash] = reset.model_copy()

    async def use_reset(self, token_hash: str, now: datetime) -> PasswordReset | None:
        async with self._lock:
            r = self._resets.get(token_hash)
            if r is None or r.used_at is not None or r.expires_at <= now:
                return None
            used = r.model_copy(update={"used_at": now})
            self._resets[token_hash] = used
            return used
