"""Task state machine (Sprint 1 item 1.6; research §9, §12, §17, §18).

Happy path: ``CREATED → READY → ASSIGNED → ACCEPTED → RUNNING → RESULT_SUBMITTED → (REVIEWING →) COMPLETED``.
Side exits: ``BLOCKED``, ``CANCELLED``, ``RETRY_SCHEDULED``, ``DEAD_LETTERED``, ``FAILED``, ``NEEDS_REVISION``.

Rules encoded here:

- ``ALLOWED`` is the single explicit table; anything else raises :class:`TransitionError`.
- Terminal states (``COMPLETED``, ``CANCELLED``, ``FAILED``, ``DEAD_LETTERED``) have no outgoing edges: they never
  regress.
- Replies may arrive out of order (at-least-once delivery), so ``ASSIGNED`` may jump to ``RUNNING`` (started before
  ack) and ``ASSIGNED``/``ACCEPTED`` may jump to ``RESULT_SUBMITTED`` (result before started).
- In Sprint 1 there is no reviewer, so ``RESULT_SUBMITTED → COMPLETED`` is allowed directly.
- ``OPERATOR_TRANSITIONS`` (Sprint 4, plan D18) are allowed only through an explicit, audited operator action
  (``Manager.replay_dead_letter``): ``DEAD_LETTERED → READY`` (a new execution) and, for the tasks that were waiting
  on it, ``BLOCKED → CREATED``. Agent reports and the watchdog can never take these edges.
- A report that points *backwards* along the happy path, or arrives after a terminal state (e.g. a late
  ``task.started`` after ``COMPLETED``), is :func:`is_stale`: the Manager records it as evidence and changes nothing.
"""

from typing import Literal

from hmap.core.contracts import TERMINAL_TASK_STATES, EventType, TaskState

S = TaskState

HAPPY_PATH: tuple[TaskState, ...] = (
    S.CREATED, S.READY, S.ASSIGNED, S.ACCEPTED, S.RUNNING, S.RESULT_SUBMITTED, S.REVIEWING, S.COMPLETED,
)

# Exits shared by every in-flight state (an execution exists): retry, give up, fail hard, cancel.
_IN_FLIGHT_EXITS = {S.RETRY_SCHEDULED, S.DEAD_LETTERED, S.FAILED, S.CANCELLED, S.BLOCKED}

ALLOWED: dict[TaskState, set[TaskState]] = {
    S.CREATED: {S.READY, S.BLOCKED, S.CANCELLED},
    S.READY: {S.ASSIGNED, S.BLOCKED, S.CANCELLED},
    # READY again = agent rejected the assignment -> reassign without consuming the retry budget
    S.ASSIGNED: {S.ACCEPTED, S.RUNNING, S.RESULT_SUBMITTED, S.READY} | _IN_FLIGHT_EXITS,
    S.ACCEPTED: {S.RUNNING, S.RESULT_SUBMITTED} | _IN_FLIGHT_EXITS,
    S.RUNNING: {S.RESULT_SUBMITTED} | _IN_FLIGHT_EXITS,
    S.RESULT_SUBMITTED: {S.REVIEWING, S.COMPLETED, S.NEEDS_REVISION, S.FAILED, S.CANCELLED},
    S.REVIEWING: {S.COMPLETED, S.NEEDS_REVISION, S.FAILED, S.CANCELLED},
    S.NEEDS_REVISION: {S.READY, S.ASSIGNED, S.FAILED, S.DEAD_LETTERED, S.CANCELLED},
    S.RETRY_SCHEDULED: {S.READY, S.DEAD_LETTERED, S.FAILED, S.CANCELLED},
    S.BLOCKED: {S.READY, S.FAILED, S.CANCELLED},
    S.COMPLETED: set(),
    S.CANCELLED: set(),
    S.FAILED: set(),
    S.DEAD_LETTERED: set(),
}

# Edges only an operator may take, never an agent report or the watchdog (DLQ replay, research §26).
OPERATOR_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    S.DEAD_LETTERED: {S.READY},
    S.BLOCKED: {S.CREATED},
}

# Domain event emitted when a task ENTERS a state.
STATE_EVENT: dict[TaskState, EventType] = {
    S.CREATED: EventType.TASK_CREATED,
    S.READY: EventType.TASK_READY,
    S.ASSIGNED: EventType.TASK_ASSIGNED,
    S.ACCEPTED: EventType.TASK_ACCEPTED,
    S.RUNNING: EventType.TASK_STARTED,
    S.RESULT_SUBMITTED: EventType.TASK_RESULT_SUBMITTED,
    S.REVIEWING: EventType.REVIEW_REQUESTED,
    S.COMPLETED: EventType.TASK_COMPLETED,
    S.BLOCKED: EventType.TASK_BLOCKED,
    S.CANCELLED: EventType.TASK_CANCELLED,
    S.RETRY_SCHEDULED: EventType.TASK_RETRYING,
    S.DEAD_LETTERED: EventType.TASK_DEAD_LETTERED,
    S.FAILED: EventType.TASK_FAILED,
    S.NEEDS_REVISION: EventType.REVISION_REQUESTED,
}

# States in which an execution is (or may be) in flight on an agent.
IN_FLIGHT_STATES: frozenset[TaskState] = frozenset({S.ASSIGNED, S.ACCEPTED, S.RUNNING})


class TransitionError(Exception):
    """A transition that is not in ``ALLOWED``."""

    def __init__(self, from_state: TaskState, to_state: TaskState, task_id: str | None = None) -> None:
        self.from_state = from_state
        self.to_state = to_state
        self.task_id = task_id
        where = f" (task {task_id})" if task_id else ""
        super().__init__(f"illegal task transition {from_state} -> {to_state}{where}")


def is_terminal(state: TaskState) -> bool:
    return state in TERMINAL_TASK_STATES


def can_transition(from_state: TaskState, to_state: TaskState) -> bool:
    return to_state in ALLOWED[from_state]


def check_transition(from_state: TaskState, to_state: TaskState, task_id: str | None = None, *,
                     operator: bool = False) -> None:
    """``operator=True`` also allows :data:`OPERATOR_TRANSITIONS` (only ``Manager.replay_dead_letter`` passes it)."""
    if can_transition(from_state, to_state):
        return
    if operator and to_state in OPERATOR_TRANSITIONS.get(from_state, set()):
        return
    raise TransitionError(from_state, to_state, task_id)


def is_stale(current: TaskState, reported: TaskState) -> bool:
    """True if a report that would move the task to ``reported`` is late/out-of-order and must not change state:
    the task is already terminal, or ``reported`` is not ahead of ``current`` on the happy path."""
    if is_terminal(current):
        return True
    if current in HAPPY_PATH and reported in HAPPY_PATH:
        return HAPPY_PATH.index(reported) <= HAPPY_PATH.index(current)
    return False


def classify(current: TaskState, reported: TaskState) -> Literal["apply", "stale", "illegal"]:
    """How the Manager treats an agent report: apply it, record it as evidence only, or flag it."""
    if is_stale(current, reported):
        return "stale"
    return "apply" if can_transition(current, reported) else "illegal"
