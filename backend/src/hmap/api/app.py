"""FastAPI application (Sprint 1 item 1.15).

    uv run uvicorn hmap.api.app:create_app --factory --reload --port 8000

Runs the Manager, bus and (optionally) all agents inside the API process (``HMAP_RUN_AGENTS=true``), so one command
gives a working platform. Member routers are mounted automatically at ``/api/<plugin>`` and require a signed-in
user (plug-ins must still check project ownership for project-scoped data: ``hmap.api.routers.projects.owned_project``).

The dashboard reaches the API through the Next.js server (``/api`` is proxied), so session cookies are first-party;
the live WebSocket connects to the API directly with a single-use ticket.
"""

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from hmap.api.deps import SESSION_COOKIE, client_address, current_session
from hmap.api.feed import EventFeed
from hmap.api.routers import auth, projects, system
from hmap.core import policy
from hmap.core.config import REPO_ROOT, Settings
from hmap.core.tracing import configure_logging
from hmap.obs import configure as configure_tracing
from hmap.obs import metrics as obs_metrics
from hmap.obs import shutdown as shutdown_tracing
from hmap.services.accounts.mailer import FileMailer, Mailer, SmtpMailer
from hmap.services.accounts.service import AccountService
from hmap.system import HmapSystem


def build_mailer(settings: Settings) -> Mailer:
    if settings.smtp_host:
        return SmtpMailer(settings.smtp_host, settings.smtp_port, settings.smtp_from, username=settings.smtp_username,
                          password=settings.smtp_password, starttls=settings.smtp_starttls)
    return FileMailer(REPO_ROOT / "data" / "dev_mailbox")


def allowed_origins(settings: Settings) -> list[str]:
    origins = {"http://127.0.0.1:3000", "http://localhost:3000", settings.public_url.rstrip("/")}
    return sorted(origins)


def create_app(hmap_system: HmapSystem | None = None, *, run_agents: bool | None = None,
               mailer: Mailer | None = None) -> FastAPI:
    """With no ``hmap_system`` one is built from the environment. Either way the app starts and stops it."""
    settings = Settings.from_env()
    configure_logging(settings.log_level, settings.log_json)
    if run_agents is None:
        run_agents = os.environ.get("HMAP_RUN_AGENTS", "true").lower() in ("1", "true", "yes")
    origins = allowed_origins(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Sprint 4: traces to Jaeger only when HMAP_OTEL_ENDPOINT is set (no-op otherwise)
        configure_tracing(service_name="hmap-api", endpoint=settings.otel_endpoint or "")
        obs_metrics.set_process_name("hmap-api")
        s = hmap_system or HmapSystem.from_settings(settings)
        app.state.system = s
        await s.start(with_agents=run_agents)
        app.state.accounts = AccountService(s.accounts, mailer or build_mailer(settings),
                                            public_url=settings.public_url, session_days=settings.session_days,
                                            allow_registration=settings.allow_registration)
        feed = EventFeed(s.bus)
        if s.persistence.db is not None:
            await feed.preload_from(s.persistence.db)   # history survives restarts (before live events arrive)
        app.state.feed = feed
        await feed.start()
        try:
            yield
        finally:
            await feed.stop()
            await s.stop()
            shutdown_tracing()

    app = FastAPI(title="hmap", version="0.2.0", lifespan=lifespan,
                  description="Hierarchical multi-agent project execution platform (IT-314 Group 23)")
    app.state.settings = settings
    app.state.allowed_origins = origins
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PATCH", "DELETE"],
                       allow_headers=["Content-Type", "X-CSRF-Token"])
    # Sprint 6 (Member 6, item 6.17): a per-client rate limit on state-changing API requests
    app.state.write_limiter = policy.RateLimiter(rate=float(os.environ.get("HMAP_API_WRITE_RATE", "20")),
                                                 burst=int(os.environ.get("HMAP_API_WRITE_BURST", "200")))

    @app.middleware("http")
    async def limit_writes(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.url.path.startswith("/api/"):
            key = f"{client_address(request)}|{policy.fingerprint(request.cookies.get(SESSION_COOKIE, ''))}"
            if not request.app.state.write_limiter.allow(key):
                return JSONResponse({"detail": "Too many requests. Wait a moment and try again."}, status_code=429,
                                    headers={"Retry-After": "1"})
        return await call_next(request)

    app.include_router(auth.router, prefix="/api")
    app.include_router(system.router, prefix="/api")
    app.include_router(projects.router, prefix="/api")
    _mount_plugin_routers(app, hmap_system)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        """Prometheus scrape target (Sprint 4 item 4.17). Counts and durations only: no project, user or text."""
        body, content_type = obs_metrics.exposition()
        return Response(body, media_type=content_type)

    return app


def _mount_plugin_routers(app: FastAPI, hmap_system: HmapSystem | None) -> None:
    from hmap.core.runtime.discovery import discover

    plugins = hmap_system.plugins if hmap_system is not None else discover(Settings.from_env().enabled_plugins())
    for plugin in plugins:
        if plugin.router is not None:
            app.include_router(plugin.router, prefix=f"/api/{plugin.name}", tags=[plugin.name],
                               dependencies=[Depends(current_session)])
