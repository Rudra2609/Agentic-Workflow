"""Account use cases: register, sign in/out, sessions, profile, password change and reset, WebSocket tickets.

Security notes (see HANDOFF.md "Accounts"):
- Errors never reveal whether an email has an account (login, reset); a login for an unknown email still runs one
  scrypt so timing matches a wrong password.
- Sessions: random token in an HttpOnly cookie, only its SHA-256 is stored; sliding expiry (``session_days``),
  invalidated on sign-out, on password change (other sessions) and on password reset (all sessions).
- Reset tokens: random, single use, 30-minute lifetime, only the hash is stored.
- WebSocket tickets: random, single use, 60 s, kept in process memory.
"""

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from hmap.core.ids import new_ulid
from hmap.services.accounts.base import AccountStore, EmailTaken, PasswordReset, Session, User
from hmap.services.accounts.mailer import Mailer
from hmap.services.accounts.ratelimit import RateLimiter
from hmap.services.accounts.security import (
    DUMMY_HASH,
    hash_password,
    needs_rehash,
    new_token,
    normalize_email,
    password_problem,
    token_hash,
    valid_email,
    verify_password,
)

RESET_TTL = timedelta(minutes=30)
TICKET_TTL_S = 60.0


class AccountError(ValueError):
    """A user-facing problem; ``field`` names the form field it belongs to (or None)."""

    def __init__(self, message: str, *, field: str | None = None, status: int = 400) -> None:
        super().__init__(message)
        self.message, self.field, self.status = message, field, status


class RateLimited(AccountError):
    def __init__(self, retry_after: int) -> None:
        super().__init__("Too many attempts. Please wait a moment and try again.", status=429)
        self.retry_after = retry_after


@dataclass
class SessionInfo:
    user: User
    session: Session


