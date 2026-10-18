"""Publish source documents to the shared lassy service; no local retrieval logic."""
import argparse
import json
from urllib.parse import quote

import requests

from backend.config import load_settings
from backend.db import get_connection, initialize_database


COLLECTIONS = {"rss": "lalaland-rss", "corpus": "lalaland-corpus"}


def documents(conn, kind, source_id):
    table = {"rss": "inbox_entries", "corpus": "corpus_articles"}[kind]
    row = conn.execute(f"SELECT * FROM {table} WHERE id=%s", (source_id,)).fetchone()
    if not row:
        return {}
    if kind == "rss":
        return {str(source_id): dict(content=row["summary"], title=row["title"],
            url=row["canonical_url"], content_type="rss_summary",
            published_at=row["article_published_at"].isoformat() if row["article_published_at"] else None,
            metadata={"source_name": row["source_name"], "source_id": str(source_id)})}
    if row["state"] != "ready" or not row["article_text"]:
        return {}
    metadata = {"source_id": str(source_id), "article_metadata": row["metadata"]}
    # Extracted date strings are not consistently publication dates. Preserve raw
    # metadata and leave published_at unknown until date normalization is added.
    base = dict(title=row["title"] or "Untitled", url=row["canonical_url"], metadata=metadata)
    result = {str(source_id): dict(base, content=row["article_text"],
        sections=[{"ref": s["ref"], "text": s["text"]} for s in row["sections"] if s["text"].strip()],
        content_type="corpus_article")}
    if row["briefing"]:
        result[f"{source_id}-briefing"] = dict(base,
            content=json.dumps(row["briefing"], ensure_ascii=False), content_type="corpus_briefing")
    return result


def backfill(settings):
    """Queue current records transactionally, including reviewed RSS/corpus records."""
    with get_connection(settings) as conn:
        for kind, table in (("rss", "inbox_entries"), ("corpus", "corpus_articles")):
            conn.execute(f"""INSERT INTO knowledge_outbox(kind,source_id)
                SELECT %s,id FROM {table} ON CONFLICT(kind,source_id) DO UPDATE
                SET version=nextval('knowledge_event_version'),attempts=0,last_error=NULL,updated_at=NOW()""", (kind,))


def drain(settings, limit=25):
    if not settings.knowledge_service_url:
        return {"enabled": False, "indexed": 0, "failed": 0}
    indexed = failed = 0
    with get_connection(settings) as conn:
        # Serialize delivery across Temporal retries, multiple workers and CLI runs.
        # Autocommit keeps source/outbox transactions short during network calls.
        conn.autocommit = True
        if not conn.execute("SELECT pg_try_advisory_lock(765439109) AS acquired").fetchone()["acquired"]:
            return {"enabled": True, "indexed": 0, "failed": 0}
        try:
            events = conn.execute("SELECT * FROM knowledge_outbox ORDER BY updated_at,kind,source_id LIMIT %s", (limit,)).fetchall()
            with requests.Session() as session:
                for event in events:
                    kind, source_id = event["kind"], event["source_id"]
                    try:
                        desired = documents(conn, kind, source_id)
                        ids = [str(source_id)] + ([f"{source_id}-briefing"] if kind == "corpus" else [])
                        for document_id in ids:
                            url = f"{settings.knowledge_service_url}/documents/{COLLECTIONS[kind]}/{quote(document_id, safe='')}"
                            if document_id in desired:
                                response = session.put(url, json=desired[document_id], timeout=settings.knowledge_timeout_seconds)
                            else:
                                response = session.delete(url, timeout=settings.knowledge_timeout_seconds)
                            response.raise_for_status()
                        # A concurrent edit/delete replaces version; never acknowledge it here.
                        conn.execute("DELETE FROM knowledge_outbox WHERE kind=%s AND source_id=%s AND version=%s",
                                     (kind,source_id,event["version"]))
                        indexed += 1
                    except Exception as exc:
                        # Avoid persisting response bodies, source text or credentials.
                        conn.execute("""UPDATE knowledge_outbox SET attempts=attempts+1,last_error=%s,
                            updated_at=NOW() WHERE kind=%s AND source_id=%s AND version=%s""",
                            (type(exc).__name__,kind,source_id,event["version"]))
                        failed += 1
        finally:
            conn.execute("SELECT pg_advisory_unlock(765439109)")
    return {"enabled": True, "indexed": indexed, "failed": failed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["backfill", "sync", "status"])
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    settings = load_settings()
    initialize_database(settings)
    if args.command == "backfill":
        backfill(settings)
        print("Queued existing RSS and corpus documents. Worker schedule will deliver them.")
    elif args.command == "sync":
        print(json.dumps(drain(settings, args.limit)))
    else:
        with get_connection(settings) as conn:
            print(json.dumps(conn.execute("SELECT count(*) AS pending, count(*) FILTER (WHERE last_error IS NOT NULL) AS failed FROM knowledge_outbox").fetchone()))


if __name__ == "__main__":
    main()
