"""Schema and migration checks that need no database."""

from __future__ import annotations

import io

import pytest
from alembic import command
from key_value.aio.stores.postgresql import store as kv_store_module

from mcp_atlassian.db import schema
from mcp_atlassian.db.migrate import alembic_config
from mcp_atlassian.db.settings import asyncpg_url, sqlalchemy_url


def test_all_tables_are_prefixed() -> None:
    assert sorted(schema.metadata.tables) == [
        "mcp_grant_index",
        "mcp_oauth_kv",
        "mcp_tool_call_audit",
    ]


def test_oauth_kv_matches_the_library_ddl() -> None:
    """The store runs with auto_create=False; columns must be what it expects."""
    import inspect

    source = inspect.getsource(kv_store_module)
    for column in schema.oauth_kv.columns:
        assert f"{column.name} " in source
    assert [c.name for c in schema.oauth_kv.primary_key] == ["collection", "key"]
    assert "idx_{self._table_name}_expires_at" in source


def test_grant_link_is_not_a_foreign_key() -> None:
    assert not schema.grant_index.foreign_keys
    fks = list(schema.tool_call_audit.foreign_keys)
    assert [fk.target_fullname for fk in fks] == ["mcp_grant_index.grant_id"]
    assert fks[0].ondelete == "SET NULL"


def test_offline_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_STORAGE_PG_URL", "postgresql://u:p@h/db")
    buffer = io.StringIO()
    cfg = alembic_config()
    cfg.output_buffer = buffer
    command.upgrade(cfg, "head", sql=True)
    sql = buffer.getvalue()
    assert "CREATE TABLE mcp_alembic_version" in sql
    for table in schema.metadata.tables:
        assert f"CREATE TABLE {table}" in sql
    assert "WHERE expires_at IS NOT NULL" in sql


def test_url_conversion() -> None:
    assert sqlalchemy_url("postgresql://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"
    assert asyncpg_url("postgresql+psycopg://u:p@h/db") == "postgresql://u:p@h/db"
