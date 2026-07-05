# Research Briefing Agent

Local-first research briefing plus daily calendar/health dashboard.

## Components
- Source registry (RSS/HTML adapters)
- URL-only deduplication
- Morning digest generator
- FastAPI backend
- Calendar/health day view with nutrition, CGM, and Apple Health imports
- Simple frontend dashboard

## Run (scaffold)
The app runs as a single FastAPI service backed by Postgres.

## Database Workflow

Schema changes are no longer run from Python application startup.

- Baseline DDL snapshots live in `backend/ddl/`:
    - `backend/ddl/lalaland.sql`
    - `backend/ddl/health.sql`
- Executable migration history lives in `backend/migrations/<target>/`:
    - `backend/migrations/lalaland/*.sql`
    - `backend/migrations/health/*.sql`

Run migrations locally:

```bash
python3 backend/migrate.py --target lalaland
```

or for the health database:

```bash
python3 backend/migrate.py --target health --database-url postgresql://localhost:5432/health
```

Notes:
- The migration runner tracks applied files in `public.schema_migrations`.
- Migrations are applied in filename sort order.
- If `--target` is omitted, the runner infers target from the database name in `DATABASE_URL`.

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

### Table 2: Health tables

- `glucose_readings`
- `nutrition_events`
- `apple_health_workouts`

### Table 3: Daily Brief

### Table 4: Seen/ranked URLs
