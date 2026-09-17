"""Persist optional remote vision-model overrides.

Revision ID: 20260917_0018
Revises: 20260911_0017
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260917_0018"
down_revision = "20260911_0017"
branch_labels = None
depends_on = None


VISION_COLUMNS = (
    ("vision_api_key", 4096),
    ("vision_base_url", 4096),
    ("vision_model_name", 256),
)


def upgrade() -> None:
    """Add empty-by-default visual endpoint fields to each user's LLM settings."""

    with op.batch_alter_table("user_llm_config") as batch_op:
        for column_name, max_length in VISION_COLUMNS:
            batch_op.add_column(
                sa.Column(
                    column_name,
                    sa.String(length=max_length),
                    nullable=False,
                    server_default="",
                )
            )


def downgrade() -> None:
    """Remove only the optional visual endpoint fields."""

    with op.batch_alter_table("user_llm_config") as batch_op:
        for column_name, _max_length in reversed(VISION_COLUMNS):
            batch_op.drop_column(column_name)
