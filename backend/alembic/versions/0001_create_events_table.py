"""create events table

Revision ID: 0001_create_events_table
Revises: None
Create Date: 2026-03-28 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0001_create_events_table"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("aggregate_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_id", sa.String(length=100), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "occurred_at_utc",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("actor_id", sa.String(length=100), nullable=True),
        sa.Column("causation_id", sa.String(length=100), nullable=True),
        sa.Column("correlation_id", sa.String(length=100), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
        sa.UniqueConstraint(
            "aggregate_id",
            "sequence_number",
            name="uq_events_aggregate_sequence",
        ),
    )
    op.create_index("ix_events_aggregate_id", "events", ["aggregate_id"], unique=False)
    op.create_index("ix_events_aggregate_type", "events", ["aggregate_type"], unique=False)
    op.create_index("ix_events_occurred_at_utc", "events", ["occurred_at_utc"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_events_occurred_at_utc", table_name="events")
    op.drop_index("ix_events_aggregate_type", table_name="events")
    op.drop_index("ix_events_aggregate_id", table_name="events")
    op.drop_table("events")