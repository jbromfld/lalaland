-- Durable, coalescing indexing events. No foreign key: deletes must survive sources.
CREATE SEQUENCE IF NOT EXISTS knowledge_event_version;
CREATE TABLE IF NOT EXISTS knowledge_outbox (
    kind TEXT NOT NULL CHECK (kind IN ('rss', 'corpus')),
    source_id BIGINT NOT NULL,
    version BIGINT NOT NULL DEFAULT nextval('knowledge_event_version'),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(kind, source_id)
);
CREATE OR REPLACE FUNCTION queue_knowledge_change() RETURNS TRIGGER AS $$
DECLARE source_kind TEXT;
BEGIN
    source_kind := CASE WHEN TG_TABLE_NAME='inbox_entries' THEN 'rss' ELSE 'corpus' END;
    IF TG_OP='UPDATE' THEN
        IF source_kind='rss' THEN
            IF ROW(NEW.summary,NEW.title,NEW.canonical_url,NEW.article_published_at,NEW.source_name)
                IS NOT DISTINCT FROM ROW(OLD.summary,OLD.title,OLD.canonical_url,OLD.article_published_at,OLD.source_name) THEN
                RETURN NEW;
            END IF;
        ELSE
            IF ROW(NEW.article_text,NEW.sections,NEW.briefing,NEW.title,NEW.metadata,NEW.state,NEW.canonical_url)
                IS NOT DISTINCT FROM ROW(OLD.article_text,OLD.sections,OLD.briefing,OLD.title,OLD.metadata,OLD.state,OLD.canonical_url) THEN
                RETURN NEW;
            END IF;
        END IF;
    END IF;
    INSERT INTO knowledge_outbox(kind,source_id)
    VALUES (source_kind, CASE WHEN TG_OP='DELETE' THEN OLD.id ELSE NEW.id END)
    ON CONFLICT(kind,source_id) DO UPDATE SET version=nextval('knowledge_event_version'),
        attempts=0,last_error=NULL,updated_at=NOW();
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
CREATE OR REPLACE TRIGGER queue_rss_knowledge AFTER INSERT OR UPDATE OR DELETE ON inbox_entries
    FOR EACH ROW EXECUTE FUNCTION queue_knowledge_change();
CREATE OR REPLACE TRIGGER queue_corpus_knowledge AFTER INSERT OR UPDATE OR DELETE ON corpus_articles
    FOR EACH ROW EXECUTE FUNCTION queue_knowledge_change();
