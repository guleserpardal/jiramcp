"""Table definitions for the MCP OAuth storage (source of truth for Alembic).

Three tables, all prefixed ``mcp_``:

* ``mcp_oauth_kv`` - FastMCP OAuth proxy state. Columns match the DDL of
  ``key_value.aio.stores.postgresql.PostgreSQLStore`` (py-key-value-aio 0.4.x)
  exactly; values are Fernet-encrypted by the storage wrapper. FastMCP
  collections are rows here (``collection`` column), not separate tables.
* ``mcp_grant_index`` - which grant belongs to whom. Holds no token.
  ``grant_id`` equals the ``key`` of the ``mcp-upstream-tokens`` row in
  ``mcp_oauth_kv``; this is a logical link, intentionally not a foreign key
  (kv rows expire, grant rows stay).
* ``mcp_tool_call_audit`` - tool call outcome and duration; never argument
  values. Retention: 180 days.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

GRANT_STATUSES = ("active", "reauth_required", "revoked")
REVOKE_REASONS = ("user", "admin", "ldap_disabled")
AUDIT_OUTCOMES = ("ok", "denied", "error")
AUDIT_RETENTION_DAYS = 180

metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)


def _in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


oauth_kv = sa.Table(
    "mcp_oauth_kv",
    metadata,
    sa.Column("collection", sa.Text(), nullable=False),
    sa.Column("key", sa.Text(), nullable=False),
    sa.Column("value", pg.JSONB(), nullable=False),
    sa.Column("ttl", pg.DOUBLE_PRECISION(), nullable=True),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint("collection", "key"),
)
# Same name the library would create, so an existing table is recognised.
sa.Index(
    "idx_mcp_oauth_kv_expires_at",
    oauth_kv.c.expires_at,
    postgresql_where=oauth_kv.c.expires_at.is_not(None),
)

grant_index = sa.Table(
    "mcp_grant_index",
    metadata,
    sa.Column("grant_id", sa.Text(), primary_key=True),
    sa.Column("client_id", sa.Text(), nullable=False),
    sa.Column("product_username", sa.Text(), nullable=False),
    sa.Column(
        "created_at",
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("revoked_reason", sa.Text(), nullable=True),
    sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
    sa.CheckConstraint(_in("status", GRANT_STATUSES), name="status"),
    sa.CheckConstraint(
        "revoked_reason IS NULL OR " + _in("revoked_reason", REVOKE_REASONS),
        name="revoked_reason",
    ),
)
sa.Index("ix_mcp_grant_index_user", grant_index.c.product_username)

tool_call_audit = sa.Table(
    "mcp_tool_call_audit",
    metadata,
    sa.Column("audit_id", sa.BigInteger(), sa.Identity(), primary_key=True),
    sa.Column(
        "called_at",
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Column(
        "grant_id",
        sa.Text(),
        sa.ForeignKey("mcp_grant_index.grant_id", ondelete="SET NULL"),
        nullable=True,
    ),
    sa.Column("client_id", sa.Text(), nullable=True),
    sa.Column("product_username", sa.Text(), nullable=True),
    sa.Column("tool_name", sa.Text(), nullable=False),
    sa.Column("outcome", sa.Text(), nullable=False),
    sa.Column("duration_ms", sa.Integer(), nullable=True),
    sa.CheckConstraint(_in("outcome", AUDIT_OUTCOMES), name="outcome"),
)
sa.Index("ix_mcp_tool_call_audit_at", tool_call_audit.c.called_at)
sa.Index("ix_mcp_tool_call_audit_grant", tool_call_audit.c.grant_id)
