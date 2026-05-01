# mypy: disable-error-code=import-not-found
# pyright: reportMissingImports=false
"""Add per-product replenishment parameters to product_read.

lead_time_days       — nullable INT; overrides global replenishment_lead_time_days
target_coverage_days — nullable INT; overrides global replenishment_target_days

When NULL the MILP engine falls back to the system-wide config value.

Revision ID: 0004_repl_params
Revises: 0003_create_users_table
Create Date: 2026-05-01 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_repl_params"
down_revision = "0003_create_users_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product_read",
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
    )
    op.add_column(
        "product_read",
        sa.Column("target_coverage_days", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("product_read", "target_coverage_days")
    op.drop_column("product_read", "lead_time_days")
