"""Agent lifecycle FSM (research §16, §21). The worker owns one ``AgentLifecycle`` and advertises its state in
heartbeats; the Registry independently marks an agent OFFLINE when its lease expires.

    STARTING    -> REGISTERING | FAILED
    REGISTERING -> AVAILABLE (registration sent) | RECOVERING (temporary fault)
    RECOVERING  -> REGISTERING (retry) | FAILED (retry budget exhausted)
    AVAILABLE   -> BUSY (accepted assignment) | DRAINING (shutdown) | FAILED
    BUSY        -> AVAILABLE (last execution finished) | DRAINING | FAILED
    DRAINING    -> OFFLINE (deregistered)
    FAILED      -> OFFLINE

``BUSY -> RECOVERING`` is deliberately absent (§21): a crash mid-execution is FAILED, not RECOVERING.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from hmap.core.contracts import AgentState, utcnow
from hmap.core.errors import ErrorCode, HmapError

S = AgentState

TRANSITIONS: dict[AgentState, frozenset[AgentState]] = {
    S.STARTING: frozenset({S.REGISTERING, S.FAILED}),
    S.REGISTERING: frozenset({S.AVAILABLE, S.RECOVERING}),
    S.RECOVERING: frozenset({S.REGISTERING, S.FAILED}),
    S.AVAILABLE: frozenset({S.BUSY, S.DRAINING, S.FAILED}),
    S.BUSY: frozenset({S.AVAILABLE, S.DRAINING, S.FAILED}),
    S.DRAINING: frozenset({S.OFFLINE}),
    S.FAILED: frozenset({S.OFFLINE}),
    S.OFFLINE: frozenset(),
}

# States an agent may advertise in a heartbeat (AgentHeartbeat.state).
HEARTBEAT_STATES: frozenset[AgentState] = frozenset({S.AVAILABLE, S.BUSY, S.DRAINING, S.RECOVERING})
# States in which the worker accepts new assignments.
ACCEPTING_STATES: frozenset[AgentState] = frozenset({S.AVAILABLE, S.BUSY})


class InvalidTransition(HmapError):
    code = ErrorCode.INTERNAL_AGENT


def can_transition(src: AgentState, dst: AgentState) -> bool:
    return dst in TRANSITIONS[src]


@dataclass(frozen=True)
class Transition:
    src: AgentState
    dst: AgentState
    reason: str
    at: datetime


@dataclass
class AgentLifecycle:
    state: AgentState = S.STARTING
    history: list[Transition] = field(default_factory=list)
    on_change: Callable[[Transition], None] | None = None

    def to(self, dst: AgentState, reason: str = "") -> Transition:
        """Move to ``dst`` or raise ``InvalidTransition``."""
        if not can_transition(self.state, dst):
            raise InvalidTransition(f"agent state {self.state} -> {dst} is not allowed ({reason})")
        tr = Transition(self.state, dst, reason, utcnow())
        self.state = dst
        self.history.append(tr)
        if self.on_change is not None:
            self.on_change(tr)
        return tr

    def try_to(self, dst: AgentState, reason: str = "") -> bool:
        """Move if allowed; return whether the state changed (for idempotent paths like BUSY<->AVAILABLE)."""
        if self.state == dst or not can_transition(self.state, dst):
            return False
        self.to(dst, reason)
        return True

    @property
    def is_terminal(self) -> bool:
        return self.state == S.OFFLINE
