"""Settings read from the environment (see /.env.example). One place, so nothing reads os.environ ad hoc."""

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator

# Repository root (backend/src/hmap/core/config.py -> four levels up). Relative paths in settings are resolved
# against it, so `make api` (run from backend/), `make agents` and scripts run from the root all agree.
REPO_ROOT = Path(os.environ.get("HMAP_ROOT") or Path(__file__).resolve().parents[4])

LLMMode = Literal["live", "record", "replay", "fake"]
LLM_ROLES = ("fast", "reasoner", "coder", "judge", "embed", "classify")
# Roles that may be sent to a cloud chat model (``embed`` always stays local; ``vision`` is cloud-only: image reading
# such as OCR of scanned pages, with no local fallback model).
CLOUD_CHAT_ROLES = ("fast", "reasoner", "coder", "judge", "classify", "vision")
# Cloud providers known to ``HMAP_CLOUD_ROLE_MAP``. ``cloud`` is the deprecated single legacy provider
# (``HMAP_CLOUD_BASE_URL`` + ``HMAP_CLOUD_API_KEY``).
CLOUD_PROVIDERS = ("groq", "gemini", "cloud")

CloudRoute = tuple[str, str]  # (provider, model)

# Used when HMAP_CLOUD_ROLE_MAP is unset or empty; ``none`` turns the key pool off (doc 02 §2.5). Each provider rate-
# limits per model, so the roles are spread over different models. Quality roles go to the strongest free model;
# the judge uses a model family that neither the reasoner nor the coder uses. fast/classify go to small, quick
# models; vision (scanned pages) goes to Gemini, the only provider here whose free models read images. Without keys
# for a provider its routes are dropped, and every role falls back to the local model (vision has no local model).
# Checked on both free tiers on 2026-10-12 (gemini-3.8-flash and gemini-flash-latest were left out: they kept
# answering 503 "overloaded"; the Pro models have no free quota).
DEFAULT_CLOUD_ROLE_MAP = (
    "reasoner=gemini:gemini-3.6-flash|groq:openai/gpt-oss-120b|gemini:gemini-3.5-flash,"
    "coder=groq:openai/gpt-oss-120b|gemini:gemini-3.6-flash|gemini:gemini-3.5-flash,"
    "judge=groq:qwen/qwen3.8-27b|gemini:gemini-3.5-flash,"
    "fast=groq:openai/gpt-oss-20b|gemini:gemini-3.5-flash-lite,"
    "classify=groq:openai/gpt-oss-20b|gemini:gemini-3.5-flash-lite,"
    "vision=gemini:gemini-3.6-flash|gemini:gemini-3.5-flash"
)


def read_env_file(path: Path) -> dict[str, str]:
    """Minimal reader for the local ``.env`` (KEY=VALUE lines, ``#`` comments, optional ``export`` and quotes).

    Unquoted values end at `` #`` so the inline comments copied from ``.env.example`` are dropped. Malformed lines are
    skipped silently: never echo a line, it may hold a key."""
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").strip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key.replace("_", "").isalnum():
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = "" if value.startswith("#") else value.split(" #", 1)[0].split("\t#", 1)[0].strip()
        out[key] = value
    return out


def env_file_values() -> dict[str, str]:
    """Values from ``<repo>/.env`` (or ``HMAP_ENV_FILE``; ``none`` disables it — the test suite does)."""
    target = os.environ.get("HMAP_ENV_FILE", "")
    if target.lower() == "none":
        return {}
    return read_env_file(Path(target) if target else REPO_ROOT / ".env")


def parse_role_map(raw: str) -> dict[str, str]:
    """``"reasoner=qwen3.5:9b,embed=nomic-embed-text"`` -> ``{"reasoner": "qwen3.5:9b", ...}``."""
    out: dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        role, sep, model = part.partition("=")
        if not sep or not role.strip() or not model.strip():
            raise ValueError(f"bad HMAP_ROLE_MAP entry: {part!r}")
        out[role.strip()] = model.strip()
    return out


def parse_key_list(raw: str | None) -> list[str]:
    """``"k1, k2,,"`` -> ``["k1", "k2"]`` (blanks ignored, duplicates dropped keeping the first)."""
    out: list[str] = []
    for part in (raw or "").split(","):
        key = part.strip()
        if key and key not in out:
            out.append(key)
    return out


