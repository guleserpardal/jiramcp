"""Run the bundled Alembic migrations without an ``alembic.ini`` file.

Usage::

    python -m mcp_atlassian.db upgrade          # to the latest revision
    python -m mcp_atlassian.db downgrade base   # drop the tables
    python -m mcp_atlassian.db current
    python -m mcp_atlassian.db sql              # print the SQL, no connection
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config

from mcp_atlassian.db.settings import TABLE_PREFIX

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    """Alembic filter: compare only ``mcp_`` tables (the database may be shared).

    Args:
        obj: The schema object.
        name: Its name.
        type_: Object kind (``table``, ``index`` ...).
        reflected: Whether it was reflected from the database.
        compare_to: The object it is compared against.

    Returns:
        True to include the object in autogenerate comparisons.
    """
    if type_ == "table":
        return bool(name) and str(name).startswith(TABLE_PREFIX)
    return True


def alembic_config(url: str | None = None) -> Config:
    """Build an Alembic config pointing at the bundled migrations.

    Args:
        url: Optional PostgreSQL URL; when omitted ``MCP_STORAGE_PG_URL`` is read
            by the migration environment.

    Returns:
        The Alembic configuration object.
    """
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option(
        "file_template",
        "%%(year)d%%(month).2d%%(day).2d_%%(rev)s_%%(slug)s",
    )
    if url:
        # Escape '%' so ConfigParser interpolation leaves passwords alone.
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def upgrade(revision: str = "head", url: str | None = None) -> None:
    """Upgrade the database to ``revision``.

    Args:
        revision: Target revision.
        url: Optional PostgreSQL URL (defaults to the environment).
    """
    command.upgrade(alembic_config(url), revision)


def downgrade(revision: str, url: str | None = None) -> None:
    """Downgrade the database to ``revision``.

    Args:
        revision: Target revision (``base`` drops everything).
        url: Optional PostgreSQL URL (defaults to the environment).
    """
    command.downgrade(alembic_config(url), revision)
