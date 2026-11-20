"""Login sessions: a session expires after its timeout (minutes) without activity."""

SESSION_TIMEOUT_MINUTES = 30


def is_expired(last_seen: float, now: float, timeout_minutes: int = SESSION_TIMEOUT_MINUTES) -> bool:
    """True when more than ``timeout_minutes`` passed since ``last_seen`` (times in seconds)."""
    return now - last_seen > timeout_minutes
