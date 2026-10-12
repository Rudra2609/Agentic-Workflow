"""Composition root: builds the whole platform in one process.

    system = HmapSystem.in_memory(artifact_root=tmp_path)        # tests: in-memory bus + stores
    system = HmapSystem.from_settings(Settings.from_env())       # HMAP_BUS=memory|rabbitmq, HMAP_STORE=memory|postgres
    await system.start(with_agents=True)
    ...
    await system.stop()

The Manager, agents, API and pipeline are identical in both set-ups; only the adapters behind the interfaces change.
"""

import asyncio
import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hmap.core.bus.base import Bus
from hmap.core.bus.inbox import InMemoryInboxStore
from hmap.core.bus.memory import InMemoryBus
from hmap.core.bus.outbox import InMemoryOutboxStore, OutboxPublisher
from hmap.core.bus.stores import InboxStore, OutboxStore
from hmap.core.config import Settings
from hmap.core.llm.base import LLMClient
from hmap.core.plugins import Plugin
from hmap.core.runtime.discovery import discover
from hmap.core.runtime.host import AgentHost, HostDeps
from hmap.core.tracing import get_logger
from hmap.manager.config import ManagerConfig
from hmap.manager.manager import Manager
from hmap.manager.store import InMemoryTaskStore, TaskStore
from hmap.services.artifact.base import ArtifactStore
from hmap.services.artifact.local import LocalFSArtifactStore
from hmap.services.artifact.memory import InMemoryArtifactStore
from hmap.services.context.base import ContextStore
from hmap.services.context.memory import InMemoryContextStore
from hmap.services.registry.base import Registry
from hmap.services.registry.memory import InMemoryRegistry

log = get_logger("hmap.system")


@dataclass
class SystemConfig:
    lease_s: float = 30.0
    heartbeat_s: float = 5.0
    watchdog_interval_s: float = 1.0
    outbox_interval_s: float = 0.05
    manager: ManagerConfig = field(default_factory=ManagerConfig)


@dataclass
class Persistence:
    """Everything durable. In memory for tests; Postgres for the demo (``HMAP_STORE=postgres``)."""

    store: TaskStore
    outbox: OutboxStore
    contexts: ContextStore
    registry: Registry
    manager_inbox: InboxStore
    agent_inbox: InboxStore
    accounts: Any = None      # hmap.services.accounts AccountStore (users, sessions, reset tokens)
    db: Any = None            # hmap.db.Database when Postgres is used
    migrate_url: str | None = None


def in_memory_persistence(lease_s: float) -> Persistence:
    from hmap.services.accounts.memory import InMemoryAccountStore

    outbox = InMemoryOutboxStore()
    return Persistence(store=InMemoryTaskStore(outbox), outbox=outbox, contexts=InMemoryContextStore(),
                       registry=InMemoryRegistry(lease_s=lease_s), manager_inbox=InMemoryInboxStore(),
                       agent_inbox=InMemoryInboxStore(), accounts=InMemoryAccountStore())


def postgres_persistence(database_url: str, lease_s: float) -> Persistence:
    from hmap.core.bus.pg_stores import PostgresInboxStore
    from hmap.db import Database
    from hmap.manager.pg_store import PostgresTaskStore
    from hmap.services.accounts.pg import PostgresAccountStore
    from hmap.services.context.pg import PostgresContextStore
    from hmap.services.registry.pg import PostgresRegistry

    db = Database(database_url)
    store = PostgresTaskStore(db)     # local_lock=True: one Manager per database (see design.md)
    return Persistence(store=store, outbox=store.outbox, contexts=PostgresContextStore(db),
                       registry=PostgresRegistry(db, lease_s=lease_s), manager_inbox=PostgresInboxStore(db),
                       agent_inbox=PostgresInboxStore(db), accounts=PostgresAccountStore(db), db=db,
                       migrate_url=database_url)


