"""PostgreSQL persistence for the OAuth proxy (tables managed with Alembic).

Nothing here is imported by the server unless PostgreSQL storage is enabled
(``ATLASSIAN_OAUTH_CLIENT_STORAGE_MODE=factory`` with
``mcp_atlassian.servers.pg_storage:build_storage``).
"""

from mcp_atlassian.db.settings import (
    PG_URL_ENV,
    VERSION_TABLE,
    asyncpg_url,
    get_pg_url,
    sqlalchemy_url,
)

__all__ = [
    "PG_URL_ENV",
    "VERSION_TABLE",
    "asyncpg_url",
    "get_pg_url",
    "sqlalchemy_url",
]
