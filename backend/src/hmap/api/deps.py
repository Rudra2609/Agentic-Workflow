"""FastAPI dependencies: the running system lives on ``app.state``; the signed-in user comes from the session cookie.

Authentication: ``hmap_session`` (HttpOnly, SameSite=Lax, Secure when ``HMAP_COOKIE_SECURE``) holds an opaque token;
:class:`AccountService` maps it to a user. The user id is never taken from the request body or URL.

CSRF: every state-changing request (POST/PUT/PATCH/DELETE) must echo the ``hmap_csrf`` cookie in the
``X-CSRF-Token`` header (double-submit). Another site can make the browser send cookies but cannot read ours, so it
cannot produce the header. SameSite cookies and the CORS allow-list are the second layer.
"""

import hmac
import ipaddress
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from hmap.api.feed import EventFeed
from hmap.manager.manager import Manager
from hmap.services.accounts.service import AccountService, SessionInfo
from hmap.system import HmapSystem

SESSION_COOKIE = "hmap_session"
CSRF_COOKIE = "hmap_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_system(request: Request) -> HmapSystem:
    system: HmapSystem = request.app.state.system
    return system


def get_manager(request: Request) -> Manager:
    return get_system(request).manager


def get_feed(request: Request) -> EventFeed:
    feed: EventFeed = request.app.state.feed
    return feed


def get_accounts(request: Request) -> AccountService:
    accounts: AccountService = request.app.state.accounts
    return accounts


def client_address(request: Request) -> str:
    """The caller's address for rate limiting. ``X-Forwarded-For`` is trusted only from a loopback peer (the
    Next.js dev/prod server proxying ``/api`` on the same machine)."""
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        try:
            if ipaddress.ip_address(peer).is_loopback:
                return forwarded.split(",")[0].strip()[:64]
        except ValueError:
            pass
    return peer


def check_csrf(request: Request) -> None:
    if request.method in SAFE_METHODS:
        return
    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get(CSRF_HEADER, "")
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Your session is out of date. Reload the page and "
                                                              "try again.")


async def current_session(request: Request) -> SessionInfo:
    info = await get_accounts(request).resolve(request.cookies.get(SESSION_COOKIE))
    if info is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Sign in to continue.")
    check_csrf(request)
    request.state.user_id = info.user.user_id
    return info


CurrentSession = Annotated[SessionInfo, Depends(current_session)]
