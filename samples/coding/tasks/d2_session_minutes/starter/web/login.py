"""Login page handlers: start a session, log out when it expired."""

from auth.sessions import is_expired


def still_logged_in(last_seen: float, now: float) -> bool:
    return not is_expired(last_seen, now)
