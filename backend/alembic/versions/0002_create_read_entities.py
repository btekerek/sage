"""Create read-side projection tables.

Revision ID: 0002_create_read_entities
Revises: 0001_create_events_table
Create Date: 2026-03-28 10:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "0002_create_read_entities"
down_revision = "0001_create_events_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create read-side projection tables."""
    # Create product_read table
    op.create_table(
        "product_read",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category_id", sa.UUID(), nullable=False),
        sa.Column("base_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("current_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("last_price_override_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            onupdate=sa.func.now(),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create category_read table
    op.create_table(
        "category_read",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            onupdate=sa.func.now(),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create inventory_layer_read table
    op.create_table(
        "inventory_layer_read",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("layer_name", sa.String(255), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_intake_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            onupdate=sa.func.now(),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create draft_sale_read table
    op.create_table(
        "draft_sale_read",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.String(255), nullable=False),
        sa.Column(
            "total_amount", sa.Numeric(12, 2), nullable=False, server_default="0.0"
        ),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column("line_items_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            onupdate=sa.func.now(),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Drop read-side projection tables."""
    op.drop_table("draft_sale_read")
    op.drop_table("inventory_layer_read")
    op.drop_table("category_read")
    op.drop_table("product_read")