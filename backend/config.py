from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str = "postgresql://localhost:5432/lalaland"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "granite4.2:4b"
    ollama_timeout_seconds: int = 120
    schedule_hour: int = 6
    schedule_minute: int = 0
    schedule_timezone: str = "local"
    app_title: str = "Research Briefing"
    service_name: str = "research-briefing"
    frontend_dir: Path = Path(__file__).resolve().parent.parent / "frontend"
    corpus_model: str = "gemma4:e4b"
    corpus_ollama_timeout_seconds: int = 300
    corpus_final_timeout_seconds: int = 900
    corpus_schedule_hour: int = 3
    corpus_end_hour: int = 5
    corpus_schedule_timezone: str = "America/Detroit"
    temporal_address: str = "host.docker.internal:30733"
    temporal_namespace: str = "lalaland"


def load_settings() -> Settings:
    """Apply environment overrides to the defaults declared on Settings."""
    defaults = Settings()
    return replace(
        defaults,
        database_url=os.getenv("DATABASE_URL", defaults.database_url),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", defaults.ollama_base_url),
        ollama_model=os.getenv("OLLAMA_MODEL", defaults.ollama_model),
        ollama_timeout_seconds=int(os.getenv(
            "OLLAMA_TIMEOUT_SECONDS", str(defaults.ollama_timeout_seconds)
        )),
        schedule_hour=int(os.getenv("SCHEDULE_HOUR", str(defaults.schedule_hour))),
        schedule_minute=int(os.getenv("SCHEDULE_MINUTE", str(defaults.schedule_minute))),
        schedule_timezone=os.getenv("SCHEDULE_TIMEZONE", defaults.schedule_timezone),
        app_title=os.getenv("APP_TITLE", defaults.app_title),
        service_name=os.getenv("OTEL_SERVICE_NAME", defaults.service_name),
        corpus_model=os.getenv("CORPUS_MODEL", defaults.corpus_model),
        corpus_ollama_timeout_seconds=int(os.getenv(
            "CORPUS_OLLAMA_TIMEOUT_SECONDS", str(defaults.corpus_ollama_timeout_seconds)
        )),
        corpus_final_timeout_seconds=int(os.getenv(
            "CORPUS_FINAL_TIMEOUT_SECONDS", str(defaults.corpus_final_timeout_seconds)
        )),
        corpus_schedule_hour=int(os.getenv(
            "CORPUS_SCHEDULE_HOUR", str(defaults.corpus_schedule_hour)
        )),
        corpus_end_hour=int(os.getenv("CORPUS_END_HOUR", str(defaults.corpus_end_hour))),
        corpus_schedule_timezone=os.getenv(
            "CORPUS_SCHEDULE_TIMEZONE", defaults.corpus_schedule_timezone
        ),
        temporal_address=os.getenv("TEMPORAL_ADDRESS", defaults.temporal_address),
        temporal_namespace=os.getenv("TEMPORAL_NAMESPACE", defaults.temporal_namespace),
    )
