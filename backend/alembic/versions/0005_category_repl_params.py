# mypy: disable-error-code=import-not-found
# pyright: reportMissingImports=false
"""Add per-category replenishment defaults to category_read.

lead_time_days       — nullable INT; default lead time for products in this category
target_coverage_days — nullable INT; default coverage horizon for products in this category

Resolution order in replenishment engine:
  product override > category default > global system config

Revision ID: 0005_category_repl_params
Revises: 0004_repl_params
Create Date: 2026-05-01 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_category_repl_params"
down_revision = "0004_repl_params"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "category_read",
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
    )
    op.add_column(
        "category_read",
        sa.Column("target_coverage_days", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("category_read", "target_coverage_days")
    op.drop_column("category_read", "lead_time_days")
