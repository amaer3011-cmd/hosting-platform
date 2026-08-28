#!/usr/bin/env python3
"""
SQLite to PostgreSQL Migration Script

This script migrates data from the existing SQLite database to PostgreSQL.
Run this before deploying to production with PostgreSQL.

Usage:
    python migrate_sqlite_to_postgres.py --sqlite-path ./data/hosting.db --postgres-url postgresql+asyncpg://user:pass@host/db
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from sqlalchemy import create_engine, text, inspect, MetaData, Table
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from models import Base, User, Bot, EnvVar, BotProcessState, Deployment, AuditLog, BackupRecord, SystemConfig


def get_sqlite_engine(sqlite_path: str):
    """Create SQLite engine."""
    if not sqlite_path.startswith("sqlite:///"):
        sqlite_path = f"sqlite:///{sqlite_path}"
    return create_engine(sqlite_path, connect_args={"check_same_thread": False})


def get_postgres_engine(postgres_url: str):
    """Create PostgreSQL async engine."""
    if postgres_url.startswith("postgresql://"):
        postgres_url = postgres_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif postgres_url.startswith("postgresql+psycopg2://"):
        postgres_url = postgres_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    return create_async_engine(postgres_url, pool_pre_ping=True)


async def migrate_table(
    sqlite_session: Session,
    pg_session: AsyncSession,
    model_class,
    table_name: str,
    batch_size: int = 1000,
) -> int:
    """Migrate a single table from SQLite to PostgreSQL."""
    print(f"  Migrating {table_name}...")

    # Get all records from SQLite
    records = sqlite_session.query(model_class).all()
    if not records:
        print(f"    No records found")
        return 0

    count = 0
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]

        # Convert to dicts
        data = []
        for record in batch:
            record_dict = {}
            for column in model_class.__table__.columns:
                value = getattr(record, column.name)
                # Handle special types
                if hasattr(value, 'isoformat'):  # datetime
                    value = value.isoformat() if value else None
                record_dict[column.name] = value
            data.append(record_dict)

        # Upsert into PostgreSQL
        table = model_class.__table__
        stmt = pg_insert(table).values(data)
        # On conflict, update all columns except primary key
        pk_columns = [c.name for c in table.primary_key.columns]
        update_dict = {c.name: stmt.excluded[c.name] for c in table.columns if c.name not in pk_columns}
        stmt = stmt.on_conflict_do_update(
            index_elements=pk_columns,
            set_=update_dict,
        )
        await pg_session.execute(stmt)
        count += len(batch)

    await pg_session.commit()
    print(f"    Migrated {count} records")
    return count


async def migrate_sequences(pg_session: AsyncSession, tables: List[str]) -> None:
    """Reset PostgreSQL sequences after migration."""
    print("  Resetting sequences...")
    for table in tables:
        # Get the primary key column
        pk_query = f"""
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = '{table}'::regclass AND i.indisprimary
        """
        result = await pg_session.execute(text(pk_query))
        pk_column = result.scalar()

        if pk_column:
            # Reset sequence
            seq_query = f"SELECT setval('{table}_{pk_column}_seq', (SELECT COALESCE(MAX({pk_column}), 1) FROM {table}))"
            await pg_session.execute(text(seq_query))
            print(f"    Reset sequence for {table}.{pk_column}")

    await pg_session.commit()


async def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite to PostgreSQL")
    parser.add_argument("--sqlite-path", required=True, help="Path to SQLite database file")
    parser.add_argument("--postgres-url", required=True, help="PostgreSQL connection URL")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be migrated without doing it")
    parser.add_argument("--batch-size", type=int, default=1000, help="Batch size for migration")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite_path)
    if not sqlite_path.exists():
        print(f"Error: SQLite database not found at {sqlite_path}")
        sys.exit(1)

    print(f"SQLite source: {sqlite_path}")
    print(f"PostgreSQL target: {args.postgres_url}")
    print(f"Dry run: {args.dry_run}")
    print()

    # Create engines
    sqlite_engine = get_sqlite_engine(str(sqlite_path))
    pg_engine = get_postgres_engine(args.postgres_url)

    # Create PostgreSQL tables
    print("Creating PostgreSQL tables...")
    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created")
    print()

    if args.dry_run:
        print("DRY RUN - No data will be migrated")
        # Just show counts
        sqlite_session = sessionmaker(bind=sqlite_engine)()
        for model_class in [User, Bot, EnvVar, BotProcessState, Deployment, AuditLog, BackupRecord, SystemConfig]:
            count = sqlite_session.query(model_class).count()
            print(f"  {model_class.__tablename__}: {count} records")
        sqlite_session.close()
        return

    # Migrate data
    print("Starting data migration...")
    sqlite_session = sessionmaker(bind=sqlite_engine)()
    pg_session_factory = sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)

    async with pg_session_factory() as pg_session:
        # Migration order matters due to foreign keys
        migration_order = [
            (User, "users"),
            (Bot, "bots"),
            (EnvVar, "env_vars"),
            (BotProcessState, "bot_process_state"),
            (Deployment, "deployments"),
            (AuditLog, "audit_logs"),
            (BackupRecord, "backup_records"),
            (SystemConfig, "system_config"),
        ]

        total_migrated = 0
        for model_class, table_name in migration_order:
            count = await migrate_table(sqlite_session, pg_session, model_class, table_name, args.batch_size)
            total_migrated += count

        # Reset sequences
        table_names = [t for _, t in migration_order]
        await migrate_sequences(pg_session, table_names)

    sqlite_session.close()
    await pg_engine.dispose()

    print()
    print(f"Migration complete! Total records migrated: {total_migrated}")
    print()
    print("Next steps:")
    print("1. Update your .env to use the PostgreSQL DATABASE_URL")
    print("2. Restart the application")
    print("3. Verify all data is accessible")


if __name__ == "__main__":
    asyncio.run(main())