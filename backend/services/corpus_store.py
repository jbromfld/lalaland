"""Persistent corpus records; network and model calls never hold a transaction."""
from psycopg.types.json import Jsonb
from backend.db import get_connection

SCHEMA = """
CREATE TABLE IF NOT EXISTS corpus_articles (
 id BIGSERIAL PRIMARY KEY, original_url TEXT NOT NULL,
 canonical_url TEXT NOT NULL UNIQUE, resolved_url TEXT, title TEXT,
 metadata JSONB NOT NULL DEFAULT '{}', article_text TEXT,
 sections JSONB NOT NULL DEFAULT '[]', briefing JSONB NOT NULL DEFAULT '{}',
 state TEXT NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','extracting','summarizing','ready','failed')),
 error TEXT, model TEXT NOT NULL, prompt_version TEXT NOT NULL DEFAULT 'engineering-v1',
 attempt INTEGER NOT NULL DEFAULT 1,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 search_document TSVECTOR GENERATED ALWAYS AS (
 to_tsvector('english', coalesce(title,'') || ' ' || coalesce(article_text,'') || ' ' || briefing::text)
 ) STORED
);
CREATE INDEX IF NOT EXISTS idx_corpus_search ON corpus_articles USING GIN(search_document);
CREATE TABLE IF NOT EXISTS corpus_progress (
 article_id BIGINT PRIMARY KEY REFERENCES corpus_articles(id) ON DELETE CASCADE,
 attempt INTEGER NOT NULL, activity_attempt INTEGER NOT NULL,
 stage TEXT NOT NULL, current INTEGER NOT NULL, total INTEGER NOT NULL,
 completed INTEGER NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS corpus_generations (
 article_id BIGINT NOT NULL REFERENCES corpus_articles(id) ON DELETE CASCADE,
 model TEXT NOT NULL, prompt_version TEXT NOT NULL, prompt_hash TEXT NOT NULL,
 response TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 PRIMARY KEY(article_id,model,prompt_version,prompt_hash)
);
CREATE TABLE IF NOT EXISTS corpus_reviews (
 article_id BIGINT PRIMARY KEY REFERENCES corpus_articles(id) ON DELETE CASCADE,
 rating SMALLINT CHECK (rating BETWEEN 1 AND 5),
 read_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS corpus_quarantine (
 article_id BIGINT PRIMARY KEY REFERENCES corpus_articles(id) ON DELETE CASCADE,
 url TEXT NOT NULL, reason TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS corpus_sources (
 hostname TEXT PRIMARY KEY,
 approved_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def get(settings, article_id):
    with get_connection(settings) as conn:
        row = conn.execute('''SELECT corpus_articles.*, q.url AS quarantine_url, q.reason AS quarantine_reason, corpus_reviews.rating, corpus_reviews.read_at
            FROM corpus_articles LEFT JOIN corpus_quarantine q ON q.article_id=corpus_articles.id LEFT JOIN corpus_reviews ON corpus_reviews.article_id=corpus_articles.id
            WHERE corpus_articles.id = %s''', (article_id,)).fetchone()
        if row:
            row['progress'] = conn.execute('''SELECT stage,current,total,completed,activity_attempt,updated_at
                FROM corpus_progress WHERE article_id=%s AND attempt=%s''', (article_id,row['attempt'])).fetchone()
        return row


def create(settings, url, canonical, model, quarantine_reason=None):
    with get_connection(settings) as conn:
        row = conn.execute('''INSERT INTO corpus_articles (original_url,canonical_url,model)
            VALUES (%s,%s,%s) ON CONFLICT (canonical_url) DO NOTHING RETURNING *''',
            (url, canonical, model)).fetchone()
        if row:
            if quarantine_reason:
                conn.execute('INSERT INTO corpus_quarantine(article_id,url,reason) VALUES (%s,%s,%s)',
                             (row['id'], url, quarantine_reason))
                row.update(quarantine_url=url, quarantine_reason=quarantine_reason)
            return row, True
        return conn.execute('SELECT * FROM corpus_articles WHERE canonical_url=%s', (canonical,)).fetchone(), False


def update(settings, article_id, attempt, **values):
    allowed = {'state','error','resolved_url','title','metadata','article_text','sections','briefing'}
    if not values or not set(values) <= allowed:
        raise ValueError('Invalid corpus update')
    params = [Jsonb(v) if k in {'metadata','sections','briefing'} else v for k,v in values.items()]
    with get_connection(settings) as conn:
        conn.execute('UPDATE corpus_articles SET ' + ', '.join(f'{k}=%s' for k in values) +
                     ', updated_at=NOW() WHERE id=%s AND attempt=%s', (*params, article_id, attempt))


def retry(settings, article_id, model):
    with get_connection(settings) as conn:
        return conn.execute('''UPDATE corpus_articles SET state='queued', error=NULL,
            model=%s, attempt=attempt+1, updated_at=NOW() WHERE id=%s AND state='failed' RETURNING *''',
            (model,article_id)).fetchone()


def search(settings, keyword, page, limit, *, include_reviewed=False):
    conditions = []
    if not include_reviewed:
        conditions.append('corpus_reviews.read_at IS NULL AND corpus_reviews.rating IS NULL')
    if keyword:
        conditions.append("search_document @@ websearch_to_tsquery('english', %s)")
    condition = 'WHERE ' + ' AND '.join(conditions) if conditions else ''
    tables = 'corpus_articles LEFT JOIN corpus_quarantine q ON q.article_id=corpus_articles.id LEFT JOIN corpus_reviews ON corpus_reviews.article_id=corpus_articles.id'
    args = (keyword,) if keyword else ()
    order = "ts_rank(search_document, websearch_to_tsquery('english', %s)) DESC," if keyword else ''
    with get_connection(settings) as conn:
        total = conn.execute(f'SELECT count(*) AS count FROM {tables} {condition}', args).fetchone()['count']
        rows = conn.execute(f'''SELECT id, original_url, title, state, error, model, q.url AS quarantine_url, q.reason AS quarantine_reason, corpus_articles.created_at, updated_at, rating, read_at,
            (SELECT jsonb_build_object('stage',p.stage,'current',p.current,'total',p.total,
                'completed',p.completed,'activity_attempt',p.activity_attempt,'updated_at',p.updated_at)
             FROM corpus_progress p WHERE p.article_id=corpus_articles.id AND p.attempt=corpus_articles.attempt) AS progress
            FROM {tables} {condition} ORDER BY {order} corpus_articles.created_at DESC, id DESC LIMIT %s OFFSET %s''',
            (*args, *args, limit, (page-1)*limit)).fetchall()
    return {'items':rows, 'total':total, 'page':page, 'limit':limit}


def set_progress(settings, article_id, attempt, activity_attempt, stage, current, total, completed):
    """Ignore stale activities after manual retry, without touching article text or search indexes."""
    with get_connection(settings) as conn:
        if not conn.execute('SELECT id FROM corpus_articles WHERE id=%s FOR KEY SHARE',
                            (article_id,)).fetchone():
            return
        conn.execute("""INSERT INTO corpus_progress
            (article_id,attempt,activity_attempt,stage,current,total,completed)
            SELECT id,attempt,%s,%s,%s,%s,%s FROM corpus_articles
            WHERE id=%s AND attempt=%s AND state='summarizing'
            ON CONFLICT(article_id) DO UPDATE SET
                attempt=EXCLUDED.attempt, activity_attempt=EXCLUDED.activity_attempt,
                stage=EXCLUDED.stage,current=EXCLUDED.current,total=EXCLUDED.total,
                completed=EXCLUDED.completed,updated_at=NOW()
            WHERE (corpus_progress.attempt,corpus_progress.activity_attempt)
               <= (EXCLUDED.attempt,EXCLUDED.activity_attempt)""",
            (activity_attempt,stage,current,total,completed,article_id,attempt))


def cached_generation(settings, article, digest):
    with get_connection(settings) as conn:
        row = conn.execute("""SELECT response FROM corpus_generations
            WHERE article_id=%s AND model=%s AND prompt_version=%s AND prompt_hash=%s""",
            (article['id'],article['model'],article['prompt_version'],digest)).fetchone()
        return row['response'] if row else None


def save_generation(settings, article, digest, response):
    with get_connection(settings) as conn:
        # Serialize with deletion, so an in-flight model response cannot leave
        # orphaned cache entries or fail a foreign-key check after deletion.
        if not conn.execute('SELECT id FROM corpus_articles WHERE id=%s FOR KEY SHARE',
                            (article['id'],)).fetchone():
            return
        conn.execute("""INSERT INTO corpus_generations(article_id,model,prompt_version,prompt_hash,response)
            VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
            (article['id'],article['model'],article['prompt_version'],digest,response))


