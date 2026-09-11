"""Persist MinerU VLM settings and scanner parser provenance.

Revision ID: 20260911_0016
Revises: 20260910_0015
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260911_0016"
down_revision = "20260910_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add user VLM overrides and immutable scanner parser selection fields."""

    op.add_column("user_settings", sa.Column("vlm_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("user_settings", sa.Column("vlm_api_key", sa.String(length=1024), nullable=False, server_default=""))
    op.add_column("user_settings", sa.Column("vlm_model", sa.String(length=64), nullable=False, server_default=""))
    for name in (
        "vlm_max_concurrency",
        "vlm_max_file_bytes",
        "vlm_max_pages",
        "vlm_submit_rate_per_minute",
        "vlm_result_rate_per_minute",
    ):
        op.add_column("user_settings", sa.Column(name, sa.Integer(), nullable=False, server_default="0"))
    op.add_column("scanner_records", sa.Column("online_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("scanner_records", sa.Column("parser_engine", sa.String(length=64), nullable=False, server_default="pending"))
    op.add_column("scanner_records", sa.Column("parser_fallback_reason", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    """Remove MinerU user settings and scanner parser provenance."""

    for name in ("parser_fallback_reason", "parser_engine", "online_enabled"):
        op.drop_column("scanner_records", name)
    for name in (
        "vlm_result_rate_per_minute",
        "vlm_submit_rate_per_minute",
        "vlm_max_pages",
        "vlm_max_file_bytes",
        "vlm_max_concurrency",
        "vlm_model",
        "vlm_api_key",
        "vlm_enabled",
    ):
        op.drop_column("user_settings", name)
