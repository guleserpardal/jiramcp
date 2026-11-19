"""PostgreSQL storage for the OAuth proxy state (``mcp_oauth_kv``).

Enable with::

    ATLASSIAN_OAUTH_CLIENT_STORAGE_MODE=factory
    ATLASSIAN_OAUTH_CLIENT_STORAGE_FACTORY=mcp_atlassian.servers.pg_storage:build_storage
    MCP_STORAGE_PG_URL=postgresql://user@host:5432/db
    PGPASSWORD=...   # asyncpg reads it; keeps the password out of the URL

The table is created by the migrations (``python -m mcp_atlassian.db upgrade``),
never by the store. Values are Fernet-encrypted with a key derived from the Jira
OAuth client secret, exactly as FastMCP derives the key of its default file
store, so there is no separate key to manage. If the secret changes, stored
rows can no longer be decrypted; they are treated as missing and every user
reconnects once.

Performance: every read is a network round trip to PostgreSQL (a login flow
does ~14, every authenticated MCP request ~4). Reads are therefore served from
a short-lived in-process cache (``MCP_STORAGE_CACHE_SECONDS``, default 60, 0 =
off); writes always go to PostgreSQL and drop the cached entry. The pool opens
one connection at start and closes idle ones after 60 s so a firewall that
silently drops idle TCP sessions cannot stall a request.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from cryptography.fernet import Fernet

from mcp_atlassian.db.settings import asyncpg_url, get_pg_url

if TYPE_CHECKING:
    from key_value.aio.protocols import AsyncKeyValue

TABLE_NAME = "mcp_oauth_kv"
CACHE_SECONDS_ENV = "MCP_STORAGE_CACHE_SECONDS"
POOL_MAX_ENV = "MCP_STORAGE_PG_POOL_MAX"
DEFAULT_CACHE_SECONDS = 60
DEFAULT_POOL_MAX = 5
POOL_IDLE_SECONDS = 60.0
"""Below typical firewall idle timeouts (5-15 min)."""
CONNECT_TIMEOUT_SECONDS = 10.0
COMMAND_TIMEOUT_SECONDS = 10.0
SECRET_ENVS = (
    "ATLASSIAN_OAUTH_CLIENT_SECRET",
    "JIRA_OAUTH_CLIENT_SECRET",
    "CONFLUENCE_OAUTH_CLIENT_SECRET",
)
"""Same lookup order as ``servers.main._build_auth_provider``."""

# FastMCP 3.4.x OAuthProxy.__init__ (fastmcp/server/auth/oauth_proxy/proxy.py):
# with no jwt_signing_key, signing key = derive_jwt_key(secret, JWT salt) and
# the default store's key = derive_jwt_key(signing_key.decode(), STORAGE salt).
_JWT_SALT = "fastmcp-jwt-signing-key"
_STORAGE_SALT = "fastmcp-storage-encryption-key"


def client_secret() -> str:
    """Return the Jira OAuth client secret from the environment.

    Returns:
        The secret.

    Raises:
        ValueError: If none of :data:`SECRET_ENVS` is set.
    """
    for name in SECRET_ENVS:
        value = os.getenv(name)
        if value:
            return value
    raise ValueError(
        "Jira OAuth client secret is not set "
        f"({' / '.join(SECRET_ENVS)}); PostgreSQL storage not opened."
    )


def storage_encryption_key(secret: str) -> bytes:
    """Derive the Fernet key FastMCP would use for its default store.

    Args:
        secret: The upstream (Jira) OAuth client secret.

    Returns:
        A urlsafe-base64 Fernet key.
    """
    from fastmcp.server.auth.jwt_issuer import derive_jwt_key

    signing_key = derive_jwt_key(high_entropy_material=secret, salt=_JWT_SALT)
    return derive_jwt_key(
        high_entropy_material=signing_key.decode(), salt=_STORAGE_SALT
    )


def encrypted(store: AsyncKeyValue, secret: str) -> AsyncKeyValue:
    """Wrap ``store`` with the secret-derived Fernet encryption.

    Undecryptable rows (secret changed) read as missing instead of raising.

    Args:
        store: The underlying key-value store.
        secret: The upstream OAuth client secret.

    Returns:
        The encrypting wrapper.
    """
    from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

    return FernetEncryptionWrapper(
        key_value=store,
        fernet=Fernet(storage_encryption_key(secret)),
        raise_on_decryption_error=False,
    )


def _int_env(name: str, default: int, minimum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def pool_options() -> dict[str, Any]:
    """Keyword arguments for ``asyncpg.create_pool``.

    Returns:
        Pool sizing and timeouts (see module docstring).
    """
    return {
        "min_size": 1,
        "max_size": _int_env(POOL_MAX_ENV, DEFAULT_POOL_MAX, 1),
        "max_inactive_connection_lifetime": POOL_IDLE_SECONDS,
        "timeout": CONNECT_TIMEOUT_SECONDS,
        "command_timeout": COMMAND_TIMEOUT_SECONDS,
    }


def postgresql_store(url: str) -> AsyncKeyValue:
    """PostgreSQLStore on ``mcp_oauth_kv`` with a tuned connection pool.

    The library's own pool uses asyncpg defaults (10 connections opened at
    first use, no timeouts); this one does not.

    Args:
        url: asyncpg-style URL (``postgresql://``).

    Returns:
        The store (table not auto-created).
    """
    import asyncpg
    from key_value.aio.stores.postgresql import PostgreSQLStore

    options = pool_options()

    class _TunedPostgreSQLStore(PostgreSQLStore):
        async def _create_pool(self) -> asyncpg.Pool:
            pool: asyncpg.Pool = await asyncpg.create_pool(url, **options)
            return pool

    return _TunedPostgreSQLStore(url=url, table_name=TABLE_NAME, auto_create=False)


def cached(store: AsyncKeyValue, seconds: int) -> AsyncKeyValue:
    """Serve reads from memory for up to ``seconds``; writes go through.

    Args:
        store: The (encrypted) primary store.
        seconds: Cache lifetime; 0 returns ``store`` unchanged.

    Returns:
        The caching wrapper, or ``store`` itself when disabled.
    """
    if seconds <= 0:
        return store
    from key_value.aio.stores.memory import MemoryStore
    from key_value.aio.wrappers.passthrough_cache import PassthroughCacheWrapper

    return PassthroughCacheWrapper(
        primary_key_value=store,
        cache_key_value=MemoryStore(),
        maximum_ttl=seconds,
        missing_ttl=seconds,
    )


def build_storage(config: dict[str, Any] | None = None) -> AsyncKeyValue:
    """Storage factory for ``ATLASSIAN_OAUTH_CLIENT_STORAGE_FACTORY``.

    Args:
        config: Unused; accepted because the factory loader may pass the
            ``ATLASSIAN_OAUTH_CLIENT_STORAGE_CONFIG_JSON`` object.

    Returns:
        An encrypted PostgreSQL-backed key-value store with a read cache.

    Raises:
        ValueError: If the secret, the PostgreSQL URL or a tuning variable is
            missing/invalid.
    """
    secret = client_secret()
    cache_seconds = _int_env(CACHE_SECONDS_ENV, DEFAULT_CACHE_SECONDS, 0)
    store = postgresql_store(asyncpg_url(get_pg_url()))
    return cached(encrypted(store, secret), cache_seconds)
