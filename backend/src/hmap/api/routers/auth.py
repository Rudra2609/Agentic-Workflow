"""Accounts API: register, sign in/out, profile, password change, password reset, WebSocket tickets.

Cookies are set here (see ``hmap.api.deps`` for the CSRF scheme). Every error message is safe to show: no stack
traces, no hint whether an email exists (except on registration, which must say so to be usable and is rate
limited).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from hmap.api.deps import CSRF_COOKIE, SESSION_COOKIE, CurrentSession, check_csrf, client_address, get_accounts
from hmap.core.config import Settings
from hmap.services.accounts.security import MAX_PASSWORD_LENGTH, new_token
from hmap.services.accounts.service import AccountError, AccountService, RateLimited, SessionInfo

router = APIRouter(prefix="/auth", tags=["auth"])
AccountsDep = Annotated[AccountService, Depends(get_accounts)]


class RegisterIn(BaseModel):
    name: str = Field(max_length=100)
    email: str = Field(max_length=254)
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class ProfileIn(BaseModel):
    name: str = Field(max_length=100)


class PasswordIn(BaseModel):
    current_password: str = Field(max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class ForgotIn(BaseModel):
    email: str = Field(max_length=254)


class ResetIn(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _fail(exc: AccountError) -> HTTPException:
    headers = {"Retry-After": str(exc.retry_after)} if isinstance(exc, RateLimited) else None
    detail: Any = {"message": exc.message, "field": exc.field} if exc.field else exc.message
    return HTTPException(exc.status, detail=detail, headers=headers)


def _set_cookies(request: Request, response: Response, token: str) -> None:
    s = _settings(request)
    max_age = int(s.session_days * 86400)
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, samesite="lax", secure=s.cookie_secure,
                        path="/")
    response.set_cookie(CSRF_COOKIE, new_token(), max_age=max_age, httponly=False, samesite="strict",
                        secure=s.cookie_secure, path="/")


def _clear_cookies(request: Request, response: Response) -> None:
    secure = _settings(request).cookie_secure
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", secure=secure, samesite="lax")


def _me(info: SessionInfo) -> dict[str, Any]:
    return {"user": info.user.public(), "session_expires_at": info.session.expires_at.isoformat()}


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterIn, request: Request, response: Response, accounts: AccountsDep) -> dict[str, Any]:
    try:
        info, token = await accounts.register(name=body.name, email=body.email, password=body.password,
                                              client=client_address(request),
                                              user_agent=request.headers.get("user-agent", ""))
    except AccountError as exc:
        raise _fail(exc) from None
    _set_cookies(request, response, token)
    return _me(info)


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, accounts: AccountsDep) -> dict[str, Any]:
    try:
        info, token = await accounts.login(email=body.email, password=body.password, client=client_address(request),
                                           user_agent=request.headers.get("user-agent", ""))
    except AccountError as exc:
        raise _fail(exc) from None
    _set_cookies(request, response, token)
    return _me(info)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, accounts: AccountsDep) -> Response:
    """Ends this session. Works without a valid session (clears cookies either way); with one, CSRF is checked."""
    token = request.cookies.get(SESSION_COOKIE)
    if token and await accounts.resolve(token) is not None:
        check_csrf(request)
        await accounts.logout(token)
    out = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_cookies(request, out)
    return out


@router.post("/logout-all")
async def logout_all(info: CurrentSession, request: Request, accounts: AccountsDep) -> Response:
    await accounts.logout_everywhere(info)
    out = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_cookies(request, out)
    return out


@router.get("/me")
async def me(info: CurrentSession, request: Request, response: Response) -> dict[str, Any]:
    if not request.cookies.get(CSRF_COOKIE):          # e.g. cookie cleared: hand out a fresh CSRF token
        s = _settings(request)
        response.set_cookie(CSRF_COOKIE, new_token(), max_age=int(s.session_days * 86400), httponly=False,
                            samesite="strict", secure=s.cookie_secure, path="/")
    return _me(info)


@router.patch("/me")
async def update_me(body: ProfileIn, info: CurrentSession, accounts: AccountsDep) -> dict[str, Any]:
    try:
        user = await accounts.update_profile(info, name=body.name)
    except AccountError as exc:
        raise _fail(exc) from None
    return {"user": user.public()}


@router.post("/password")
async def change_password(body: PasswordIn, info: CurrentSession, accounts: AccountsDep) -> dict[str, Any]:
    try:
        ended = await accounts.change_password(info, current=body.current_password, new=body.new_password)
    except AccountError as exc:
        raise _fail(exc) from None
    return {"other_sessions_ended": ended}


@router.post("/forgot", status_code=status.HTTP_202_ACCEPTED)
async def forgot(body: ForgotIn, request: Request, accounts: AccountsDep) -> dict[str, str]:
    try:
        await accounts.request_reset(email=body.email, client=client_address(request))
    except RateLimited as exc:
        raise _fail(exc) from None
    return {"message": "If an account exists for that address, we've sent a link to reset the password."}


@router.post("/reset")
async def reset(body: ResetIn, request: Request, accounts: AccountsDep) -> Response:
    try:
        await accounts.reset_password(token=body.token, new=body.password)
    except AccountError as exc:
        raise _fail(exc) from None
    out = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_cookies(request, out)                      # every session was ended; sign in with the new password
    return out


@router.post("/ws-ticket")
async def ws_ticket(info: CurrentSession, accounts: AccountsDep) -> dict[str, str]:
    """A single-use, 60-second ticket for opening the live-event WebSocket (browsers cannot send our cookies to
    the API's WebSocket port through the Next.js proxy)."""
    return {"ticket": accounts.issue_ticket(info)}
