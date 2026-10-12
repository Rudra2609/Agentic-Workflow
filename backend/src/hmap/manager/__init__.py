"""Manager core (owner: Member 1): task state machine, task store, assignment, retries, watchdog, graph executor.

Other members extend it only through plug-in hooks and strategy slots (``hmap.core.plugins``)."""

from hmap.manager.config import ManagerConfig
from hmap.manager.executor import GraphExecutor, NaiveTopologicalExecutor
from hmap.manager.manager import InvalidProjectState, Manager, UnknownProject, UnknownTask
from hmap.manager.records import ApprovalRecord, ExecutionRecord, ProjectRecord, TaskRecord
from hmap.manager.store import (
    ConcurrencyConflict,
    InMemoryTaskStore,
    RecordNotFound,
    StoreError,
    TaskStore,
    TaskStoreTx,
    UniqueViolation,
)
from hmap.manager.transitions import ALLOWED, TransitionError, can_transition, check_transition, is_stale

__all__ = [
    "ALLOWED", "ApprovalRecord", "ConcurrencyConflict", "ExecutionRecord", "GraphExecutor", "InMemoryTaskStore",
    "InvalidProjectState", "Manager", "ManagerConfig", "NaiveTopologicalExecutor", "ProjectRecord",
    "RecordNotFound", "StoreError", "TaskRecord", "TaskStore", "TaskStoreTx", "TransitionError", "UniqueViolation",
    "UnknownProject", "UnknownTask", "can_transition", "check_transition", "is_stale",
]
