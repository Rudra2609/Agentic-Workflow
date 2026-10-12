"""Cross-process contracts (owner: Member 1). Import from here, e.g. ``from hmap.core.contracts import TaskAssign``."""

from hmap.core.contracts.capabilities import STUBBED_CAPABILITIES, CapabilityDescriptor
from hmap.core.contracts.common import (
    SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    AgentRef,
    ArtifactRef,
    ContextRef,
    Contract,
    Priority,
    ensure_compatible,
    is_compatible,
    negotiate,
    utcnow,
)
from hmap.core.contracts.domain import (
    DOMAIN_MODELS,
    ClaimVerdict,
    CodeChangeSet,
    Critique,
    DocBundle,
    Issue,
    PlanTask,
    RefinementSpec,
    RefinementTrace,
    RequirementSet,
    ResearchBrief,
    ResearchReport,
    ReviewReport,
    RouteDecision,
    TaskGraph,
    TestReport,
    VerificationReport,
)
from hmap.core.contracts.envelope import Envelope, make_envelope, parse_envelope
from hmap.core.contracts.events import DomainEvent, EventType
from hmap.core.contracts.messages import (
    COMMAND_TYPES,
    PAYLOAD_MODELS,
    AgentDeregister,
    AgentHeartbeat,
    AgentRegister,
    ContextRequest,
    ErrorPayload,
    Feedback,
    RetryRequest,
    RevisionRequest,
    TaskAck,
    TaskAssign,
    TaskCancel,
    TaskCompleted,
    TaskProgress,
    TaskResult,
    TaskStarted,
)
from hmap.core.contracts.states import TERMINAL_TASK_STATES, AgentState, ExecutionStatus, ProjectState, TaskState

__all__ = [
    "COMMAND_TYPES", "DOMAIN_MODELS", "PAYLOAD_MODELS", "SCHEMA_VERSION", "STUBBED_CAPABILITIES",
    "SUPPORTED_SCHEMA_VERSIONS", "TERMINAL_TASK_STATES",
    "AgentDeregister", "AgentHeartbeat", "AgentRef", "AgentRegister", "AgentState", "ArtifactRef",
    "CapabilityDescriptor", "ClaimVerdict", "CodeChangeSet", "ContextRef", "ContextRequest", "Contract", "Critique",
    "DocBundle", "DomainEvent", "Envelope", "ErrorPayload", "EventType", "ExecutionStatus", "Feedback", "Issue",
    "PlanTask", "Priority", "ProjectState", "RefinementSpec", "RefinementTrace", "RequirementSet", "ResearchBrief",
    "ResearchReport", "RetryRequest", "ReviewReport", "RevisionRequest", "RouteDecision", "TaskAck", "TaskAssign",
    "TaskCancel", "TaskCompleted", "TaskGraph", "TaskProgress", "TaskResult", "TaskStarted", "TaskState",
    "TestReport", "VerificationReport", "ensure_compatible", "is_compatible", "make_envelope", "negotiate",
    "parse_envelope", "utcnow",
]
