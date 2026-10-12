"""User accounts, sessions and password-reset tokens: records + the store interface (memory and Postgres)."""

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str
    email: str                        # normalised (lower-case); unique
    name: str
    password_hash: str = Field(repr=False)
    created_at: datetime
    updated_at: datetime

    def public(self) -> dict[str, object]:
        """What the API may return about the signed-in user (never the hash)."""
        return {"user_id": self.user_id, "email": self.email, "name": self.name,
                "created_at": self.created_at.isoformat()}


class Session(BaseModel):
    session_hash: str = Field(repr=False)   # sha256 of the cookie token; the token itself is never stored
    user_id: str
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime
    user_agent: str = ""


class PasswordReset(BaseModel):
    token_hash: str = Field(repr=False)
    user_id: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None = None


class EmailTaken(ValueError):
    pass


class AccountStore(Protocol):
    async def create_user(self, user: User) -> User:
        """Raises :class:`EmailTaken` if the (normalised) email exists."""

    async def get_user(self, user_id: str) -> User | None: ...
    async def get_user_by_email(self, email: str) -> User | None: ...
    async def update_user(self, user: User) -> User: ...

    async def create_session(self, session: Session) -> None: ...
    async def get_session(self, session_hash: str) -> Session | None: ...
    async def touch_session(self, session_hash: str, last_seen_at: datetime, expires_at: datetime) -> None: ...
    async def delete_session(self, session_hash: str) -> None: ...
    async def delete_user_sessions(self, user_id: str, *, except_hash: str | None = None) -> int: ...

    async def create_reset(self, reset: PasswordReset) -> None: ...
    async def use_reset(self, token_hash: str, now: datetime) -> PasswordReset | None:
        """Atomically mark an unused, unexpired reset as used and return it; otherwise None (single use)."""
