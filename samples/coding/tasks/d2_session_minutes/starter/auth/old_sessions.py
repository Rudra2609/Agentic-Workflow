"""DEPRECATED session store (cookie based); kept until the migration ends. Not used for timeouts."""


def session_cookie_name() -> str:
    return "sid"
