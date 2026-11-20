"""Job timeouts: a job that runs longer than its timeout (minutes) is killed."""


def job_timed_out(started: float, now: float, timeout_minutes: int) -> bool:
    return now - started > timeout_minutes * 60