def queued_articles(settings):
    with get_connection(settings) as conn:
        return conn.execute("SELECT id,attempt FROM corpus_articles WHERE state='queued' AND NOT EXISTS (SELECT 1 FROM corpus_quarantine q WHERE q.article_id=corpus_articles.id) ORDER BY created_at,id").fetchall()


def review(settings, article_id, rating=None):
    """Rating also marks read; review state is independent of processing state."""
    with get_connection(settings) as conn:
        return conn.execute('''INSERT INTO corpus_reviews(article_id,rating)
            SELECT id,%s FROM corpus_articles WHERE id=%s AND state='ready'
            ON CONFLICT(article_id) DO UPDATE SET rating=COALESCE(EXCLUDED.rating,corpus_reviews.rating)
            RETURNING article_id,rating,read_at''',(rating,article_id)).fetchone()


def quarantine(settings, article_id, attempt, url, reason):
    with get_connection(settings) as conn:
        row = conn.execute("""UPDATE corpus_articles SET state='queued', error=NULL, updated_at=NOW()
            WHERE id=%s AND attempt=%s AND state <> 'ready' RETURNING id""", (article_id, attempt)).fetchone()
        if row:
            conn.execute("""INSERT INTO corpus_quarantine(article_id,url,reason) VALUES (%s,%s,%s)
                ON CONFLICT(article_id) DO UPDATE SET url=EXCLUDED.url,reason=EXCLUDED.reason,created_at=NOW()""",
                (article_id,url,reason))


