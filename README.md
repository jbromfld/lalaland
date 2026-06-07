# Research Briefing Agent

Local-first daily research briefing system.

## Components
- Source registry (RSS/HTML adapters)
- URL-only deduplication
- Morning digest generator
- FastAPI backend
- Simple frontend dashboard

## Run (scaffold)
Backend is not fully wired yet; this is a starting structure.

## DB

### Table 1: Sources
```sql
research_sources
(
    id uuid,
    name text,
    category text,
    feed_url text,
    adapter_type text,
    source_weight int,
    enabled boolean
)
```

### Table 2: Daily Brief


### Table 3: Seen/ranked URLs
