import pytest

from hmap.core.contracts import DomainEvent, ExecutionStatus, TaskState
from hmap.manager import (
    ConcurrencyConflict,
    ExecutionRecord,
    InMemoryTaskStore,
    ProjectRecord,
    RecordNotFound,
    TaskRecord,
    UniqueViolation,
)
from tests.manager.fakes import T0, FakeOutbox


def _task(task_id: str = "T-1") -> TaskRecord:
    return TaskRecord(task_id=task_id, project_id="P-1", capability="echo", objective="x", created_at=T0,
                      updated_at=T0)


def _exe(execution_id: str, attempt: int, task_id: str = "T-1") -> ExecutionRecord:
    return ExecutionRecord(execution_id=execution_id, task_id=task_id, attempt=attempt, created_at=T0, updated_at=T0)


def _event(task_id: str = "T-1", version: int = 1) -> DomainEvent:
    return DomainEvent(event_type="task.created", aggregate_id=task_id, aggregate_version=version)


@pytest.fixture
def outbox() -> FakeOutbox:
    return FakeOutbox()


@pytest.fixture
def store(outbox: FakeOutbox) -> InMemoryTaskStore:
    return InMemoryTaskStore(outbox)


async def test_state_change_and_event_commit_together(store: InMemoryTaskStore, outbox: FakeOutbox) -> None:
    async with store.transaction() as tx:
        await tx.insert_task(_task())
        await tx.add_event(_event())
        assert await store.get_task("T-1") is None          # not visible outside before commit
        assert (await tx.get_task("T-1")) is not None       # tx sees its own writes
        assert outbox.rows == []
    assert (await store.get_task("T-1")) is not None
    assert [r.kind for r in outbox.rows] == ["event"]


async def test_exception_rolls_back_state_and_outbox(store: InMemoryTaskStore, outbox: FakeOutbox) -> None:
    with pytest.raises(RuntimeError):
        async with store.transaction() as tx:
            await tx.insert_task(_task())
            await tx.add_event(_event())
            raise RuntimeError("boom")
    assert await store.get_task("T-1") is None
    assert outbox.rows == []


async def test_cas_conflict(store: InMemoryTaskStore) -> None:
    async with store.transaction() as tx:
        await tx.insert_task(_task())
    stale = await store.get_task("T-1")
    assert stale is not None and stale.state_version == 1
    async with store.transaction() as tx:
        saved = await tx.update_task(stale.model_copy(update={"state": TaskState.READY}), expected_version=1)
    assert saved.state_version == 2
    with pytest.raises(ConcurrencyConflict):
        async with store.transaction() as tx:
            await tx.update_task(stale.model_copy(update={"state": TaskState.CANCELLED}), expected_version=1)
    current = await store.get_task("T-1")
    assert current is not None and current.state == TaskState.READY and current.state_version == 2


async def test_update_missing_record(store: InMemoryTaskStore) -> None:
    with pytest.raises(RecordNotFound):
        async with store.transaction() as tx:
            await tx.update_task(_task("T-404"), expected_version=1)


async def test_unique_task_attempt(store: InMemoryTaskStore) -> None:
    async with store.transaction() as tx:
        await tx.insert_task(_task())
        await tx.insert_execution(_exe("E-1", 1))
    with pytest.raises(UniqueViolation):
        async with store.transaction() as tx:
            await tx.insert_execution(_exe("E-2", 1))
    with pytest.raises(UniqueViolation):
        async with store.transaction() as tx:
            await tx.insert_execution(_exe("E-1", 2))
    async with store.transaction() as tx:
        await tx.insert_execution(_exe("E-2", 2))
    assert [e.attempt for e in await store.list_executions(task_id="T-1")] == [1, 2]


async def test_unique_ids(store: InMemoryTaskStore) -> None:
    now = T0
    async with store.transaction() as tx:
        await tx.insert_task(_task())
        await tx.insert_project(ProjectRecord(project_id="P-1", name="p", created_at=now, updated_at=now))
    with pytest.raises(UniqueViolation):
        async with store.transaction() as tx:
            await tx.insert_task(_task())
    with pytest.raises(UniqueViolation):
        async with store.transaction() as tx:
            await tx.insert_project(ProjectRecord(project_id="P-1", name="q", created_at=now, updated_at=now))


async def test_reads_return_copies(store: InMemoryTaskStore) -> None:
    async with store.transaction() as tx:
        await tx.insert_task(_task())
        await tx.insert_execution(_exe("E-1", 1))
    t = await store.get_task("T-1")
    assert t is not None
    t.state = TaskState.COMPLETED
    t.inputs["x"] = 1
    again = await store.get_task("T-1")
    assert again is not None and again.state == TaskState.CREATED and again.inputs == {}


async def test_list_filters(store: InMemoryTaskStore) -> None:
    async with store.transaction() as tx:
        await tx.insert_task(_task("T-1"))
        await tx.insert_task(_task("T-2").model_copy(update={"state": TaskState.READY}))
        await tx.insert_execution(_exe("E-1", 1).model_copy(update={"agent_id": "a", "status": ExecutionStatus.ACTIVE}))
    assert [t.task_id for t in await store.list_tasks(states={TaskState.READY})] == ["T-2"]
    assert [t.task_id for t in await store.list_tasks(project_id="P-1")] == ["T-1", "T-2"]
    assert len(await store.list_executions(agent_id="a", statuses={ExecutionStatus.ACTIVE})) == 1
    assert await store.list_executions(agent_id="b") == []
