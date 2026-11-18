"""PostgreSQL storage for the OAuth proxy state (``mcp_oauth_kv``).

Enable with::

    ATLASSIAN_OAUTH_CLIENT_STORAGE_MODE=factory
    ATLASSIAN_OAUTH_CLIENT_STORAGE_FACTORY=mcp_atlassian.servers.pg_storage:build_storage
    MCP_STORAGE_PG_URL=postgresql://user:pass@host:5432/db

The table is created by the migrations (``python -m mcp_atlassian.db upgrade``),
never by the store. Values are Fernet-encrypted with a key derived from the Jira
OAuth client secret, exactly as FastMCP derives the key of its default file
store, so there is no separate key to manage. If the secret changes, stored
rows can no longer be decrypted; they are treated as missing and every user
reconnects once.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from cryptography.fernet import Fernet

from mcp_atlassian.db.settings import asyncpg_url, get_pg_url

if TYPE_CHECKING:
    from key_value.aio.protocols import AsyncKeyValue

TABLE_NAME = "mcp_oauth_kv"
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


def build_storage(config: dict[str, Any] | None = None) -> AsyncKeyValue:
    """Storage factory for ``ATLASSIAN_OAUTH_CLIENT_STORAGE_FACTORY``.

    Args:
        config: Unused; accepted because the factory loader may pass the
            ``ATLASSIAN_OAUTH_CLIENT_STORAGE_CONFIG_JSON`` object.

    Returns:
        An encrypted PostgreSQL-backed key-value store.

    Raises:
        ValueError: If the secret or the PostgreSQL URL is missing/invalid.
    """
    from key_value.aio.stores.postgresql import PostgreSQLStore

    secret = client_secret()
    store = PostgreSQLStore(
        url=asyncpg_url(get_pg_url()),
        table_name=TABLE_NAME,
        auto_create=False,
    )
    return encrypted(store, secret)
