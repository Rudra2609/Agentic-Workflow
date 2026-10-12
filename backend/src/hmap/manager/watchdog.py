"""Watchdog decisions (research §21, §25, §26, §35): ack timeouts and abandoned executions. Pure functions over
records; ``Manager.tick`` applies them."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from hmap.core.contracts import AgentState, ExecutionStatus
from hmap.manager.assignment import IN_FLIGHT_EXECUTIONS
from hmap.manager.records import ExecutionRecord
from hmap.services.registry.base import AgentRecord


def ack_timed_out(executions: Iterable[ExecutionRecord], now: datetime) -> list[ExecutionRecord]:
    """Assigned executions whose ack deadline passed without a ``task.ack``."""
    return [e for e in executions
            if e.status == ExecutionStatus.PENDING and e.lease_until is not None and e.lease_until <= now]


def agent_gone(agent_id: str | None, agents: Mapping[str, AgentRecord]) -> bool:
    if agent_id is None:
        return False
    rec = agents.get(agent_id)
    return rec is None or rec.state == AgentState.OFFLINE


@dataclass
class OrphanScan:
    newly_orphaned: list[ExecutionRecord]   # agent just went away: start the grace period
    abandoned: list[ExecutionRecord]        # grace period over and the agent is still away: retry
    recovered: list[ExecutionRecord]        # agent came back within the grace period: clear the mark


def agent_vouches(e: ExecutionRecord, agents: Mapping[str, AgentRecord]) -> bool:
    """The agent is live and its latest heartbeat lists this execution."""
    rec = agents.get(e.agent_id) if e.agent_id else None
    return rec is not None and rec.state != AgentState.OFFLINE and e.execution_id in rec.current_execution_ids


def scan_orphans(executions: Iterable[ExecutionRecord], agents: Mapping[str, AgentRecord], now: datetime,
                 grace: timedelta) -> OrphanScan:
    """An execution is orphaned when its agent went OFFLINE / deregistered (or re-registered as a fresh instance).
    It is abandoned only after ``grace`` -- never because of one late heartbeat -- unless the agent comes back and
    its heartbeat lists the execution again."""
    scan = OrphanScan([], [], [])
    for e in executions:
        if e.status not in IN_FLIGHT_EXECUTIONS:
            continue
        if e.orphaned_at is None:
            if agent_gone(e.agent_id, agents):
                scan.newly_orphaned.append(e)
        elif agent_vouches(e, agents):
            scan.recovered.append(e)
        elif now - e.orphaned_at >= grace:
            scan.abandoned.append(e)
    return scan
