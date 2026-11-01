"""Runtime configuration. Everything is env-overridable; defaults run offline.

A `.env` is loaded from (in order) $WASIGNAL_ENV_FILE, the repo root, and
`apps/api/`. Real environment variables always win over the file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _candidate in (
    os.getenv("WASIGNAL_ENV_FILE"),
    _REPO_ROOT / ".env",
    _REPO_ROOT / "apps" / "api" / ".env",
):
    if _candidate and Path(_candidate).is_file():
        load_dotenv(Path(_candidate), override=False)


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw is None or raw.strip() == "" else int(raw)


_OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
_DEFAULT_PROVIDER = os.getenv("WASIGNAL_LLM_PROVIDER", "").strip() or (
    "openrouter" if _OPENROUTER_KEY else "echo"
)



@dataclass(frozen=True)
class Settings:
    app_name: str = "Wasignal API"
    env: str = os.getenv("WASIGNAL_ENV", "dev")
    data_dir: Path = Path(os.getenv("WASIGNAL_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
    db_path: Path = field(init=False)

    # auth
    session_cookie: str = os.getenv("WASIGNAL_SESSION_COOKIE", "ws_session")
    session_ttl_seconds: int = _int("WASIGNAL_SESSION_TTL", 7 * 24 * 3600)
    cookie_domain: str = os.getenv("WASIGNAL_COOKIE_DOMAIN", "")
    cookie_same_site: str = os.getenv("WASIGNAL_COOKIE_SAMESITE", "lax").lower()
    cookie_secure: bool = _bool("WASIGNAL_COOKIE_SECURE", os.getenv("WASIGNAL_ENV", "dev") != "dev")
    dev_otp: str = os.getenv("WASIGNAL_DEV_OTP", "123456")
    otp_ttl_seconds: int = _int("WASIGNAL_OTP_TTL", 300)

    # browser origins allowed to call this API directly (split deployment)
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv(
            "WASIGNAL_CORS_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000",
        ).split(",")
        if origin.strip()
    )

    # llm: "echo" (offline, deterministic), "openrouter", or "openai" (any compatible endpoint)
    llm_provider: str = _DEFAULT_PROVIDER
    llm_model: str = os.getenv("WASIGNAL_LLM_MODEL", "openai/gpt-4o-mini")
    llm_base_url: str = os.getenv("WASIGNAL_LLM_BASE_URL", "https://api.openai.com/v1")
    llm_api_key: str = os.getenv("WASIGNAL_LLM_API_KEY", "")

    # OpenRouter (https://openrouter.ai): one key, every model
    openrouter_key: str = _OPENROUTER_KEY
    openrouter_base_url: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    openrouter_referer: str = os.getenv("OPENROUTER_HTTP_REFERER", "http://localhost:3000")
    openrouter_title: str = os.getenv("OPENROUTER_X_TITLE", "Wasignal")
    model_cache_seconds: int = _int("WASIGNAL_MODEL_CACHE_SECONDS", 900)

    # storage: mongo is selected automatically when MONGODB_URI is present
    db_backend: str = (os.getenv("WASIGNAL_DB_BACKEND") or (
        "mongo" if os.getenv("MONGODB_URI") else "sqlite"
    )).strip().lower()
    mongodb_uri: str = os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017")
    mongodb_db: str = os.getenv("MONGODB_DB", "wasignal")
    mongomock: bool = _bool("WASIGNAL_MONGOMOCK", False)
    redis_url: str = os.getenv("REDIS_URL", "").strip()
    fakeredis: bool = _bool("WASIGNAL_FAKEREDIS", False)


    # channel: "stub" (in-memory outbox) or "meta" (Cloud API)
    channel: str = os.getenv("WASIGNAL_CHANNEL", "stub")
    meta_token: str = os.getenv("WASIGNAL_META_TOKEN", "")
    meta_phone_number_id: str = os.getenv("WASIGNAL_META_PHONE_NUMBER_ID", "")
    meta_verify_token: str = os.getenv("WASIGNAL_META_VERIFY_TOKEN", "wasignal-verify")

    # behaviour
    human_active_pause_seconds: int = _int("WASIGNAL_HUMAN_PAUSE_SECONDS", 600)
    history_limit: int = _int("WASIGNAL_HISTORY_LIMIT", 30)
    tick_seconds: int = _int("WASIGNAL_TICK_SECONDS", 15)
    scheduler_enabled: bool = _bool("WASIGNAL_SCHEDULER", True)
    seed_demo: bool = _bool("WASIGNAL_SEED_DEMO", True)

    def __post_init__(self) -> None:
        object.__setattr__(self, "db_path", self.data_dir / "wasignal.db")


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
