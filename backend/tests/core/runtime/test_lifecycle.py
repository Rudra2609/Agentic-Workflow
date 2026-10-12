import pytest

from hmap.core.contracts import AgentState as S
from hmap.core.runtime.lifecycle import (
    HEARTBEAT_STATES,
    TRANSITIONS,
    AgentLifecycle,
    InvalidTransition,
    can_transition,
)

ALLOWED = {
    (S.STARTING, S.REGISTERING), (S.STARTING, S.FAILED),
    (S.REGISTERING, S.AVAILABLE), (S.REGISTERING, S.RECOVERING),
    (S.RECOVERING, S.REGISTERING), (S.RECOVERING, S.FAILED),
    (S.AVAILABLE, S.BUSY), (S.AVAILABLE, S.DRAINING), (S.AVAILABLE, S.FAILED),
    (S.BUSY, S.AVAILABLE), (S.BUSY, S.DRAINING), (S.BUSY, S.FAILED),
    (S.DRAINING, S.OFFLINE),
    (S.FAILED, S.OFFLINE),
}


def test_table_covers_every_state() -> None:
    assert set(TRANSITIONS) == set(S)


@pytest.mark.parametrize("src", list(S))
@pytest.mark.parametrize("dst", list(S))
def test_transition_table(src: S, dst: S) -> None:
    assert can_transition(src, dst) == ((src, dst) in ALLOWED)
    fsm = AgentLifecycle(state=src)
    if (src, dst) in ALLOWED:
        fsm.to(dst, "test")
        assert fsm.state == dst and fsm.history[-1].src == src
    else:
        with pytest.raises(InvalidTransition):
            fsm.to(dst)
        assert fsm.state == src and not fsm.history


def test_busy_to_recovering_is_deliberately_absent() -> None:
    assert not can_transition(S.BUSY, S.RECOVERING)


def test_happy_path_and_try_to() -> None:
    seen = []
    fsm = AgentLifecycle(on_change=seen.append)
    for dst in (S.REGISTERING, S.AVAILABLE, S.BUSY, S.AVAILABLE, S.DRAINING, S.OFFLINE):
        fsm.to(dst)
    assert fsm.is_terminal and [t.dst for t in seen][-1] == S.OFFLINE
    assert fsm.try_to(S.AVAILABLE) is False  # OFFLINE is terminal
    fsm2 = AgentLifecycle(state=S.BUSY)
    assert fsm2.try_to(S.BUSY) is False and fsm2.try_to(S.AVAILABLE) is True


def test_heartbeat_states_match_contract() -> None:
    assert {S.AVAILABLE, S.BUSY, S.DRAINING, S.RECOVERING} == HEARTBEAT_STATES
