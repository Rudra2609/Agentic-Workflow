"""Per-provider pool of contributed API keys (doc 02 §2.5, item 1.14b).

Keys rotate round-robin. Each key has its own state: a cool-down deadline (set from a 429's ``retry-after`` or an
exponential default), a ``disabled`` flag (401/403 -> disabled until restart; the owner may have revoked it) and
usage counters. A key is only ever identified by its :func:`fingerprint` — the raw key is held privately and handed
out inside a :class:`KeyLease` whose ``repr`` hides it. All state changes happen under a lock and never ``await``,
so one pool is safe to share between asyncio tasks and threads.
"""

import hashlib
import threading
import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from typing import Any

from hmap.core.tracing import get_logger

log = get_logger("hmap.llm.keys")

DEFAULT_COOLDOWN_S = 5.0
MAX_DEFAULT_COOLDOWN_S = 300.0
MAX_COOLDOWN_S = 24 * 3600.0


def fingerprint(provider: str, key: str) -> str:
    """``provider:<8 hex>`` — a short SHA-256 prefix of the key. The ONLY key identifier ever logged or returned.
    A teammate can compute theirs with ``python -c "from hmap.core.llm import fingerprint; print(fingerprint('groq',
    '<key>'))"``."""
    return f"{provider}:{hashlib.sha256(key.encode('utf-8')).hexdigest()[:8]}"


class KeyLease:
    """A key handed out for one request. ``secret()`` is for the ``Authorization`` header only."""

    __slots__ = ("_key", "fingerprint", "provider")

    def __init__(self, provider: str, key: str, fp: str) -> None:
        self.provider = provider
        self.fingerprint = fp
        self._key = key

    def secret(self) -> str:
        return self._key

    def __repr__(self) -> str:
        return f"KeyLease({self.fingerprint})"

    __str__ = __repr__


@dataclass
class KeyState:
    """Mutable per-key state + counters (no secret in here)."""

    fingerprint: str
    provider: str
    cooling_until: float = 0.0
    disabled: bool = False
    strikes: int = 0  # consecutive 429s without retry-after -> exponential default cool-down
    requests: int = 0
    ok: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    rate_limited: int = 0
    auth_errors: int = 0
    errors: int = 0

    def snapshot(self, now: float) -> dict[str, Any]:
        return {"provider": self.provider, "requests": self.requests, "ok": self.ok,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "rate_limited": self.rate_limited, "auth_errors": self.auth_errors, "errors": self.errors,
                "disabled": self.disabled, "cooling_for_s": round(max(0.0, self.cooling_until - now), 3)}


class KeyPool:
    """Round-robin pool for one provider. ``clock`` is monotonic seconds (injectable for tests)."""

    def __init__(self, provider: str, keys: Sequence[str], *, clock: Callable[[], float] = time.monotonic,
                 default_cooldown_s: float = DEFAULT_COOLDOWN_S,
                 max_default_cooldown_s: float = MAX_DEFAULT_COOLDOWN_S) -> None:
        self.provider = provider
        self._clock = clock
        self.default_cooldown_s = default_cooldown_s
        self.max_default_cooldown_s = max_default_cooldown_s
        self._lock = threading.Lock()
        self._keys: list[str] = []
        self._states: list[KeyState] = []
        for key in keys:
            key = key.strip()
            if not key or key in self._keys:
                continue
            self._keys.append(key)
            self._states.append(KeyState(fingerprint=fingerprint(provider, key), provider=provider))
        self._by_fp = {s.fingerprint: s for s in self._states}
        self._cursor = 0

    def __len__(self) -> int:
        return len(self._keys)

    def __repr__(self) -> str:
        return f"KeyPool(provider={self.provider!r}, keys={len(self._keys)})"

    @property
    def fingerprints(self) -> list[str]:
        return [s.fingerprint for s in self._states]

    # ------------------------------------------------------------------ selection
    def acquire(self, exclude: Collection[str] = ()) -> KeyLease | None:
        """The next usable key (round-robin), skipping disabled, cooling and ``exclude``d fingerprints;
        ``None`` when no key is usable right now. Never waits."""
        with self._lock:
            n = len(self._keys)
            now = self._clock()
            for step in range(n):
                i = (self._cursor + step) % n
                state = self._states[i]
                if state.disabled or state.cooling_until > now or state.fingerprint in exclude:
                    continue
                self._cursor = (i + 1) % n
                state.requests += 1
                return KeyLease(self.provider, self._keys[i], state.fingerprint)
            return None

    def available(self) -> int:
        with self._lock:
            now = self._clock()
            return sum(1 for s in self._states if not s.disabled and s.cooling_until <= now)

    # ------------------------------------------------------------------ outcomes
    def mark_ok(self, fp: str, *, input_tokens: int = 0, output_tokens: int = 0) -> None:
        with self._lock:
            state = self._by_fp[fp]
            state.ok += 1
            state.strikes = 0
            state.input_tokens += max(0, input_tokens)
            state.output_tokens += max(0, output_tokens)

    def mark_rate_limited(self, fp: str, retry_after: float | None) -> float:
        """Cool the key for ``retry_after`` seconds, or ``default * 2**strikes`` (capped) when absent.
        Returns the cool-down applied."""
        with self._lock:
            state = self._by_fp[fp]
            state.rate_limited += 1
            if retry_after is not None:
                cooldown = min(max(0.0, retry_after), MAX_COOLDOWN_S)
            else:
                cooldown = min(self.default_cooldown_s * (2 ** state.strikes), self.max_default_cooldown_s)
            state.strikes += 1
            state.cooling_until = max(state.cooling_until, self._clock() + cooldown)
            return cooldown

    def mark_auth_error(self, fp: str) -> bool:
        """Disable the key until restart. Returns ``True`` the first time (logged once)."""
        with self._lock:
            state = self._by_fp[fp]
            state.auth_errors += 1
            newly = not state.disabled
            state.disabled = True
        if newly:
            log.warning("llm.cloud.key_disabled", provider=self.provider, key=fp,
                        reason="credentials refused; disabled until restart")
        return newly

    def mark_error(self, fp: str) -> None:
        with self._lock:
            self._by_fp[fp].errors += 1

    # ------------------------------------------------------------------ introspection
    def usage(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            now = self._clock()
            return {s.fingerprint: s.snapshot(now) for s in self._states}


__all__ = ["KeyLease", "KeyPool", "KeyState", "fingerprint"]
