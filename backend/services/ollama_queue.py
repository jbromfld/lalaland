"""Serialize local inference across RSS and corpus workers/processes."""
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from backend.db import get_connection

# Stable application-specific PostgreSQL session advisory lock; no application rows change.
OLLAMA_LOCK = 765439102


class CorpusDeferred(Exception):
    """The overnight window has insufficient time for another model call."""


def check_deadline(settings, deadline, timeout_seconds=None):
    reserve = settings.corpus_ollama_timeout_seconds if timeout_seconds is None else timeout_seconds
    if deadline and datetime.now(UTC).timestamp() + reserve + 30 >= datetime.fromisoformat(deadline).timestamp():
        raise CorpusDeferred('Saved progress for the next overnight processing window')


@contextmanager
def inference_slot(settings, deadline=None, heartbeat=lambda:None, timeout_seconds=None):
    with get_connection(settings) as conn:
        conn.autocommit = True
        while True:
            check_deadline(settings, deadline, timeout_seconds)
            if conn.execute('SELECT pg_try_advisory_lock(%s) AS acquired',(OLLAMA_LOCK,)).fetchone()['acquired']:
                break
            heartbeat()
            time.sleep(1)
        try:
            check_deadline(settings, deadline, timeout_seconds)
            yield
        finally:
            conn.execute('SELECT pg_advisory_unlock(%s)',(OLLAMA_LOCK,))