def parse_cloud_role_map(raw: str, providers: tuple[str, ...] = CLOUD_PROVIDERS) -> dict[str, list[CloudRoute]]:
    """``"coder=groq:<model>|gemini:<model>,reasoner=gemini:<model>"`` -> ``{"coder": [("groq", m), ("gemini", m)],
    ...}``; ``none``/``off``/``local`` -> ``{}`` (every role local). Errors name the entry by position and never echo
    its text (a mistyped value could be a pasted key)."""
    out: dict[str, list[CloudRoute]] = {}
    if raw.strip().lower() in ("none", "off", "local"):
        return out
    for idx, part in enumerate((p.strip() for p in raw.split(",")), start=1):
        if not part:
            continue
        where = f"HMAP_CLOUD_ROLE_MAP entry #{idx}"
        role, sep, chain = part.partition("=")
        role = role.strip()
        if not sep or not role or not chain.strip():
            raise ValueError(f"{where}: expected role=provider:model[|provider:model...]")
        if role not in CLOUD_CHAT_ROLES:
            raise ValueError(f"{where}: unknown or non-chat role (expected one of {', '.join(CLOUD_CHAT_ROLES)})")
        if role in out:
            raise ValueError(f"{where}: role {role!r} is listed twice")
        routes: list[CloudRoute] = []
        for hop, step in enumerate((s.strip() for s in chain.split("|")), start=1):
            provider, sep2, model = step.partition(":")
            provider, model = provider.strip().lower(), model.strip()
            if not sep2 or not provider or not model:
                raise ValueError(f"{where} (role {role!r}), provider #{hop}: expected provider:model")
            if provider not in providers:
                raise ValueError(f"{where} (role {role!r}), provider #{hop}: unknown provider "
                                 f"(expected one of {', '.join(providers)})")
            if (provider, model) not in routes:
                routes.append((provider, model))
        out[role] = routes
    return out


