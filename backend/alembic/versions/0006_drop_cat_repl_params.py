# mypy: disable-error-code=import-not-found
# pyright: reportMissingImports=false
"""Drop per-category replenishment columns (feature removed).

Resolution is now: product override → global system config only.

Revision ID: 0006_drop_cat_repl
Revises: 0005_category_repl_params
Create Date: 2026-05-01 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_drop_cat_repl"
down_revision = "0005_category_repl_params"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("category_read", "target_coverage_days")
    op.drop_column("category_read", "lead_time_days")


def downgrade() -> None:
    op.add_column(
        "category_read",
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
    )
    op.add_column(
        "category_read",
        sa.Column("target_coverage_days", sa.Integer(), nullable=True),
    )
