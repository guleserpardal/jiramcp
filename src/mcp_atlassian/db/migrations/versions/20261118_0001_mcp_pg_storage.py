"""MCP PostgreSQL storage: oauth kv, grant index, tool call audit.

Revision ID: 0001
Revises:
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the three ``mcp_`` tables."""
    # Matches PostgreSQLStore's own DDL (py-key-value-aio 0.4.x); the store runs
    # with auto_create=False, so this is the only place the table is created.
    op.create_table(
        "mcp_oauth_kv",
        sa.Column("collection", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", pg.JSONB(), nullable=False),
        sa.Column("ttl", pg.DOUBLE_PRECISION(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("collection", "key", name=op.f("pk_mcp_oauth_kv")),
    )
    op.create_index(
        "idx_mcp_oauth_kv_expires_at",
        "mcp_oauth_kv",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )

    op.create_table(
        "mcp_grant_index",
        sa.Column("grant_id", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("product_username", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'reauth_required', 'revoked')",
            name=op.f("ck_mcp_grant_index_status"),
        ),
        sa.CheckConstraint(
            "revoked_reason IS NULL OR "
            "revoked_reason IN ('user', 'admin', 'ldap_disabled')",
            name=op.f("ck_mcp_grant_index_revoked_reason"),
        ),
        sa.PrimaryKeyConstraint("grant_id", name=op.f("pk_mcp_grant_index")),
    )
    op.create_index("ix_mcp_grant_index_user", "mcp_grant_index", ["product_username"])

    op.create_table(
        "mcp_tool_call_audit",
        sa.Column("audit_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column(
            "called_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("grant_id", sa.Text(), nullable=True),
        sa.Column("client_id", sa.Text(), nullable=True),
        sa.Column("product_username", sa.Text(), nullable=True),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "outcome IN ('ok', 'denied', 'error')",
            name=op.f("ck_mcp_tool_call_audit_outcome"),
        ),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["mcp_grant_index.grant_id"],
            name=op.f("fk_mcp_tool_call_audit_grant_id_mcp_grant_index"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("audit_id", name=op.f("pk_mcp_tool_call_audit")),
    )
    op.create_index("ix_mcp_tool_call_audit_at", "mcp_tool_call_audit", ["called_at"])
    op.create_index("ix_mcp_tool_call_audit_grant", "mcp_tool_call_audit", ["grant_id"])


def downgrade() -> None:
    """Drop the three tables (destroys stored tokens: everyone reconnects)."""
    op.drop_index("ix_mcp_tool_call_audit_grant", table_name="mcp_tool_call_audit")
    op.drop_index("ix_mcp_tool_call_audit_at", table_name="mcp_tool_call_audit")
    op.drop_table("mcp_tool_call_audit")
    op.drop_index("ix_mcp_grant_index_user", table_name="mcp_grant_index")
    op.drop_table("mcp_grant_index")
    op.drop_index("idx_mcp_oauth_kv_expires_at", table_name="mcp_oauth_kv")
    op.drop_table("mcp_oauth_kv")
