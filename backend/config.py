from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class Settings:
    database_url: str = "postgresql://localhost:5432/lalaland"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "granite4.2:3b"
    ollama_timeout_seconds: int = 120
    inference_queue_timeout_seconds: int = 30
    schedule_hour: int = 6
    schedule_minute: int = 0
    schedule_timezone: str = "UTC"
    app_title: str = "Research Briefing"
    service_name: str = "research-briefing"
    frontend_dir: Path = Path(__file__).resolve().parent.parent / "frontend"
    corpus_trusted_domains: tuple[str, ...] = ("arxiv.org", "neurips.cc")
    corpus_model: str = "granite4.2:3b"
    corpus_ollama_timeout_seconds: int = 300
    corpus_final_timeout_seconds: int = 900
    corpus_final_num_predict: int = 6144
    corpus_schedule_hour: int = 3
    corpus_end_hour: int = 5
    corpus_schedule_timezone: str = "America/Detroit"
    knowledge_enabled: bool = False
    knowledge_service_url: str = ""
    knowledge_timeout_seconds: int = 120
    knowledge_model: str = "granite4.2:3b"
    knowledge_agent_timeout_seconds: int = 120
    knowledge_agent_instructions: str = "Answer the question concisely, explaining the main findings and relevant limitations."
    knowledge_schedule_hour: int = 7
    knowledge_schedule_minute: int = 0
    knowledge_schedule_timezone: str = "America/Detroit"
    temporal_address: str = "host.docker.internal:30733"
    temporal_namespace: str = "lalaland"

    def __post_init__(self):
        for name in ('ollama_timeout_seconds', 'inference_queue_timeout_seconds',
                     'corpus_ollama_timeout_seconds', 'corpus_final_timeout_seconds',
                     'corpus_final_num_predict', 'knowledge_timeout_seconds',
                     'knowledge_agent_timeout_seconds'):
            if getattr(self, name) <= 0:
                raise ValueError(f'{name} must be positive')
        for prefix in ('schedule', 'knowledge_schedule'):
            if not (0 <= getattr(self, prefix + '_hour') <= 23 and
                    0 <= getattr(self, prefix + '_minute') <= 59):
                raise ValueError(f'{prefix} requires an hour from 0–23 and minute from 0–59')
        if not 0 <= self.corpus_schedule_hour < self.corpus_end_hour <= 23:
            raise ValueError('Corpus window must end after it starts, on the same day')
        for timezone in (self.schedule_timezone, self.corpus_schedule_timezone,
                         self.knowledge_schedule_timezone):
            try:
                ZoneInfo('UTC' if timezone.lower() == 'local' else timezone)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError(f'Invalid schedule timezone: {timezone}') from exc
        if max(self.corpus_ollama_timeout_seconds, self.corpus_final_timeout_seconds) >= 1200:
            raise ValueError('Corpus inference timeouts must be below the 1200-second heartbeat timeout')

    @property
    def knowledge_active(self) -> bool:
        return self.knowledge_enabled and bool(self.knowledge_service_url)


def trusted_domains(value: str) -> tuple[str, ...]:
    domains = []
    for entry in value.split(','):
        if not entry.strip():
            continue
        domain = entry.strip().lower().encode('idna').decode('ascii')
        if len(domain) > 253 or not all(
            re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
            for label in domain.split('.')
        ):
            raise ValueError('CORPUS_TRUSTED_DOMAINS must contain DNS domains, without URLs, ports, or wildcards')
        domains.append(domain)
    return tuple(dict.fromkeys(domains))


def load_settings() -> Settings:
    """Apply environment overrides to the defaults declared on Settings."""
    defaults = Settings()
    return replace(
        defaults,
        knowledge_enabled=boolean_setting("KNOWLEDGE_ENABLED", defaults.knowledge_enabled),
        knowledge_service_url=os.getenv("KNOWLEDGE_SERVICE_URL", defaults.knowledge_service_url).rstrip("/"),
        knowledge_timeout_seconds=int(os.getenv("KNOWLEDGE_TIMEOUT_SECONDS", str(defaults.knowledge_timeout_seconds))),
        knowledge_model=os.getenv("KNOWLEDGE_MODEL", defaults.knowledge_model),
        knowledge_agent_timeout_seconds=int(os.getenv("KNOWLEDGE_AGENT_TIMEOUT_SECONDS", str(defaults.knowledge_agent_timeout_seconds))),
        knowledge_agent_instructions=os.getenv("KNOWLEDGE_AGENT_INSTRUCTIONS", defaults.knowledge_agent_instructions),
        knowledge_schedule_hour=int(os.getenv("KNOWLEDGE_SCHEDULE_HOUR", str(defaults.knowledge_schedule_hour))),
        knowledge_schedule_minute=int(os.getenv("KNOWLEDGE_SCHEDULE_MINUTE", str(defaults.knowledge_schedule_minute))),
        knowledge_schedule_timezone=os.getenv("KNOWLEDGE_SCHEDULE_TIMEZONE", defaults.knowledge_schedule_timezone),
        database_url=os.getenv("DATABASE_URL", defaults.database_url),
        inference_queue_timeout_seconds=int(os.getenv(
            "INFERENCE_QUEUE_TIMEOUT_SECONDS", str(defaults.inference_queue_timeout_seconds))),
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
        corpus_trusted_domains=trusted_domains(os.getenv(
            "CORPUS_TRUSTED_DOMAINS", ",".join(defaults.corpus_trusted_domains)
        )),
        corpus_model=os.getenv("CORPUS_MODEL", defaults.corpus_model),
        corpus_ollama_timeout_seconds=int(os.getenv(
            "CORPUS_OLLAMA_TIMEOUT_SECONDS", str(defaults.corpus_ollama_timeout_seconds)
        )),
        corpus_final_timeout_seconds=int(os.getenv(
            "CORPUS_FINAL_TIMEOUT_SECONDS", str(defaults.corpus_final_timeout_seconds)
        )),
        corpus_final_num_predict=int(os.getenv(
            "CORPUS_FINAL_NUM_PREDICT", str(defaults.corpus_final_num_predict)
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


def boolean_setting(name: str, default: bool) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    if value in ('true', '1', 'yes', 'on'):
        return True
    if value in ('false', '0', 'no', 'off'):
        return False
    raise ValueError(f'{name} must be a boolean')
