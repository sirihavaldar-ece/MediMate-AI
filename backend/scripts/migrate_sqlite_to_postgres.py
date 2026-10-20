"""Copy an existing MediMate SQLite database into a new PostgreSQL database.

Set DATABASE_URL to the empty PostgreSQL destination. Pass the SQLite file path
as the sole argument. This is a one-time data transfer, not schema versioning.
"""

from pathlib import Path
import sys

from sqlalchemy import create_engine, func, select, text

from app.config import DATABASE_URL
from app.database import Base
from app import models  # noqa: F401 - register every mapped table


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.migrate_sqlite_to_postgres <sqlite-file>")
        return 2
    source_path = Path(sys.argv[1]).resolve()
    if not source_path.is_file():
        print("Source SQLite file does not exist.")
        return 2
    if not DATABASE_URL.startswith("postgresql+"):
        print("DATABASE_URL must point to the PostgreSQL destination.")
        return 2

    source = create_engine(f"sqlite:///{source_path.as_posix()}")
    destination = create_engine(DATABASE_URL)
    Base.metadata.create_all(destination)
    tables = Base.metadata.sorted_tables
    try:
        with destination.begin() as target, source.connect() as original:
            for table in tables:
                count = target.scalar(select(func.count()).select_from(table))
                if count:
                    raise RuntimeError(
                        f"Destination table {table.name} is not empty; refusing to merge data."
                    )
            copied: dict[str, int] = {}
            for table in tables:
                rows = [dict(row) for row in original.execute(select(table)).mappings()]
                if rows:
                    target.execute(table.insert(), rows)
                copied[table.name] = len(rows)
            for table in tables:
                if "id" in table.c and table.name not in {"revoked_tokens"}:
                    target.execute(
                        text(
                            "SELECT setval(pg_get_serial_sequence(:table_name, 'id'), "
                            "COALESCE((SELECT MAX(id) FROM \"" + table.name + "\"), 1), "
                            "EXISTS (SELECT 1 FROM \"" + table.name + "\"))"
                        ),
                        {"table_name": table.name},
                    )
        print("SQLite data copied successfully. Row counts:")
        for table_name, count in copied.items():
            print(f"  {table_name}: {count}")
    finally:
        source.dispose()
        destination.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