class AccountService:
    def __init__(self, store: AccountStore, mailer: Mailer, *, public_url: str = "http://localhost:3000",
                 session_days: float = 14.0, allow_registration: bool = True) -> None:
        self.store = store
        self.mailer = mailer
        self.public_url = public_url.rstrip("/")
        self.session_ttl = timedelta(days=session_days)
        self.allow_registration = allow_registration
        self.login_limiter = RateLimiter(10, 300)        # per email and per client: 10 tries / 5 minutes
        self.register_limiter = RateLimiter(10, 3600)    # per client
        self.reset_limiter = RateLimiter(5, 3600)        # per email and per client
        self._tickets: dict[str, tuple[str, float]] = {}

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    def _check(self, limiter: RateLimiter, *keys: str) -> None:
        blocked = [k for k in keys if not limiter.allow(k)]
        if blocked:
            raise RateLimited(max(limiter.retry_after(k) for k in blocked))

    # ------------------------------------------------------------------ registration and sign-in

    async def register(self, *, name: str, email: str, password: str, client: str,
                       user_agent: str = "") -> tuple[SessionInfo, str]:
        if not self.allow_registration:
            raise AccountError("New accounts are disabled on this server.", status=403)
        self._check(self.register_limiter, f"ip:{client}")
        name, email = name.strip(), normalize_email(email)
        if not name:
            raise AccountError("Enter your name.", field="name")
        if len(name) > 100:
            raise AccountError("Use at most 100 characters.", field="name")
        if not valid_email(email):
            raise AccountError("Enter a valid email address.", field="email")
        problem = password_problem(password, email=email, name=name)
        if problem:
            raise AccountError(problem, field="password")
        now = self._now()
        user = User(user_id=f"U-{new_ulid()}", email=email, name=name, password_hash=hash_password(password),
                    created_at=now, updated_at=now)
        try:
            await self.store.create_user(user)
        except EmailTaken:
            # Registration has to say this for the form to be usable; rate limiting bounds enumeration.
            raise AccountError("An account with this email already exists. Sign in instead.",
                               field="email", status=409) from None
        return await self._open_session(user, user_agent)

    async def login(self, *, email: str, password: str, client: str,
                    user_agent: str = "") -> tuple[SessionInfo, str]:
        email = normalize_email(email)
        self._check(self.login_limiter, f"email:{email}", f"ip:{client}")
        user = await self.store.get_user_by_email(email) if valid_email(email) else None
        ok = verify_password(password, user.password_hash if user else DUMMY_HASH)
        if user is None or not ok:
            raise AccountError("Email or password is incorrect.", status=401)
        self.login_limiter.reset(f"email:{email}")
        if needs_rehash(user.password_hash):
            user = await self.store.update_user(user.model_copy(update={
                "password_hash": hash_password(password), "updated_at": self._now()}))
        return await self._open_session(user, user_agent)

    async def _open_session(self, user: User, user_agent: str) -> tuple[SessionInfo, str]:
        token, now = new_token(), self._now()
        session = Session(session_hash=token_hash(token), user_id=user.user_id, created_at=now,
                          expires_at=now + self.session_ttl, last_seen_at=now, user_agent=user_agent[:200])
        await self.store.create_session(session)
        return SessionInfo(user, session), token

    async def resolve(self, token: str | None) -> SessionInfo | None:
        """The signed-in user for a session cookie, or None (unknown/expired). Extends the session (sliding)."""
        if not token or len(token) > 200:
            return None
        h = token_hash(token)
        session = await self.store.get_session(h)
        now = self._now()
        if session is None:
            return None
        if session.expires_at <= now:
            await self.store.delete_session(h)
            return None
        user = await self.store.get_user(session.user_id)
        if user is None:
            await self.store.delete_session(h)
            return None
        if now - session.last_seen_at > timedelta(minutes=5):      # write at most every 5 minutes
            session = session.model_copy(update={"last_seen_at": now, "expires_at": now + self.session_ttl})
            await self.store.touch_session(h, session.last_seen_at, session.expires_at)
        return SessionInfo(user, session)

    async def logout(self, token: str | None) -> None:
        if token:
            await self.store.delete_session(token_hash(token))

    async def logout_everywhere(self, info: SessionInfo) -> int:
        return await self.store.delete_user_sessions(info.user.user_id)

    # ------------------------------------------------------------------ profile and password

    async def update_profile(self, info: SessionInfo, *, name: str) -> User:
        name = name.strip()
        if not name or len(name) > 100:
            raise AccountError("Enter a name of 1 to 100 characters.", field="name")
        return await self.store.update_user(info.user.model_copy(update={"name": name, "updated_at": self._now()}))

    async def change_password(self, info: SessionInfo, *, current: str, new: str) -> int:
        if not verify_password(current, info.user.password_hash):
            raise AccountError("Your current password is incorrect.", field="current_password")
        problem = password_problem(new, email=info.user.email, name=info.user.name)
        if problem:
            raise AccountError(problem, field="new_password")
        await self.store.update_user(info.user.model_copy(update={
            "password_hash": hash_password(new), "updated_at": self._now()}))
        return await self.store.delete_user_sessions(info.user.user_id, except_hash=info.session.session_hash)

    async def request_reset(self, *, email: str, client: str) -> None:
        """Always succeeds from the caller's view (no account enumeration); sends mail only for real accounts."""
        email = normalize_email(email)
        self._check(self.reset_limiter, f"email:{email}", f"ip:{client}")
        user = await self.store.get_user_by_email(email) if valid_email(email) else None
        if user is None:
            return
        token, now = new_token(), self._now()
        await self.store.create_reset(PasswordReset(token_hash=token_hash(token), user_id=user.user_id,
                                                    created_at=now, expires_at=now + RESET_TTL))
        # The token travels in the URL fragment (#), which browsers never send to servers or in Referer headers.
        link = f"{self.public_url}/reset-password#token={token}"
        await self.mailer.send(user.email, "Reset your HMAP password",
                               f"Hi {user.name},\n\nSomeone (hopefully you) asked to reset your HMAP password.\n"
                               f"Open this link within 30 minutes to choose a new one:\n\n{link}\n\n"
                               "If you didn't ask for this, you can ignore this email; your password is unchanged.\n")

    async def reset_password(self, *, token: str, new: str) -> None:
        if not token or len(token) > 200:
            raise AccountError("This reset link is invalid or has expired.", status=400)
        problem = password_problem(new)                  # checked before the single-use token is spent
        if problem:
            raise AccountError(problem, field="password")
        reset = await self.store.use_reset(token_hash(token), self._now())
        user = await self.store.get_user(reset.user_id) if reset else None
        if reset is None or user is None:
            raise AccountError("This reset link is invalid or has expired.", status=400)
        await self.store.update_user(user.model_copy(update={"password_hash": hash_password(new),
                                                             "updated_at": self._now()}))
        await self.store.delete_user_sessions(user.user_id)

    # ------------------------------------------------------------------ WebSocket tickets

    def issue_ticket(self, info: SessionInfo) -> str:
        now = time.monotonic()
        for t in [t for t, (_, exp) in self._tickets.items() if exp <= now]:
            del self._tickets[t]
        ticket = new_token()
        self._tickets[ticket] = (info.user.user_id, now + TICKET_TTL_S)
        return ticket

    def redeem_ticket(self, ticket: str | None) -> str | None:
        """The user id for a valid, unexpired ticket (single use), else None."""
        if not ticket:
            return None
        entry = self._tickets.pop(ticket, None)
        if entry is None or entry[1] <= time.monotonic():
            return None
        return entry[0]
