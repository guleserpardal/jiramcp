"""Alembic environment: async engine (asyncpg), ``mcp_`` tables only."""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from mcp_atlassian.db.migrate import include_object
from mcp_atlassian.db.schema import metadata
from mcp_atlassian.db.settings import (
    VERSION_TABLE,
    get_pg_url,
    sqlalchemy_url,
)

config = context.config
target_metadata = metadata


def _url() -> str:
    # A URL set programmatically (tests, ``python -m mcp_atlassian.db``) wins;
    # alembic.ini never carries one.
    configured = config.get_main_option("sqlalchemy.url")
    url: str = sqlalchemy_url(configured or get_pg_url())
    return url


def _configure(connection: Connection | None = None, **extra: Any) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        include_object=include_object,
        compare_type=True,
        **extra,
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout (``alembic upgrade head --sql``)."""
    _configure(url=_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _url()
    engine = async_engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_sync)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    """Run migrations against the database.

    When called from inside a running event loop (an async caller of
    ``mcp_atlassian.db.migrate``), the migration runs on a worker thread with
    its own loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_run_async())
        return
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(asyncio.run, _run_async()).result()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
