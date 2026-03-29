"""Read models (Pydantic schemas) for query endpoints."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class ProductReadModel(BaseModel):
    """Read model for Product aggregate."""

    id: UUID
    name: str
    category_id: UUID
    base_price: Decimal
    current_price: Decimal
    last_price_override_at: datetime | None = None
    created_at: datetime
    version: int

    model_config = {"from_attributes": True}


class CategoryReadModel(BaseModel):
    """Read model for Category aggregate."""

    id: UUID
    name: str
    description: str | None = None
    created_at: datetime
    version: int

    model_config = {"from_attributes": True}


class InventoryLayerReadModel(BaseModel):
    """Read model for InventoryLayer aggregate."""

    id: UUID
    product_id: UUID
    layer_name: str
    quantity: int
    last_intake_at: datetime | None = None
    created_at: datetime
    version: int

    model_config = {"from_attributes": True}


class DraftSaleLineItemRead(BaseModel):
    """Nested read model for a draft sale line item."""

    product_id: UUID
    quantity: int
    unit_price: Decimal


class DraftSaleReadModel(BaseModel):
    """Read model for DraftSale aggregate."""

    id: UUID
    customer_id: str
    line_items: list[DraftSaleLineItemRead] = Field(default_factory=list)
    total_amount: Decimal
    status: str  # "draft", "finalized", "voided"
    created_at: datetime
    version: int

    model_config = {"from_attributes": True}


class EventStreamEntry(BaseModel):
    """A single entry in an event stream for query responses."""

    sequence_number: int
    event_type: str
    payload: dict
    created_at: datetime


class AggregateStreamResponse(BaseModel):
    """Response containing the event stream for an aggregate."""

    aggregate_id: UUID
    event_stream: list[EventStreamEntry]
