"""Basic security layer (Sprint 6 item 6.20, owner Member 6; was Sprint 1 item 1.18) and token lifecycle (6.15).

The platform runs on one laptop (doc 02 §3), so the threat this layer handles is **a message on the bus that did
not come from a platform process**: anything that can reach RabbitMQ (the dev ``hmap/hmap`` account) or the
in-process bus, a stray script, a replayed or edited message, or an agent reporting on work it was never given.

**Service tokens.** Each agent's token is ``v1.<kid>.<exp>.<sig>``, ``sig = HMAC-SHA256(secret[kid],
"v1|kid|agent_id|exp")``. The secret comes from a *keyring*: ``HMAP_AGENT_SECRETS="kid:secret,..."`` (newest
first), else the local file ``data/security/agent_keys.json`` (mode 0600, created on first use, git-ignored: the
"seeded" dev keyring every process on this laptop shares). The agent runtime derives its token when it registers;
the token itself never travels (a bus reader could reuse it): every message carries a signature keyed by it. The
Manager re-derives tokens from the keyring, so it keeps no token table and a restart logs nobody out.

**Signed messages.** Every envelope built with ``make_envelope`` carries ``auth = v1.<kid>.<exp>.<mac>``, ``mac =
HMAC(token, message_id|type|sender|task|execution|sha256(payload))``: it proves the sender holds a valid token and
that nothing in the message was changed. A message without a valid ``auth`` is refused.

**Lifecycle.** ``python -m hmap.core.policy rotate`` adds a new key in front; senders switch to it on their next
message, the old key keeps verifying until ``retire <kid>`` (no downtime). Tokens expire after
``HMAP_AGENT_TOKEN_TTL_S`` (renewed automatically at half-life). ``revoke <agent_id>`` refuses one agent at once.
Secrets and tokens are never logged: only a short fingerprint (:func:`fingerprint`).

**Policy table** (:data:`POLICY_TABLE`): which messages an agent may send to the Manager, and the extra condition
for each (identity = the payload's agent is the sender; assigned = the sender is a registered agent serving the
task's capability). Commands to agents may only come from the Manager.

Every refusal is written to the **audit log** (memory, plus the ``security_audit`` table on Postgres) and, with
``HMAP_SECURITY_ENFORCE=true`` (default), the message is dropped; with ``false`` it is only audited.

Also here: :class:`RateLimiter` (API write requests) and :func:`content_matches` (an upload's bytes match its type).
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from hmap.core.config import REPO_ROOT, Settings
from hmap.core.contracts.envelope import MAX_MESSAGE_BYTES, Envelope, register_signer
from hmap.core.tracing import get_logger

log = get_logger("hmap.security")
KEYS_FILE = REPO_ROOT / "data" / "security" / "agent_keys.json"
VERSION = "v1"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def fingerprint(secret: str | bytes) -> str:
    """A short, non-reversible id for logs (never log a token or secret)."""
    raw = secret.encode() if isinstance(secret, str) else secret
    return hashlib.sha256(raw).hexdigest()[:8]


# ===================================================================================================== keyring


@dataclass
class Keyring:
    """Signing keys, newest first, plus revoked agent ids. File-backed keyrings reload when the file changes."""

    keys: list[tuple[str, bytes]] = field(default_factory=list)
    revoked: set[str] = field(default_factory=set)
    path: Path | None = None
    _mtime: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def from_settings(cls, settings: Settings | None = None, *, path: Path | None = None) -> "Keyring":
        s = settings or Settings.from_env()
        if s.agent_secrets:
            keys = []
            for raw in s.agent_secrets:
                value = raw.get_secret_value()
                kid, _, secret = value.partition(":") if ":" in value else (f"k{fingerprint(value)}", "", value)
                keys.append((kid.strip(), secret.strip().encode()))
            return cls(keys=keys)
        ring = cls(path=path or KEYS_FILE)
        ring.reload(force=True)
        return ring

    # ------------------------------------------------------------------ file
    def _read(self) -> dict[str, Any]:
        assert self.path is not None
        try:
            data: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
            return data
        except FileNotFoundError:
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        assert self.path is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(f".{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, self.path)

    def reload(self, *, force: bool = False) -> None:
        if self.path is None:
            return
        with self._lock:
            try:
                mtime = self.path.stat().st_mtime
            except FileNotFoundError:
                mtime = -1.0
            if not force and mtime == self._mtime:
                return
            data = self._read()
            if not data.get("keys"):
                # a random key id: messages signed by another copy's keyring then read "unknown key", not "forged"
                data = {"keys": [{"kid": f"dev-{secrets.token_hex(3)}", "secret": secrets.token_hex(32),
                                  "created_at": _now_iso()}],
                        "revoked": [], "note": "local dev keyring (Sprint 6); never commit or share this file"}
                try:
                    self._write_new(data)
                except FileExistsError:                       # another process created it first
                    data = self._read()
                mtime = self.path.stat().st_mtime
            self.keys = [(k["kid"], str(k["secret"]).encode()) for k in data.get("keys", [])]
            self.revoked = set(data.get("revoked", []))
            self._mtime = mtime

    def _write_new(self, data: dict[str, Any]) -> None:
        assert self.path is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)

    def _update(self, change: Callable[[dict[str, Any]], None]) -> None:
        if self.path is None:   # env keyring: change in memory only
            data: dict[str, Any] = {"keys": [{"kid": k, "secret": s.decode()} for k, s in self.keys],
                                    "revoked": sorted(self.revoked)}
            change(data)
            self.keys = [(k["kid"], str(k["secret"]).encode()) for k in data["keys"]]
            self.revoked = set(data["revoked"])
            return
        self.reload()
        data = self._read()
        change(data)
        self._write(data)
        self.reload(force=True)

    # ------------------------------------------------------------------ lifecycle
    def rotate(self) -> str:
        """Add a new key in front; the old ones keep verifying until retired. Returns the new kid."""
        kid = f"k{secrets.token_hex(3)}"

        def change(d: dict[str, Any]) -> None:
            d.setdefault("keys", []).insert(0, {"kid": kid, "secret": secrets.token_hex(32), "created_at": _now_iso()})
        self._update(change)
        log.info("agent key rotated", kid=kid)
        return kid

    def retire(self, kid: str) -> None:
        def change(d: dict[str, Any]) -> None:
            keys = [k for k in d.get("keys", []) if k["kid"] != kid]
            if not keys:
                raise ValueError("cannot retire the last key")
            d["keys"] = keys
        self._update(change)
        log.info("agent key retired", kid=kid)

    def revoke(self, agent_id: str) -> None:
        def change(d: dict[str, Any]) -> None:
            d["revoked"] = sorted({*d.get("revoked", []), agent_id})
        self._update(change)
        log.info("agent token revoked", agent_id=agent_id)

    def unrevoke(self, agent_id: str) -> None:
        def change(d: dict[str, Any]) -> None:
            d["revoked"] = sorted(set(d.get("revoked", [])) - {agent_id})
        self._update(change)

    def newest(self) -> tuple[str, bytes]:
        self.reload()
        return self.keys[0]

    def get(self, kid: str) -> bytes | None:
        self.reload()
        return next((s for k, s in self.keys if k == kid), None)

    def is_revoked(self, agent_id: str) -> bool:
        self.reload()
        return agent_id in self.revoked


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ====================================================================================================== tokens


@dataclass(frozen=True)
class Decision:
    allowed: bool
    rule: str
    reason: str = ""

    @staticmethod
    def allow(rule: str) -> "Decision":
        return Decision(True, rule)

    @staticmethod
    def deny(rule: str, reason: str) -> "Decision":
        return Decision(False, rule, reason)


def _sig(secret: bytes, kid: str, agent_id: str, exp: int) -> str:
    return _b64(hmac.new(secret, f"{VERSION}|{kid}|{agent_id}|{exp}".encode(), hashlib.sha256).digest())


def issue_token(keyring: Keyring, agent_id: str, *, ttl_s: int, now: float | None = None) -> str:
    kid, secret = keyring.newest()
    exp = int((now if now is not None else time.time()) + ttl_s)
    return f"{VERSION}.{kid}.{exp}.{_sig(secret, kid, agent_id, exp)}"


def check_token(keyring: Keyring, token: str | None, agent_id: str, *, now: float | None = None) -> Decision:
    if not token:
        return Decision.deny("token", "no service token")
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != VERSION or not parts[2].isdigit():
        return Decision.deny("token", "malformed service token")
    _, kid, exp_s, sig = parts
    secret = keyring.get(kid)
    if secret is None:
        return Decision.deny("token", "unknown or retired signing key")
    if not hmac.compare_digest(sig, _sig(secret, kid, agent_id, int(exp_s))):
        return Decision.deny("token", "token signature does not match this agent")
    if int(exp_s) < (now if now is not None else time.time()):
        return Decision.deny("token", "token expired")
    if keyring.is_revoked(agent_id):
        return Decision.deny("token", "agent revoked")
    return Decision.allow("token")


def _canonical(env: Envelope) -> bytes:
    body = json.dumps(env.payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return "|".join([env.message_id, env.message_type, env.sender.agent_id, env.task_id or "", env.execution_id or "",
                     hashlib.sha256(body).hexdigest()]).encode()


def _mac(token: str, env: Envelope) -> str:
    return _b64(hmac.new(token.encode(), _canonical(env), hashlib.sha256).digest())


@dataclass
class Signer:
    """Signs envelopes for any sender in this process (agents and the Manager), renewing tokens at half-life and
    switching to the newest key after a rotation."""

    keyring: Keyring
    ttl_s: int = 7 * 24 * 3600
    _tokens: dict[str, tuple[str, str, int]] = field(default_factory=dict)   # agent -> (token, kid, exp)

    def token(self, agent_id: str, *, now: float | None = None) -> str:
        t = now if now is not None else time.time()
        kid, _ = self.keyring.newest()
        cached = self._tokens.get(agent_id)
        if cached is None or cached[1] != kid or cached[2] - t < self.ttl_s / 2:
            tok = issue_token(self.keyring, agent_id, ttl_s=self.ttl_s, now=t)
            cached = (tok, kid, int(tok.split(".")[2]))
            self._tokens[agent_id] = cached
        return cached[0]

    def sign(self, env: Envelope) -> str:
        tok = self.token(env.sender.agent_id)
        _, kid, exp, _ = tok.split(".")
        return f"{VERSION}.{kid}.{exp}.{_mac(tok, env)}"


def check_auth(keyring: Keyring, env: Envelope, *, now: float | None = None) -> Decision:
    auth = env.auth
    if not auth:
        return Decision.deny("auth", "message is not signed")
    parts = auth.split(".")
    if len(parts) != 4 or parts[0] != VERSION or not parts[2].isdigit():
        return Decision.deny("auth", "malformed signature")
    _, kid, exp_s, mac = parts
    secret = keyring.get(kid)
    if secret is None:
        return Decision.deny("auth", "unknown or retired signing key")
    token = f"{VERSION}.{kid}.{exp_s}.{_sig(secret, kid, env.sender.agent_id, int(exp_s))}"
    if not hmac.compare_digest(mac, _mac(token, env)):
        return Decision.deny("auth", "signature does not match the message (forged or changed)")
    if int(exp_s) < (now if now is not None else time.time()):
        return Decision.deny("auth", "token expired")
    if keyring.is_revoked(env.sender.agent_id):
        return Decision.deny("auth", "agent revoked")
    return Decision.allow("auth")


# ======================================================================================================= audit


@dataclass(frozen=True)
class AuditEntry:
    at: str
    decision: str            # "allow" | "deny"
    rule: str
    reason: str
    sender: str
    message_type: str
    message_id: str
    task_id: str | None = None
    execution_id: str | None = None
    project_id: str | None = None
    enforced: bool = True

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class AuditSink(Protocol):
    async def write(self, entry: AuditEntry) -> None: ...

    async def recent(self, limit: int = 100) -> list[AuditEntry]: ...


class MemoryAudit:
    def __init__(self, maxlen: int = 2000) -> None:
        self.entries: deque[AuditEntry] = deque(maxlen=maxlen)

    async def write(self, entry: AuditEntry) -> None:
        self.entries.append(entry)

    async def recent(self, limit: int = 100) -> list[AuditEntry]:
        return list(self.entries)[-limit:][::-1]


class PgAudit:
    """``security_audit`` (migration 006). Writes never fail the caller: a lost audit row is logged."""

    def __init__(self, db: Any) -> None:
        self.db = db

    async def write(self, entry: AuditEntry) -> None:
        try:
            async with self.db.connection() as c:
                await c.execute(
                    "INSERT INTO security_audit (at, decision, rule, reason, sender, message_type, message_id, task_id,"
                    " execution_id, project_id, enforced) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (entry.at, entry.decision, entry.rule, entry.reason, entry.sender, entry.message_type,
                     entry.message_id, entry.task_id, entry.execution_id, entry.project_id, entry.enforced))
        except Exception as exc:
            log.warning("audit row not written", error=type(exc).__name__)

    async def recent(self, limit: int = 100) -> list[AuditEntry]:
        rows = await self.db.fetch("SELECT at, decision, rule, reason, sender, message_type, message_id, task_id, "
                                   "execution_id, project_id, enforced FROM security_audit ORDER BY id DESC LIMIT %s",
                                   (limit,))
        return [AuditEntry(**{**r, "at": r["at"].astimezone(UTC).isoformat() if hasattr(r["at"], "astimezone")
                              else str(r["at"])}) for r in rows]


AUDIT = MemoryAudit()        # per process; the Manager also writes to Postgres when it runs on Postgres


# ====================================================================================================== policy

_ASSIGNED = "assigned: the sender is a registered agent serving the task's capability"
AGENT_REPORTS: dict[str, str] = {
    "agent.register": "identity + valid service token",
    "agent.heartbeat": "identity",
    "agent.deregister": "identity",
    "task.ack": _ASSIGNED,
    "task.started": _ASSIGNED,
    "task.progress": _ASSIGNED,
    "task.result": _ASSIGNED,
    "error": _ASSIGNED + " (or an error without a task)",
    "retry.request": _ASSIGNED,
    "context.request": _ASSIGNED,
}
MANAGER_COMMANDS = frozenset({"task.assign", "task.cancel", "revision.request", "feedback", "task.completed"})
POLICY_TABLE: list[dict[str, str]] = (
    [{"message": m, "from": "an agent", "to": "the Manager", "condition": c} for m, c in AGENT_REPORTS.items()]
    + [{"message": m, "from": "the Manager", "to": "an agent", "condition": "sender is the Manager"}
       for m in sorted(MANAGER_COMMANDS)])


class PolicyContext(Protocol):
    async def agent_capabilities(self, agent_id: str) -> list[str] | None: ...

    async def execution(self, execution_id: str) -> tuple[str | None, str] | None:
        """(assigned agent id, task capability) or None when unknown."""


class Policy:
    """Checks one message. ``check_report`` runs in the Manager before any state change; ``check_command`` in the
    agent runtime before a command is executed."""

    def __init__(self, settings: Settings | None = None, *, keyring: Keyring | None = None,
                 audit: Sequence[AuditSink] = (), manager_id: str = "manager") -> None:
        s = settings or Settings.from_env()
        self._keyring = keyring                 # None: the process signer's keyring (follows policy.install)
        self.enforce = s.security_enforce
        self.audit_sinks: list[AuditSink] = [AUDIT, *audit]
        self.manager_id = manager_id

    @property
    def keyring(self) -> Keyring:
        return self._keyring or signer().keyring

    async def _record(self, env: Envelope, d: Decision) -> None:
        entry = AuditEntry(at=_now_iso(), decision="allow" if d.allowed else "deny", rule=d.rule, reason=d.reason,
                           sender=env.sender.agent_id, message_type=env.message_type, message_id=env.message_id,
                           task_id=env.task_id, execution_id=env.execution_id, project_id=env.project_id,
                           enforced=self.enforce)
        for sink in self.audit_sinks:
            await sink.write(entry)
        if not d.allowed:
            log.warning("message refused" if self.enforce else "message would be refused (audit only)",
                        sender=env.sender.agent_id, message_type=env.message_type, rule=d.rule, reason=d.reason)

    async def _decide_report(self, env: Envelope, payload: Any, ctx: PolicyContext) -> Decision:
        if len(env.model_dump_json()) > MAX_MESSAGE_BYTES:
            return Decision.deny("size", f"message larger than {MAX_MESSAGE_BYTES} bytes")
        if env.message_type not in AGENT_REPORTS:
            return Decision.deny("table", f"agents may not send {env.message_type}")
        auth = check_auth(self.keyring, env)
        if not auth.allowed:
            return auth
        sender = env.sender.agent_id
        if env.message_type.startswith("agent."):
            if getattr(payload, "agent_id", None) != sender:
                return Decision.deny("identity", "the message speaks for another agent")
            # the signature is keyed by the agent's token, so it already proves the agent holds one; a token sent
            # in the registration must also be valid (older clients send none)
            if env.message_type == "agent.register" and getattr(payload, "token", None):
                tok = check_token(self.keyring, payload.token, sender)
                if not tok.allowed:
                    return tok
            return Decision.allow("identity")
        execution_id = env.execution_id or getattr(payload, "execution_id", None)
        if not execution_id:
            return (Decision.allow("assigned") if env.message_type == "error"
                    else Decision.deny("assigned", "a task report without an execution"))
        found = await ctx.execution(execution_id)
        if found is None:
            return Decision.allow("assigned")        # unknown execution: the Manager ignores it anyway
        _, capability = found
        # Commands go to a per-capability queue and any instance serving it may take one (the Manager binds the
        # execution to whoever acks it; after a crash the broker redelivers to the new instance). So the rule is:
        # the sender is a registered agent that serves this task's capability.
        caps = await ctx.agent_capabilities(sender)
        if caps is None:
            return Decision.deny("assigned", "the sender is not a registered agent")
        if capability not in caps:
            return Decision.deny("assigned", f"the agent did not register capability {capability}")
        return Decision.allow("assigned")

    async def check_report(self, env: Envelope, payload: Any, ctx: PolicyContext) -> bool:
        """True = handle the message. Refusals (and registrations) are audited."""
        d = await self._decide_report(env, payload, ctx)
        if not d.allowed or env.message_type == "agent.register":
            await self._record(env, d)
        return d.allowed or not self.enforce

    async def check_command(self, env: Envelope) -> bool:
        if env.sender.agent_id != self.manager_id:
            d = Decision.deny("table", "commands may only come from the Manager")
        else:
            d = check_auth(self.keyring, env)
        if not d.allowed:
            await self._record(env, d)
        return d.allowed or not self.enforce


# ======================================================================================= process-wide installation

_SIGNER: Signer | None = None
_INSTALL_LOCK = threading.Lock()


def install(settings: Settings | None = None, *, keyring: Keyring | None = None) -> Signer:
    """Sign every envelope this process builds (idempotent). Called by the Manager and the agent runtime."""
    global _SIGNER
    with _INSTALL_LOCK:
        if _SIGNER is None or keyring is not None:
            s = settings or Settings.from_env()
            _SIGNER = Signer(keyring or Keyring.from_settings(s), ttl_s=s.agent_token_ttl_s)
            register_signer(_SIGNER.sign)
        return _SIGNER


def signer() -> Signer:
    return _SIGNER or install()


_COMMAND_POLICY: Policy | None = None


def command_policy() -> Policy:
    """One policy per process for the agent runtime (installs the signer too)."""
    global _COMMAND_POLICY
    signer()
    if _COMMAND_POLICY is None:
        _COMMAND_POLICY = Policy()
    return _COMMAND_POLICY


# ======================================================================================== API limits (6.17)


class RateLimiter:
    """Token bucket per key (user or address): ``rate`` requests per second, bursts up to ``burst``. In memory, so per
    process (the API is one process on the demo laptop)."""

    def __init__(self, rate: float, burst: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.rate, self.burst, self.clock = rate, burst, clock
        self._buckets: dict[str, tuple[float, float]] = {}

    def allow(self, key: str) -> bool:
        now = self.clock()
        tokens, last = self._buckets.get(key, (float(self.burst), now))
        tokens = min(float(self.burst), tokens + (now - last) * self.rate)
        if tokens < 1:
            self._buckets[key] = (tokens, now)
            return False
        self._buckets[key] = (tokens - 1, now)
        if len(self._buckets) > 10_000:                     # forget idle clients
            self._buckets = dict(list(self._buckets.items())[-5_000:])
        return True


_MAGIC: dict[str, tuple[bytes, ...]] = {
    "application/pdf": (b"%PDF-",),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (b"PK\x03\x04",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
}


def content_matches(media_type: str, data: bytes) -> bool:
    """The upload's first bytes match its declared type (a renamed executable is not a PDF). Text types must decode
    as UTF-8 and contain no NUL bytes."""
    if media_type in _MAGIC:
        return any(data.startswith(m) for m in _MAGIC[media_type])
    if media_type.startswith("text/"):
        head = data[:65536]
        if b"\x00" in head:
            return False
        try:
            head.decode("utf-8")
        except UnicodeDecodeError as exc:
            return exc.start >= len(head) - 4          # a multi-byte character cut at the 64 KiB boundary
        return True
    return True


# ============================================================================================ command line


def _main(argv: list[str]) -> int:
    ring = Keyring.from_settings()
    cmd = argv[0] if argv else "status"
    if cmd == "rotate":
        print(f"new key {ring.rotate()} (old keys keep working until retired)")
    elif cmd == "retire" and len(argv) == 2:
        ring.retire(argv[1])
        print(f"retired {argv[1]}")
    elif cmd == "revoke" and len(argv) == 2:
        ring.revoke(argv[1])
        print(f"revoked {argv[1]}")
    elif cmd == "unrevoke" and len(argv) == 2:
        ring.unrevoke(argv[1])
        print(f"unrevoked {argv[1]}")
    elif cmd == "status":
        src = str(ring.path) if ring.path else "HMAP_AGENT_SECRETS"
        print(f"keyring: {src}")
        for kid, secret in ring.keys:
            print(f"  key {kid}  fingerprint {fingerprint(secret)}")
        print(f"  revoked agents: {', '.join(sorted(ring.revoked)) or 'none'}")
    else:
        print("usage: python -m hmap.core.policy [status | rotate | retire <kid> | revoke <agent> | unrevoke <agent>]")
        return 2
    return 0


AsyncCheck = Callable[[Envelope], Awaitable[bool]]

if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
