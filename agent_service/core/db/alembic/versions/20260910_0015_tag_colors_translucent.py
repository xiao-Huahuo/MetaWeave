"""Persist the optional tag translucency override.

Revision ID: 20260910_0015
Revises: 20260910_0014
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260910_0015"
down_revision = "20260910_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add a nullable override so null continues to mean service default."""

    op.add_column("user_settings", sa.Column("tag_colors_translucent", sa.Boolean(), nullable=True))


def downgrade() -> None:
    """Remove the tag translucency override."""

    op.drop_column("user_settings", "tag_colors_translucent")
