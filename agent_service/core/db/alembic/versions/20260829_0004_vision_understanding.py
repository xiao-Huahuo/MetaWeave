"""Add the opt-in user setting for remote image understanding.

Revision ID: 20260829_0004
Revises: 20260829_0003
Create Date: 2026-08-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260829_0004"
down_revision: str | Sequence[str] | None = "20260829_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist image understanding as an explicit opt-in user setting."""

    with op.batch_alter_table("user_settings") as batch_op:
        batch_op.add_column(
            sa.Column("vision_understanding_enabled", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    """Remove the image-understanding preference."""

    with op.batch_alter_table("user_settings") as batch_op:
        batch_op.drop_column("vision_understanding_enabled")
