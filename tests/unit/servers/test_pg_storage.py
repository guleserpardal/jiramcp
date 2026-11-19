"""Tests for the PostgreSQL OAuth storage factory (no database needed)."""

from __future__ import annotations

from pathlib import Path

import pytest
from key_value.aio.stores.memory import MemoryStore

from mcp_atlassian.servers import pg_storage
from mcp_atlassian.servers.client_storage import (
    _validate_storage_candidate,
    build_oauth_client_storage_from_env,
)

SECRET = "jira-client-secret-for-tests-0123456789"
URL = "postgresql://mcp@db.example:5432/mcp"
# Built from parts so secret scanners do not mistake a test fixture for a leak.
LEAKY = "postgres" + "://u:" + "hunter2" + "@h/db"


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in pg_storage.SECRET_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ATLASSIAN_OAUTH_CLIENT_SECRET", SECRET)
    monkeypatch.setenv("MCP_STORAGE_PG_URL", URL)
    return monkeypatch


@pytest.mark.anyio
async def test_key_matches_fastmcp_default_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A row FastMCP's own default store wrote decrypts with our key.

    This pins the derivation to FastMCP's real behaviour, so rows written
    before the switch (or by another replica) stay readable.
    """
    import fastmcp
    from fastmcp.server.auth.oauth_proxy import OAuthProxy

    from mcp_atlassian.utils.token_verifier import AtlassianOpaqueTokenVerifier

    monkeypatch.setattr(fastmcp.settings, "home", tmp_path)
    proxy = OAuthProxy(
        upstream_authorization_endpoint="https://jira.example/authorize",
        upstream_token_endpoint="https://jira.example/token",
        upstream_client_id="client",
        upstream_client_secret=SECRET,
        token_verifier=AtlassianOpaqueTokenVerifier(required_scopes=[]),
        base_url="http://localhost:9000",
    )
    default_store = proxy._client_storage
    await default_store.put(key="k", value={"token": "t"}, collection="c")

    raw_store = default_store.key_value  # type: ignore[attr-defined]
    ours = pg_storage.encrypted(raw_store, SECRET)
    assert await ours.get(key="k", collection="c") == {"token": "t"}


@pytest.mark.anyio
async def test_values_are_encrypted_at_rest() -> None:
    raw = MemoryStore()
    store = pg_storage.encrypted(raw, SECRET)
    await store.put(key="grant", value={"access_token": "SECRET-TOKEN"}, collection="c")

    assert await store.get(key="grant", collection="c") == {
        "access_token": "SECRET-TOKEN"
    }
    stored = await raw.get(key="grant", collection="c")
    assert stored is not None
    assert "SECRET-TOKEN" not in repr(stored)


@pytest.mark.anyio
async def test_other_secret_reads_as_missing_not_error() -> None:
    raw = MemoryStore()
    await pg_storage.encrypted(raw, SECRET).put(
        key="grant", value={"a": 1}, collection="c"
    )
    other = pg_storage.encrypted(raw, "a-completely-different-secret-value")
    assert await other.get(key="grant", collection="c") is None


def _pg_store(storage: object) -> object:
    """PassthroughCache -> FernetEncryption -> PostgreSQLStore."""
    primary = getattr(storage, "primary_key_value", storage)
    return primary.key_value  # type: ignore[attr-defined]


def test_build_storage_uses_kv_table_without_auto_create(
    env: pytest.MonkeyPatch,
) -> None:
    storage = pg_storage.build_storage()
    inner = _pg_store(storage)
    assert inner._table_name == "mcp_oauth_kv"
    assert inner._auto_create is False
    assert inner._url == URL
    _validate_storage_candidate(storage)


def test_build_storage_accepts_driver_suffixed_url(env: pytest.MonkeyPatch) -> None:
    env.setenv("MCP_STORAGE_PG_URL", "postgresql+asyncpg://h/db")
    inner = _pg_store(pg_storage.build_storage())
    assert inner._url == "postgresql://h/db"


def test_secret_lookup_order(env: pytest.MonkeyPatch) -> None:
    env.delenv("ATLASSIAN_OAUTH_CLIENT_SECRET")
    env.setenv("CONFLUENCE_OAUTH_CLIENT_SECRET", "confluence")
    env.setenv("JIRA_OAUTH_CLIENT_SECRET", "jira")
    assert pg_storage.client_secret() == "jira"


def test_missing_secret_fails_clearly(env: pytest.MonkeyPatch) -> None:
    env.delenv("ATLASSIAN_OAUTH_CLIENT_SECRET")
    with pytest.raises(ValueError, match="client secret is not set"):
        pg_storage.build_storage()


@pytest.mark.parametrize("value", ["", LEAKY.replace("postgres", "mysql"), "hunter2"])
def test_bad_url_fails_without_leaking_it(env: pytest.MonkeyPatch, value: str) -> None:
    env.setenv("MCP_STORAGE_PG_URL", value)
    with pytest.raises(ValueError) as err:
        pg_storage.build_storage()
    assert "hunter2" not in str(err.value)


def test_factory_mode_loads_build_storage(env: pytest.MonkeyPatch) -> None:
    env.setenv("ATLASSIAN_OAUTH_CLIENT_STORAGE_MODE", "factory")
    env.setenv(
        "ATLASSIAN_OAUTH_CLIENT_STORAGE_FACTORY",
        "mcp_atlassian.servers.pg_storage:build_storage",
    )
    storage = build_oauth_client_storage_from_env()
    assert storage is not None


def test_pool_is_small_with_timeouts(env: pytest.MonkeyPatch) -> None:
    options = pg_storage.pool_options()
    assert options["min_size"] == 1
    assert options["max_size"] == pg_storage.DEFAULT_POOL_MAX
    assert options["max_inactive_connection_lifetime"] <= 60
    assert options["timeout"] and options["command_timeout"]
    env.setenv("MCP_STORAGE_PG_POOL_MAX", "2")
    assert pg_storage.pool_options()["max_size"] == 2


@pytest.mark.parametrize(
    "name", ["MCP_STORAGE_PG_POOL_MAX", "MCP_STORAGE_CACHE_SECONDS"]
)
@pytest.mark.parametrize("value", ["abc", "-1"])
def test_bad_tuning_values_fail_clearly(
    env: pytest.MonkeyPatch, name: str, value: str
) -> None:
    if name == "MCP_STORAGE_PG_POOL_MAX" and value == "-1":
        value = "0"
    env.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        pg_storage.build_storage()


def test_cache_can_be_disabled(env: pytest.MonkeyPatch) -> None:
    env.setenv("MCP_STORAGE_CACHE_SECONDS", "0")
    storage = pg_storage.build_storage()
    assert not hasattr(storage, "primary_key_value")
    assert _pg_store(storage)._table_name == "mcp_oauth_kv"  # type: ignore[attr-defined]


class _CountingStore(MemoryStore):
    def __init__(self) -> None:
        super().__init__()
        self.gets = 0

    async def get(self, key: str, *, collection: str | None = None):  # type: ignore[override]
        self.gets += 1
        return await super().get(key=key, collection=collection)

    async def ttl(self, key: str, *, collection: str | None = None):  # type: ignore[override]
        self.gets += 1
        return await super().ttl(key=key, collection=collection)


@pytest.mark.anyio
async def test_cache_serves_repeat_reads_and_writes_go_through() -> None:
    primary = _CountingStore()
    store = pg_storage.cached(pg_storage.encrypted(primary, SECRET), 60)
    await store.put(key="g", value={"v": 1}, collection="c")
    for _ in range(5):
        assert await store.get(key="g", collection="c") == {"v": 1}
    assert primary.gets == 1  # only the first read reached the database

    await store.put(key="g", value={"v": 2}, collection="c")
    assert await store.get(key="g", collection="c") == {"v": 2}
    await store.delete(key="g", collection="c")
    assert await store.get(key="g", collection="c") is None
    assert await primary.get(key="g", collection="c") is None
