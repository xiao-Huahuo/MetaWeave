"""Persist reusable MinerU VLM configuration presets.

Revision ID: 20260911_0017
Revises: 20260911_0016
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260911_0017"
down_revision = "20260911_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the user-owned MinerU preset table and lookup index."""

    op.create_table(
        "user_vlm_config_presets",
        sa.Column("config_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=256), nullable=False),
        sa.Column("label", sa.String(length=256), nullable=False),
        sa.Column("api_key", sa.String(length=4096), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), nullable=False),
        sa.Column("max_file_bytes", sa.Integer(), nullable=False),
        sa.Column("max_pages", sa.Integer(), nullable=False),
        sa.Column("submit_rate_per_minute", sa.Integer(), nullable=False),
        sa.Column("result_rate_per_minute", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("config_id"),
    )
    op.create_index(op.f("ix_user_vlm_config_presets_user_id"), "user_vlm_config_presets", ["user_id"], unique=False)


def downgrade() -> None:
    """Remove reusable MinerU configuration presets."""

    op.drop_index(op.f("ix_user_vlm_config_presets_user_id"), table_name="user_vlm_config_presets")
    op.drop_table("user_vlm_config_presets")
