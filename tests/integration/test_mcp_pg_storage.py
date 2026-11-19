"""Migrations and storage against a real PostgreSQL.

Run with ``MCP_TEST_PG_URL=postgresql://user@host:5432/emptydb`` (password in
``PGPASSWORD``); the
database's ``mcp_`` tables are dropped and recreated.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from mcp_atlassian.db import migrate, schema
from mcp_atlassian.db.migrate import include_object
from mcp_atlassian.db.settings import VERSION_TABLE, asyncpg_url, sqlalchemy_url

PG_URL = os.getenv("MCP_TEST_PG_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not PG_URL, reason="MCP_TEST_PG_URL not set"),
]


@pytest.fixture
def migrated() -> Iterator[None]:
    migrate.downgrade("base", PG_URL)
    migrate.upgrade("head", PG_URL)
    yield
    migrate.downgrade("base", PG_URL)


@pytest.fixture
async def engine(migrated: None) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(sqlalchemy_url(PG_URL))
    yield eng
    await eng.dispose()


def _diff(connection: sa.Connection) -> list[object]:
    ctx = MigrationContext.configure(
        connection,
        opts={
            "compare_type": True,
            "include_object": include_object,
            "version_table": VERSION_TABLE,
        },
    )
    return list(compare_metadata(ctx, schema.metadata))


@pytest.mark.anyio
async def test_round_trip_and_no_drift(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        assert await conn.run_sync(_diff) == []
    migrate.downgrade("base", PG_URL)
    async with engine.connect() as conn:
        names = await conn.run_sync(lambda c: sa.inspect(c).get_table_names())
    assert not [n for n in names if n.startswith("mcp_") and n != VERSION_TABLE]
    migrate.upgrade("head", PG_URL)


@pytest.mark.anyio
async def test_real_store_round_trip(engine: AsyncEngine) -> None:
    from key_value.aio.stores.postgresql import PostgreSQLStore

    from mcp_atlassian.servers.pg_storage import encrypted

    raw = PostgreSQLStore(
        url=asyncpg_url(PG_URL), table_name="mcp_oauth_kv", auto_create=False
    )
    store = encrypted(raw, "integration-secret-0123456789")
    async with raw:
        await store.put(
            key="g1",
            value={"access_token": "PLAIN"},
            collection="mcp-upstream-tokens",
            ttl=60,
        )
        assert await store.get(key="g1", collection="mcp-upstream-tokens") == {
            "access_token": "PLAIN"
        }
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                sa.text("SELECT value::text, expires_at FROM mcp_oauth_kv")
            )
        ).one()
    assert "PLAIN" not in row[0]
    assert row[1] is not None


@pytest.mark.anyio
async def test_constraints(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            sa.insert(schema.grant_index).values(
                grant_id="g1", client_id="itool", product_username="ALI"
            )
        )
        await conn.execute(
            sa.insert(schema.tool_call_audit).values(
                grant_id="g1", tool_name="jira_search", outcome="ok"
            )
        )
    for stmt in (
        sa.insert(schema.grant_index).values(
            grant_id="g2", client_id="x", product_username="u", status="bogus"
        ),
        sa.insert(schema.tool_call_audit).values(
            grant_id="nope", tool_name="t", outcome="ok"
        ),
        sa.insert(schema.tool_call_audit).values(tool_name="t", outcome="maybe"),
    ):
        with pytest.raises(sa.exc.IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(stmt)
    async with engine.begin() as conn:
        await conn.execute(sa.delete(schema.grant_index))
        audit_grant = (
            await conn.execute(sa.select(schema.tool_call_audit.c.grant_id))
        ).scalar_one()
    assert audit_grant is None
