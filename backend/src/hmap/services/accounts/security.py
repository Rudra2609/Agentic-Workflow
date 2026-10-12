"""Password hashing and opaque tokens (standard library only).

Passwords: scrypt (RFC 7914) with a random 16-byte salt, stored as ``scrypt$n$r$p$salt_b64$hash_b64`` so the cost can
be raised later without breaking old hashes (``needs_rehash``). Comparison is constant-time.

Tokens (sessions, password resets, WebSocket tickets): 32 random bytes, URL-safe. Only their SHA-256 is stored, so a
database leak does not hand out working sessions.
"""

import base64
import hashlib
import hmac
import re
import secrets

SCRYPT_N = 2**15          # 32 MiB per hash with r=8: strong, still fast enough (~70 ms) on a laptop
SCRYPT_R = 8
SCRYPT_P = 1
_MAXMEM = 128 * 1024 * 1024
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 256
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=_MAXMEM,
                            dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = _unb64(digest)
        actual = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), maxmem=_MAXMEM,
                                dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def needs_rehash(stored: str) -> bool:
    try:
        _, n, r, p, *_ = stored.split("$")
        return (int(n), int(r), int(p)) != (SCRYPT_N, SCRYPT_R, SCRYPT_P)
    except ValueError:
        return True


# A precomputed hash so a login for an unknown email costs the same time as a wrong password (no user enumeration).
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def password_problem(password: str, *, email: str = "", name: str = "") -> str | None:
    """A human-readable reason the password is too weak, or None. Length first (NIST SP 800-63B), plus a few
    obvious cases; no arbitrary composition rules."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Use at most {MAX_PASSWORD_LENGTH} characters."
    lowered = password.lower()
    if len(set(lowered)) < 4:
        return "Use a less repetitive password."
    local = email.split("@")[0].lower()
    if (local and len(local) >= 4 and local in lowered) or (name and len(name) >= 4 and name.lower() in lowered):
        return "Don't include your name or email address in the password."
    if lowered in {"password123", "1234567890", "qwertyuiop", "letmein123", "iloveyou12"}:
        return "This password is too common."
    return None


def normalize_email(email: str) -> str:
    return email.strip().lower()


def valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email)) and len(email) <= 254


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