class HmapSystem:
    def __init__(self, *, bus: Bus, artifacts: ArtifactStore, llm: LLMClient, plugins: list[Plugin],
                 config: SystemConfig | None = None, persistence: Persistence | None = None) -> None:
        self.config = config or SystemConfig()
        self.bus = bus
        self.artifacts = artifacts
        self.llm = llm
        self.plugins = plugins
        self.persistence = persistence or in_memory_persistence(self.config.lease_s)
        p = self.persistence
        self.store, self.outbox, self.contexts, self.registry = p.store, p.outbox, p.contexts, p.registry
        if p.accounts is None:
            from hmap.services.accounts.memory import InMemoryAccountStore

            p.accounts = InMemoryAccountStore()
        self.accounts = p.accounts
        self.manager = Manager(bus=bus, store=self.store, outbox=self.outbox, registry=self.registry,
                               artifacts=artifacts, contexts=self.contexts, plugins=plugins,
                               config=self.config.manager, inbox=p.manager_inbox)
        self.publisher = OutboxPublisher(self.outbox, bus)
        self.host: AgentHost | None = None
        self._publisher_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ builders

    @classmethod
    def in_memory(cls, *, artifact_root: Path | None = None, llm: LLMClient | None = None,
                  plugins: list[Plugin] | None = None, config: SystemConfig | None = None) -> "HmapSystem":
        from hmap.core.llm import FakeLLM

        artifacts: ArtifactStore = LocalFSArtifactStore(artifact_root) if artifact_root else InMemoryArtifactStore()
        return cls(bus=InMemoryBus(), artifacts=artifacts, llm=llm or FakeLLM(),
                   plugins=plugins if plugins is not None else discover(), config=config)

    @classmethod
    def from_settings(cls, settings: Settings, *, config: SystemConfig | None = None,
                      rabbit_namespace: str = "", plugins: list[Plugin] | None = None) -> "HmapSystem":
        from hmap.core.llm import build_llm

        cfg = config or SystemConfig()
        bus: Bus
        if settings.bus == "rabbitmq":
            from hmap.core.bus.rabbitmq import RabbitBus

            bus = RabbitBus(settings.rabbitmq_url, namespace=rabbit_namespace, connection_name="hmap-platform")
        else:
            bus = InMemoryBus()
        persistence = (postgres_persistence(settings.database_url, cfg.lease_s) if settings.store == "postgres"
                       else in_memory_persistence(cfg.lease_s))
        return cls(bus=bus, artifacts=LocalFSArtifactStore(settings.artifact_root), llm=build_llm(settings),
                   plugins=plugins if plugins is not None else discover(settings.enabled_plugins()),
                   config=cfg, persistence=persistence)

    # ------------------------------------------------------------------ lifecycle

    async def start(self, *, with_agents: bool = True, migrate: bool = True) -> None:
        if self.persistence.migrate_url and migrate:
            from hmap.db import upgrade_async

            await upgrade_async(self.persistence.migrate_url)   # migrations-on-start (idempotent)
            log.info("database migrated", url=self.persistence.migrate_url.split("@")[-1])
        await self.bus.start()
        await self.manager.start(watchdog_interval_s=self.config.watchdog_interval_s)
        self._publisher_task = asyncio.create_task(self.publisher.run_forever(self.config.outbox_interval_s))
        if with_agents:
            await self.start_agents()

    async def start_agents(self, plugins: list[Plugin] | None = None) -> AgentHost:
        deps = HostDeps(bus=self.bus, llm=self.llm, artifacts=self.artifacts, contexts=self.contexts,
                        inbox=self.persistence.agent_inbox, owns_bus=False)
        self.host = AgentHost(plugins if plugins is not None else self.plugins, deps,
                              heartbeat_s=self.config.heartbeat_s)
        await self.host.start()
        return self.host

    async def stop(self) -> None:
        if self.host is not None:
            await self.host.stop()
        await self.manager.stop()
        self.publisher.stop()
        if self._publisher_task is not None:
            self._publisher_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._publisher_task
        with contextlib.suppress(Exception):
            await self.publisher.run_once()   # final drain
        await self.bus.close()
        if self.persistence.db is not None:
            await self.persistence.db.close()
