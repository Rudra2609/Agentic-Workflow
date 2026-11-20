"""API tokens: expire after a fixed number of seconds."""

TOKEN_TTL_SECONDS = 3600


def token_expired(issued_at: float, now: float, ttl_seconds: int = TOKEN_TTL_SECONDS) -> bool:
    return now - issued_at > ttl_seconds