class Settings(BaseModel):
    env: str = "dev"
    log_level: str = "INFO"
    log_json: bool = True
    bus: Literal["memory", "rabbitmq"] = "memory"
    store: Literal["memory", "postgres"] = "memory"
    rabbitmq_url: str = "amqp://hmap:hmap@127.0.0.1:5672/"
    database_url: str = "postgresql+psycopg://hmap:hmap@127.0.0.1:5433/hmap"
    artifact_root: Path = Field(default=Path("data/artifacts"), validate_default=True)
    plugins: str = "all"
    llm_mode: LLMMode = "replay"
    llm_cache_dir: Path = Field(default=Path("samples/llm_cache"), validate_default=True)
    role_map: dict[str, str] = Field(default_factory=dict)
    ollama_base_url: str = "http://127.0.0.1:11434"
    # context window sent to Ollama (its server default is 4096: too small for a 3K-token prompt plus the answer)
    ollama_num_ctx: int | None = 8192
    llm_max_concurrency: int = 1
    # replay mode only: plug-ins whose MISSING answers are fetched live and recorded (``all`` = every plug-in); the
    # others stay strict replay. For filling in a new plug-in's recordings without re-recording anyone else's.
    llm_record_missing: frozenset[str] = Field(default_factory=frozenset)
    # --- planning (Sprint 3) and demos ---
    plan_max_parallel: int = Field(default=4, ge=1, description="graph steps of one project that may run at once")
    stub_delay_s: float = Field(default=0.0, ge=0, description="minimum simulated work per stub step (demos)")
    retry_delays_s: tuple[float, ...] | None = Field(default=None, description="Manager backoff per retry "
                                                     "(HMAP_RETRY_DELAYS_S=5,30,120); unset = the default")
    # --- refinement and observability (Sprint 4, Member 4) ---
    refine_default: bool = Field(default=False, description="new projects check and improve results (refine=true)")
    otel_endpoint: str | None = Field(default=None, description="OTLP/HTTP base URL (Jaeger), e.g. "
                                                               "http://127.0.0.1:4318; unset = no traces")
    metrics_port: int = Field(default=9464, ge=0, le=65535, description="/metrics port of the agents process; 0 = off")
    metrics_interval_s: float = Field(default=5.0, gt=0, description="how often the metric gauges are refreshed")
    jaeger_url: str = Field(default="http://127.0.0.1:16686", description="Jaeger UI (links from the Ops page)")
    grafana_url: str = Field(default="http://127.0.0.1:3001", description="Grafana (links from the Ops page)")
    prometheus_url: str = Field(default="http://127.0.0.1:9090", description="Prometheus (alerts, links)")
    # --- autonomous research (Sprint 5, Member 5) ---
    research_mode: Literal["online", "cached", "local"] = Field(
        default="cached", description="online = live search + fetch (cached on disk); cached = cache + offline corpus "
                                      "only, never the network; local = the local corpus only")
    research_providers: tuple[str, ...] = Field(default=("wikipedia", "arxiv", "ddg", "local"),
                                                description="search providers in order (HMAP_RESEARCH_PROVIDERS)")
    research_cache_dir: Path = Field(default=REPO_ROOT / "data" / "research_cache",
                                     description="fetched pages + search results (git-ignored)")
    research_max_fetch_mb: float = Field(default=5.0, gt=0, description="largest page / PDF fetched")
    research_rate_per_host: float = Field(default=1.0, gt=0, description="requests per second per host")
    # --- research verification (Sprint 6, Member 6) ---
    verify_max_rounds: int = Field(default=1, ge=0, le=3, description="follow-up research rounds after a verification "
                                                                     "flags claims (0 = never)")
    verify_independent: bool = Field(default=True, description="L3/L4: own searches + cross-source check")
    verify_cache_dir: Path = Field(default=REPO_ROOT / "data" / "verify_cache",
                                   description="the verifier's own search results (git-ignored)")
    # --- security layer (Sprint 6, Member 6; hmap.core.policy) ---
    agent_secrets: list[SecretStr] = Field(default_factory=list, repr=False,
                                           description="HMAP_AGENT_SECRETS 'kid:secret,...' (newest first); empty = "
                                                       "dev mode with a per-process seeded secret")
    agent_token_ttl_s: int = Field(default=7 * 24 * 3600, ge=60, description="lifetime of an agent service token")
    security_enforce: bool = Field(default=True, description="deny (not only audit) messages the policy refuses")
    # --- team cloud key pool (doc 02 §2.5, item 1.14b). Keys are SecretStr and hidden from repr/str/dumps.
    groq_api_keys: list[SecretStr] = Field(default_factory=list, repr=False)
    gemini_api_keys: list[SecretStr] = Field(default_factory=list, repr=False)
    groq_base_url: str = "https://api.groq.com/openai/v1"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    cloud_role_map: dict[str, list[CloudRoute]] = Field(
        default_factory=lambda: parse_cloud_role_map(DEFAULT_CLOUD_ROLE_MAP))
    cloud_ok: bool = Field(default=True, description="global switch (HMAP_CLOUD_OK); false keeps every call local")
    # --- accounts (sign-in, sessions, password reset) ---
    public_url: str = Field(default="http://localhost:3000", description="where users open the dashboard (reset links)")
    cookie_secure: bool = Field(default=False, description="Secure flag on cookies; true whenever served over HTTPS")
    session_days: float = 14.0
    allow_registration: bool = True
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = Field(default=None, repr=False)
    smtp_from: str = "HMAP <no-reply@localhost>"
    smtp_starttls: bool = True
    # DEPRECATED single cloud provider (named ``cloud``); prefer the key pool above. Still honoured.
    cloud_base_url: str | None = None
    cloud_api_key: str | None = Field(default=None, repr=False)

    @field_validator("artifact_root", "llm_cache_dir", "research_cache_dir", "verify_cache_dir")
    @classmethod
    def _anchor_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else (REPO_ROOT / value).resolve()

    @field_validator("groq_api_keys", "gemini_api_keys", mode="before")
    @classmethod
    def _split_keys(cls, value: object) -> object:
        return parse_key_list(value) if isinstance(value, str) else value

    @field_validator("cloud_role_map", mode="before")
    @classmethod
    def _parse_cloud_role_map(cls, value: object) -> object:
        return parse_cloud_role_map(value) if isinstance(value, str) else value

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        # real environment variables win over the local .env file; an explicit ``env`` dict ignores both
        e = {**env_file_values(), **os.environ} if env is None else dict(env)

        def get(key: str) -> str | None:
            value = e.get(key)
            return value if value not in (None, "") else None

        data: dict[str, object] = {}
        mapping = {
            "HMAP_ENV": "env", "HMAP_LOG_LEVEL": "log_level", "HMAP_BUS": "bus",
            "HMAP_RABBITMQ_URL": "rabbitmq_url", "HMAP_STORE": "store", "HMAP_DATABASE_URL": "database_url",
            "HMAP_ARTIFACT_ROOT": "artifact_root", "HMAP_PLUGINS": "plugins", "HMAP_LLM_MODE": "llm_mode",
            "HMAP_LLM_CACHE_DIR": "llm_cache_dir", "OLLAMA_BASE_URL": "ollama_base_url",
            "HMAP_LLM_MAX_CONCURRENCY": "llm_max_concurrency", "HMAP_OLLAMA_NUM_CTX": "ollama_num_ctx",
            "HMAP_PLAN_MAX_PARALLEL": "plan_max_parallel", "HMAP_STUB_DELAY_S": "stub_delay_s",
            "HMAP_OTEL_ENDPOINT": "otel_endpoint", "HMAP_METRICS_PORT": "metrics_port",
            "HMAP_METRICS_INTERVAL_S": "metrics_interval_s", "HMAP_JAEGER_URL": "jaeger_url",
            "HMAP_GRAFANA_URL": "grafana_url", "HMAP_PROMETHEUS_URL": "prometheus_url",
            "HMAP_RESEARCH_MODE": "research_mode", "HMAP_RESEARCH_CACHE_DIR": "research_cache_dir",
            "HMAP_RESEARCH_MAX_FETCH_MB": "research_max_fetch_mb",
            "HMAP_RESEARCH_RATE_PER_HOST": "research_rate_per_host",
            "HMAP_VERIFY_MAX_ROUNDS": "verify_max_rounds", "HMAP_VERIFY_CACHE_DIR": "verify_cache_dir",
            "HMAP_AGENT_TOKEN_TTL_S": "agent_token_ttl_s",
            "HMAP_CLOUD_BASE_URL": "cloud_base_url",
            "HMAP_CLOUD_API_KEY": "cloud_api_key", "HMAP_GROQ_BASE_URL": "groq_base_url",
            "HMAP_GEMINI_BASE_URL": "gemini_base_url", "HMAP_PUBLIC_URL": "public_url",
            "HMAP_SESSION_DAYS": "session_days", "HMAP_SMTP_HOST": "smtp_host", "HMAP_SMTP_PORT": "smtp_port",
            "HMAP_SMTP_USERNAME": "smtp_username", "HMAP_SMTP_PASSWORD": "smtp_password", "HMAP_SMTP_FROM": "smtp_from",
        }
        for key, field in mapping.items():
            value = get(key)
            if value is not None:
                data[field] = value
        if (value := get("HMAP_LOG_JSON")) is not None:
            data["log_json"] = value.lower() in ("1", "true", "yes")
        for key, field in (("HMAP_COOKIE_SECURE", "cookie_secure"), ("HMAP_ALLOW_REGISTRATION", "allow_registration"),
                           ("HMAP_SMTP_STARTTLS", "smtp_starttls")):
            if (value := get(key)) is not None:
                data[field] = value.strip().lower() in ("1", "true", "yes", "on")
        if (value := get("HMAP_REFINE_DEFAULT")) is not None:
            data["refine_default"] = value.strip().lower() in ("1", "true", "yes", "on")
        for key, field in (("HMAP_VERIFY_INDEPENDENT", "verify_independent"),
                           ("HMAP_SECURITY_ENFORCE", "security_enforce")):
            if (value := get(key)) is not None:
                data[field] = value.strip().lower() in ("1", "true", "yes", "on")
        if (value := get("HMAP_AGENT_SECRETS")) is not None:
            data["agent_secrets"] = parse_key_list(value)
        if (value := get("HMAP_CLOUD_OK")) is not None:
            data["cloud_ok"] = value.strip().lower() in ("1", "true", "yes", "on")
        if (value := get("HMAP_RETRY_DELAYS_S")) is not None:
            data["retry_delays_s"] = tuple(float(x) for x in value.split(",") if x.strip())
        if (value := get("HMAP_RESEARCH_PROVIDERS")) is not None:
            data["research_providers"] = tuple(p.strip() for p in value.split(",") if p.strip())
        if (value := get("HMAP_LLM_RECORD_MISSING")) is not None:
            data["llm_record_missing"] = frozenset(p.strip() for p in value.split(",") if p.strip())
        if (value := get("HMAP_ROLE_MAP")) is not None:
            data["role_map"] = parse_role_map(value)
        if (value := get("HMAP_CLOUD_ROLE_MAP")) is not None:
            data["cloud_role_map"] = parse_cloud_role_map(value)
        data["groq_api_keys"] = parse_key_list(get("HMAP_GROQ_API_KEYS"))
        data["gemini_api_keys"] = parse_key_list(get("HMAP_GEMINI_API_KEYS"))
        return cls.model_validate(data)

    def cloud_keys(self, provider: str) -> list[str]:
        """The raw keys for ``provider`` (``groq`` | ``gemini`` | legacy ``cloud``). Never log the result."""
        if provider == "groq":
            return [k.get_secret_value() for k in self.groq_api_keys]
        if provider == "gemini":
            return [k.get_secret_value() for k in self.gemini_api_keys]
        if provider == "cloud":
            return [self.cloud_api_key] if self.cloud_api_key and self.cloud_base_url else []
        return []

    def cloud_base_url_for(self, provider: str) -> str | None:
        return {"groq": self.groq_base_url, "gemini": self.gemini_base_url,
                "cloud": self.cloud_base_url}.get(provider)

    def enabled_plugins(self) -> set[str] | None:
        """``None`` means every discovered plug-in."""
        if self.plugins.strip().lower() == "all":
            return None
        return {p.strip() for p in self.plugins.split(",") if p.strip()}
