"""Persist MCP user overrides, encrypted connections, hashed credentials and redacted call outcomes."""
import sqlalchemy as sa
from alembic import op

revision = "20261001_0019"
down_revision = "20260917_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create only MCP-owned tables and the user override column."""
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "mcp_settings" not in {column["name"] for column in inspector.get_columns("user_settings")}:
        op.add_column("user_settings", sa.Column("mcp_settings", sa.Text(), nullable=False, server_default=""))
    if "mcp_connections" not in tables:
        op.create_table("mcp_connections",
            sa.Column("connection_id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), nullable=False, index=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("encrypted_secrets", sa.String(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("user_id", "name"))
    if "mcp_credentials" not in tables:
        op.create_table("mcp_credentials",
            sa.Column("credential_id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), nullable=False, index=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("token_hash", sa.String(), nullable=False, unique=True, index=True),
            sa.Column("token_prefix", sa.String(), nullable=False),
            sa.Column("grants", sa.JSON(), nullable=False),
            sa.Column("revoked", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False))
    if "mcp_access_records" not in tables:
        op.create_table("mcp_access_records",
            sa.Column("record_id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), nullable=False, index=True),
            sa.Column("credential_id", sa.String(), nullable=False),
            sa.Column("tool_name", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("duration_ms", sa.Integer(), nullable=False),
            sa.Column("message", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, index=True))


def downgrade() -> None:
    """Remove MCP records and overrides only."""
    for table in ("mcp_access_records", "mcp_credentials", "mcp_connections"):
        op.drop_table(table)
    op.drop_column("user_settings", "mcp_settings")
