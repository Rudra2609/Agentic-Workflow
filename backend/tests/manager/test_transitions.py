import itertools

import pytest

from hmap.core.contracts import TERMINAL_TASK_STATES, TaskState
from hmap.manager.transitions import (
    ALLOWED,
    HAPPY_PATH,
    STATE_EVENT,
    TransitionError,
    can_transition,
    check_transition,
    classify,
    is_stale,
)

S = TaskState
ALL_EDGES = [(a, b) for a, targets in ALLOWED.items() for b in sorted(targets)]
FORBIDDEN = [
    (S.CREATED, S.RUNNING), (S.CREATED, S.COMPLETED), (S.READY, S.COMPLETED), (S.READY, S.RUNNING),
    (S.RUNNING, S.READY), (S.RUNNING, S.ASSIGNED), (S.RESULT_SUBMITTED, S.RUNNING), (S.ACCEPTED, S.READY),
    (S.RETRY_SCHEDULED, S.RUNNING), (S.BLOCKED, S.RUNNING), (S.REVIEWING, S.RUNNING),
    (S.COMPLETED, S.RUNNING), (S.COMPLETED, S.READY), (S.CANCELLED, S.READY), (S.FAILED, S.RETRY_SCHEDULED),
    (S.DEAD_LETTERED, S.READY), (S.CREATED, S.CREATED),
]


def test_table_covers_every_state() -> None:
    assert set(ALLOWED) == set(TaskState)
    assert set(STATE_EVENT) == set(TaskState)


@pytest.mark.parametrize(("src", "dst"), ALL_EDGES, ids=[f"{a}->{b}" for a, b in ALL_EDGES])
def test_allowed(src: TaskState, dst: TaskState) -> None:
    assert can_transition(src, dst)
    check_transition(src, dst)


@pytest.mark.parametrize(("src", "dst"), FORBIDDEN, ids=[f"{a}->{b}" for a, b in FORBIDDEN])
def test_forbidden(src: TaskState, dst: TaskState) -> None:
    assert not can_transition(src, dst)
    with pytest.raises(TransitionError) as exc:
        check_transition(src, dst, "T-1")
    assert exc.value.from_state == src and exc.value.to_state == dst and "T-1" in str(exc.value)


def test_happy_path_is_allowed_step_by_step() -> None:
    for a, b in itertools.pairwise(HAPPY_PATH):
        assert can_transition(a, b), (a, b)
    assert can_transition(S.RESULT_SUBMITTED, S.COMPLETED)  # Sprint 1: no reviewer


@pytest.mark.parametrize("terminal", sorted(TERMINAL_TASK_STATES))
def test_terminal_states_never_regress(terminal: TaskState) -> None:
    assert ALLOWED[terminal] == set()
    for target in TaskState:
        assert not can_transition(terminal, target)
        assert is_stale(terminal, target)


def test_side_exits_from_in_flight_states() -> None:
    for s in (S.ASSIGNED, S.ACCEPTED, S.RUNNING):
        for exit_ in (S.RETRY_SCHEDULED, S.DEAD_LETTERED, S.FAILED, S.CANCELLED, S.BLOCKED):
            assert can_transition(s, exit_)


def test_late_started_after_completed_is_stale_not_illegal() -> None:
    assert classify(S.COMPLETED, S.RUNNING) == "stale"
    assert classify(S.RUNNING, S.ACCEPTED) == "stale"         # duplicate / out-of-order ack
    assert classify(S.RESULT_SUBMITTED, S.RUNNING) == "stale"
    assert classify(S.ACCEPTED, S.RUNNING) == "apply"
    assert classify(S.ASSIGNED, S.RUNNING) == "apply"         # started overtook the ack
    assert classify(S.BLOCKED, S.RUNNING) == "illegal"
