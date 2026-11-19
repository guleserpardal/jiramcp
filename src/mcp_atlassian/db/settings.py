"""Connection settings shared by Alembic and the runtime storage."""

from __future__ import annotations

import os

PG_URL_ENV = "MCP_STORAGE_PG_URL"
"""Environment variable holding ``postgresql://user@host:5432/db``.

Keep the password out of the URL: asyncpg reads ``PGPASSWORD``.
"""

VERSION_TABLE = "mcp_alembic_version"
"""Alembic version table; prefixed so it can share a database with other apps."""

TABLE_PREFIX = "mcp_"

_SCHEMES = ("postgresql", "postgres")


def get_pg_url() -> str:
    """Return the configured PostgreSQL URL.

    Returns:
        The raw URL from :data:`PG_URL_ENV`.

    Raises:
        ValueError: If the variable is missing or not a PostgreSQL URL. The
            message never contains the URL itself (it may carry a password).
    """
    raw = os.getenv(PG_URL_ENV, "").strip()
    if not raw:
        raise ValueError(f"{PG_URL_ENV} is not set; PostgreSQL storage disabled.")
    scheme = raw.split("://", 1)[0].split("+", 1)[0].lower()
    if "://" not in raw or scheme not in _SCHEMES:
        raise ValueError(f"{PG_URL_ENV} must start with postgresql://")
    return raw


def _rest(url: str) -> str:
    return url.split("://", 1)[1]


def asyncpg_url(url: str) -> str:
    """Return the URL in the form asyncpg accepts (``postgresql://``).

    Args:
        url: A PostgreSQL URL, possibly with a SQLAlchemy driver suffix.

    Returns:
        The same URL with the plain ``postgresql`` scheme.
    """
    return f"postgresql://{_rest(url)}"


def sqlalchemy_url(url: str) -> str:
    """Return the URL with the async SQLAlchemy driver (``postgresql+asyncpg``).

    Args:
        url: A PostgreSQL URL.

    Returns:
        The same URL with the ``postgresql+asyncpg`` scheme.
    """
    return f"postgresql+asyncpg://{_rest(url)}"
