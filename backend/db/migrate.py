from __future__ import annotations

import argparse
import os
from pathlib import Path
from urllib.parse import urlparse

from psycopg import connect


def infer_target(database_url: str) -> str:
    parsed = urlparse(database_url)
    name = parsed.path.lstrip("/")
    if not name:
        raise ValueError("Could not infer target from DATABASE_URL. Provide --target.")
    return name


def load_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def apply_migrations(database_url: str, target: str) -> None:
    backend_dir = Path(__file__).resolve().parent
    migrations_dir = backend_dir / "migrations" / target

    if not migrations_dir.exists() or not migrations_dir.is_dir():
        raise ValueError(f"Migration target directory not found: {migrations_dir}")

    migration_files = sorted(migrations_dir.glob("*.sql"))
    if not migration_files:
        print(f"No migrations found in {migrations_dir}")
        return

    bootstrap = migrations_dir / "000_schema_migrations.sql"

    with connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            if bootstrap.exists():
                cur.execute(load_sql(bootstrap))

            cur.execute("SELECT name FROM public.schema_migrations")
            applied = {row[0] for row in cur.fetchall()}

        for migration in migration_files:
            if migration.name in applied:
                print(f"skip  {migration.name}")
                continue

            print(f"apply {migration.name}")
            sql = load_sql(migration)

            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO public.schema_migrations (name) VALUES (%s)",
                    (migration.name,),
                )

    print("Migrations complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply local SQL migrations.")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", "postgresql://localhost:5432/lalaland"),
        help="PostgreSQL connection string. Defaults to DATABASE_URL env var.",
    )
    parser.add_argument(
        "--target",
        default=os.getenv("MIGRATION_TARGET"),
        help="Migration target folder name under backend/migrations (for example: lalaland or health).",
    )
    args = parser.parse_args()

    target = args.target or infer_target(args.database_url)
    apply_migrations(args.database_url, target)


if __name__ == "__main__":
    main()
