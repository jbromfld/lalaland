from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    ollama_base_url: str
    ollama_model: str
    ollama_timeout_seconds: int
    schedule_hour: int
    schedule_minute: int
    schedule_timezone: str
    app_title: str
    service_name: str
    frontend_dir: Path
    corpus_model: str = "gemma4:e4b"
    corpus_ollama_timeout_seconds: int = 300
    corpus_final_timeout_seconds: int = 900
    corpus_schedule_hour: int = 3
    corpus_end_hour: int = 5
    corpus_schedule_timezone: str = "America/Detroit"


def load_settings() -> Settings:
    backend_dir = Path(__file__).resolve().parent
    project_root = backend_dir.parent

    return Settings(
        database_url=os.getenv("DATABASE_URL", "postgresql://localhost:5432/lalaland"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "granite4.2:4b"),
        ollama_timeout_seconds=int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120")),
        schedule_hour=int(os.getenv("SCHEDULE_HOUR", "6")),
        schedule_minute=int(os.getenv("SCHEDULE_MINUTE", "0")),
        schedule_timezone=os.getenv("SCHEDULE_TIMEZONE", "local"),
        app_title=os.getenv("APP_TITLE", "Research Briefing"),
        service_name=os.getenv("OTEL_SERVICE_NAME", "research-briefing"),
        frontend_dir=project_root / "frontend",
        corpus_model=os.getenv("CORPUS_MODEL", "gemma4:e4b"),
        corpus_ollama_timeout_seconds=int(os.getenv("CORPUS_OLLAMA_TIMEOUT_SECONDS", "300")),
        corpus_final_timeout_seconds=int(os.getenv("CORPUS_FINAL_TIMEOUT_SECONDS", "900")),
        corpus_schedule_hour=int(os.getenv("CORPUS_SCHEDULE_HOUR", "3")),
        corpus_end_hour=int(os.getenv("CORPUS_END_HOUR", "5")),
        corpus_schedule_timezone=os.getenv("CORPUS_SCHEDULE_TIMEZONE", "America/Detroit"),
    )
