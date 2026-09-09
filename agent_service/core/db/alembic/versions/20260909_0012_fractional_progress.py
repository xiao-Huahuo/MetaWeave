"""Store scanner and ingestion percentages with one-decimal precision.

Revision ID: 20260909_0012
Revises: 20260908_0011
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260909_0012"
down_revision = "20260908_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Change persisted progress columns from integer to floating point."""

    with op.batch_alter_table("knowledge_ingestion_jobs") as batch_op:
        batch_op.alter_column("progress", existing_type=sa.Integer(), type_=sa.Float(), existing_nullable=False)
    with op.batch_alter_table("scanner_records") as batch_op:
        batch_op.alter_column("progress", existing_type=sa.Integer(), type_=sa.Float(), existing_nullable=False)


def downgrade() -> None:
    """Restore integer progress storage for the previous schema revision."""

    with op.batch_alter_table("scanner_records") as batch_op:
        batch_op.alter_column("progress", existing_type=sa.Float(), type_=sa.Integer(), existing_nullable=False)
    with op.batch_alter_table("knowledge_ingestion_jobs") as batch_op:
        batch_op.alter_column("progress", existing_type=sa.Float(), type_=sa.Integer(), existing_nullable=False)
