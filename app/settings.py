from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
DATA_DIR = Path(os.getenv("VDP_DATA_DIR", BASE_DIR / "data")).resolve()
DOWNLOAD_DIR = DATA_DIR / "downloads"


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = "Video Downloader Plus"
    app_env: str = os.getenv("APP_ENV", "development")
    max_file_mb: int = _int("MAX_FILE_MB", 2048)
    max_duration_seconds: int = _int("MAX_DURATION_SECONDS", 14400)
    max_concurrent_jobs: int = _int("MAX_CONCURRENT_JOBS", 2)
    job_ttl_minutes: int = _int("JOB_TTL_MINUTES", 30)
    info_cache_minutes: int = _int("INFO_CACHE_MINUTES", 10)
    analyze_rate_per_minute: int = _int("ANALYZE_RATE_PER_MINUTE", 20)
    download_rate_per_minute: int = _int("DOWNLOAD_RATE_PER_MINUTE", 8)
    trust_proxy_headers: bool = _bool("TRUST_PROXY_HEADERS", False)
    allow_playlists: bool = _bool("ALLOW_PLAYLISTS", False)
    enable_node_runtime: bool = _bool("ENABLE_NODE_RUNTIME", True)
    enable_deno_runtime: bool = _bool("ENABLE_DENO_RUNTIME", True)


settings = Settings()
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