def approved_hosts(settings):
    """UI approvals trust exact hosts; configured domains also trust subdomains."""
    with get_connection(settings) as conn:
        return tuple(row['hostname'] for row in conn.execute('SELECT hostname FROM corpus_sources').fetchall())


def release(settings, article_id, *, approved_hosts=(), quarantine_url=None):
    with get_connection(settings) as conn:
        # Match quarantine's lock order, and serialize concurrent release/deletion.
        if not conn.execute('SELECT id FROM corpus_articles WHERE id=%s FOR UPDATE', (article_id,)).fetchone():
            return None
        row = conn.execute('''DELETE FROM corpus_quarantine WHERE article_id=%s
            AND (%s::text IS NULL OR url=%s) RETURNING article_id''',
            (article_id, quarantine_url, quarantine_url)).fetchone()
        if row:
            for hostname in approved_hosts:
                conn.execute('INSERT INTO corpus_sources(hostname) VALUES (%s) ON CONFLICT DO NOTHING', (hostname,))
            return conn.execute("""UPDATE corpus_articles SET state='queued',error=NULL,
                attempt=attempt+1,updated_at=NOW() WHERE id=%s RETURNING *""", (article_id,)).fetchone()


def delete(settings, article_id):
    """Foreign-key cascades remove progress, evidence, reviews, and quarantine."""
    with get_connection(settings) as conn:
        return conn.execute('DELETE FROM corpus_articles WHERE id=%s RETURNING id',
                            (article_id,)).fetchone()
