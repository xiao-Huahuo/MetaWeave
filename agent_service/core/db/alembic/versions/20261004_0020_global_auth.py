"""Replace independent vault credentials with global accounts and fixed device grants.

The user explicitly requested a fresh start. This revision clears existing user
business rows once, removes the entire plaintext-bearing vault_profiles table,
and preserves schema/version history. Program-shipped component files are not
database records and are not touched by this migration.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261004_0020"
down_revision = "20261001_0019"
branch_labels = None
depends_on = None

# Explicit user-owned tables include relationships without their own user_id.
USER_TABLES = (
    "mcp_access_records", "mcp_credentials", "mcp_connections",
    "vault_item_tags", "vault_assets", "vault_items", "vault_tags",
    "library_item_tags", "library_assets", "library_items", "library_tags",
    "literature_reading_states", "smart_form_cells", "smart_form_columns",
    "smart_form_rows", "smart_forms", "session_attachments", "agent_messages",
    "agent_change_snapshots", "agent_token_usage", "agent_queue_tasks",
    "automation_runs", "automation_tasks", "agent_sessions", "agent_queue_settings",
    "favorites", "feedback", "privacy_records", "activity_events",
    "knowledge_graph_section_cache", "knowledge_graph_dedup_decisions",
    "knowledge_graph_edges", "knowledge_graph_nodes", "knowledge_graph_document_status",
    "knowledge_ingestion_jobs", "longterm_memory_specs", "scanner_records",
    "todo_imports", "todos", "component_library_metadata",
    "user_knowledge_libraries", "user_llm_config", "user_llm_config_presets",
    "user_vlm_config_presets", "user_system_prompts", "user_settings",
)


def upgrade() -> None:
    """Clear old user data once and create production authentication persistence."""
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # Erase deleted cells instead of leaving former plaintext in free pages.
        bind.exec_driver_sql("PRAGMA secure_delete = ON")
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for name in USER_TABLES:
        if name in tables:
            bind.execute(sa.table(name).delete())
    if "vault_profiles" in tables:
        op.drop_table("vault_profiles")

    op.create_table("accounts",
        sa.Column("user_id", sa.String(8), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("onboarding_step", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("onboarding_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("password_hash", sa.String(128), nullable=False),
        sa.Column("password_salt", sa.String(128), nullable=False),
        sa.Column("password_kdf_iterations", sa.Integer(), nullable=False),
        sa.Column("encryption_kdf_iterations", sa.Integer(), nullable=False),
        sa.Column("key_fingerprint", sa.String(64), nullable=False),
        sa.Column("password_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_accounts_username", "accounts", ["username"], unique=True)

    op.create_table("auth_access_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(8), nullable=False, index=True),
        sa.Column("device_id", sa.String(128), nullable=False, server_default="", index=True),
        sa.Column("device_credential_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("password_version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("auth_devices",
        sa.Column("device_id", sa.String(128), primary_key=True),
        sa.Column("user_id", sa.String(8), nullable=False, index=True),
        sa.Column("credential_hash", sa.String(64), nullable=False),
        sa.Column("password_version", sa.Integer(), nullable=False),
        sa.Column("key_fingerprint", sa.String(64), nullable=False),
        sa.Column("remembered_blob", sa.Text(), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_table("auth_attempts",
        sa.Column("attempt_key", sa.String(64), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=False))

    settings_columns = {column["name"] for column in inspector.get_columns("user_settings")}
    for name in ("safety_enabled", "sensitive_words_enabled"):
        if name not in settings_columns:
            op.add_column("user_settings", sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.true()))
    if "theme_mode" not in settings_columns:
        op.add_column("user_settings", sa.Column("theme_mode", sa.String(16), nullable=False, server_default="light"))


def downgrade() -> None:
    """Do not recreate removed plaintext credentials or pretend to restore deleted rows."""
    raise RuntimeError("Global account migration is irreversible; restore an explicit database backup to revert.")
