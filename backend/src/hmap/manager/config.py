"""Manager tunables (research §23 defaults)."""

from dataclasses import dataclass

from hmap.core.bus.base import DEFAULT_RETRY_DELAYS_S


@dataclass(frozen=True)
class ManagerConfig:
    manager_id: str = "manager"
    ack_timeout_s: float = 30.0                       # ASSIGNED without task.ack -> retryable TIMEOUT
    retry_delays_s: tuple[float, ...] = DEFAULT_RETRY_DELAYS_S  # 5 s, 30 s, 2 min
    retry_jitter: float = 0.1                         # + uniform(0, jitter * delay): bounded random jitter
    max_retries: int = 3                              # after this many retries a retryable failure dead-letters
    offline_grace_s: float = 15.0                     # agent OFFLINE -> wait this long before abandoning its work
    max_rejections: int = 3                           # task.ack rejected this often -> treat as AGENT_UNAVAILABLE

    def __post_init__(self) -> None:
        if not self.retry_delays_s:
            raise ValueError("retry_delays_s must not be empty")
        if self.max_retries < 0 or self.retry_jitter < 0 or self.ack_timeout_s <= 0 or self.offline_grace_s < 0:
            raise ValueError("invalid manager config")
