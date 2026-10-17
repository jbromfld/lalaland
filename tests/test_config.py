import os

import pytest

from backend.config import Settings, load_settings
from backend.temporal.client import temporal_address, temporal_namespace


def test_missing_environment_uses_settings_defaults(monkeypatch):
    for name in list(os.environ):
        if name.startswith(('OLLAMA_', 'CORPUS_', 'SCHEDULE_', 'TEMPORAL_')) or name in (
            'DATABASE_URL', 'APP_TITLE', 'OTEL_SERVICE_NAME'
        ):
            monkeypatch.delenv(name)
    assert load_settings() == Settings()


@pytest.mark.parametrize('name,field,value,expected', [
    ('DATABASE_URL', 'database_url', 'postgresql://example.test/research', 'postgresql://example.test/research'),
    ('OLLAMA_MODEL', 'ollama_model', 'rss-custom', 'rss-custom'),
    ('CORPUS_MODEL', 'corpus_model', 'research-custom', 'research-custom'),
    ('SCHEDULE_HOUR', 'schedule_hour', '8', 8),
    ('CORPUS_FINAL_TIMEOUT_SECONDS', 'corpus_final_timeout_seconds', '600', 600),
])
def test_environment_overrides_keep_field_types(monkeypatch, name, field, value, expected):
    monkeypatch.setenv(name, value)
    actual = getattr(load_settings(), field)
    assert actual == expected
    assert type(actual) is type(expected)


def test_temporal_helpers_use_central_configuration(monkeypatch):
    monkeypatch.setenv('TEMPORAL_ADDRESS', 'temporal.example.test:7233')
    monkeypatch.setenv('TEMPORAL_NAMESPACE', 'research-test')
    settings = load_settings()
    assert temporal_address() == settings.temporal_address == 'temporal.example.test:7233'
    assert temporal_namespace() == settings.temporal_namespace == 'research-test'


def test_frontend_location_is_independent_of_working_directory(monkeypatch, tmp_path):
    expected = Settings().frontend_dir
    monkeypatch.chdir(tmp_path)
    assert load_settings().frontend_dir == expected
    assert expected.is_absolute() and expected.is_dir()


def test_invalid_integer_override_still_fails(monkeypatch):
    monkeypatch.setenv('CORPUS_SCHEDULE_HOUR', 'not-an-hour')
    with pytest.raises(ValueError):
        load_settings()
