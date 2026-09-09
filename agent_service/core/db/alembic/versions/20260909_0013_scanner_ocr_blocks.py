"""Persist structured OCR blocks for scanner preview overlays.

Revision ID: 20260909_0013
Revises: 20260909_0012
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260909_0013"
down_revision = "20260909_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the JSON block payload without rewriting existing drafts."""

    op.add_column("scanner_records", sa.Column("ocr_blocks_json", sa.Text(), nullable=False, server_default="[]"))


def downgrade() -> None:
    """Remove scanner OCR block persistence."""

    op.drop_column("scanner_records", "ocr_blocks_json")
