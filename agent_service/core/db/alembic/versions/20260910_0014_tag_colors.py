"""Persist user tag-color palette overrides.

Revision ID: 20260910_0014
Revises: 20260909_0013
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260910_0014"
down_revision = "20260909_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the optional six-color JSON palette override."""

    op.add_column("user_settings", sa.Column("tag_colors", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    """Remove user tag-color palette overrides."""

    op.drop_column("user_settings", "tag_colors")
