"""Test helpers: sign a TestClient in (cookies + CSRF header), capture account emails."""

import itertools
import re
from typing import Any

from fastapi.testclient import TestClient

PASSWORD = "correct horse battery staple"
_n = itertools.count(1)


def signed_in(client: TestClient, *, name: str = "Ada Lovelace", email: str | None = None,
              password: str = PASSWORD) -> dict[str, Any]:
    """Register a fresh user on ``client`` and keep its session; returns the user."""
    email = email or f"user{next(_n)}@example.test"
    r = client.post("/api/auth/register", json={"name": name, "email": email, "password": password})
    assert r.status_code == 201, r.text
    use_csrf(client)
    return r.json()["user"]


def use_csrf(client: TestClient) -> None:
    client.headers["X-CSRF-Token"] = client.cookies.get("hmap_csrf") or ""


class CapturingMailer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))

    def reset_token(self, to: str) -> str:
        body = next(b for t, _, b in reversed(self.sent) if t == to)
        match = re.search(r"#token=([A-Za-z0-9_-]+)", body)
        assert match, body
        return match.group(1)


def second_client(first: TestClient) -> TestClient:
    """Another browser (own cookies) on the SAME running app and event loop as ``first`` (which must be inside its
    ``with`` block). A plain ``TestClient(app)`` would run each request on a new event loop, which the in-memory bus
    and stores do not support."""
    other = TestClient(first.app)
    other.portal = first.portal
    return other
