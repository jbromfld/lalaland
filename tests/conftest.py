import uuid
from dataclasses import replace
from pathlib import Path

import psycopg
import pytest

from backend.config import load_settings
from backend.db import initialize_database


ADMIN_DATABASE_URL = "postgresql://testuser:testpass@127.0.0.1:5432/postgres"


@pytest.fixture
def settings():
    """Settings pointed at a freshly created, freshly dropped test database."""
    db_name = f"lalaland_test_{uuid.uuid4().hex[:12]}"

    with psycopg.connect(ADMIN_DATABASE_URL, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{db_name}"')

    try:
        test_settings = replace(
            load_settings(),
            database_url=f"postgresql://testuser:testpass@127.0.0.1:5432/{db_name}",
            frontend_dir=Path(__file__).resolve().parent.parent / "frontend",
        )
        initialize_database(test_settings)
        yield test_settings
    finally:
        with psycopg.connect(ADMIN_DATABASE_URL, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE "{db_name}" WITH (FORCE)')
