from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.domain.aggregates.base import AggregateRoot
from app.domain.aggregates.inventory_layer import InventoryLayer
from app.domain.events.events import InventoryLayerCreatedEvent
from app.infrastructure.repositories.event_store_repository import EventStoreRepository
from sqlalchemy.ext.asyncio import AsyncSession


class InventoryLayerRepository:
    """
    Loads InventoryLayer aggregates from their event stream.
    Each InventoryLayer is created once from an intake event and then
    depleted via consume() calls — state is reconstructed from the stream.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._event_store = EventStoreRepository(session)

    async def get(self, aggregate_id: uuid.UUID) -> InventoryLayer | None:
        stored_events = await self._event_store.load_stream(str(aggregate_id))
        if not stored_events:
            return None

        layer = InventoryLayer.__new__(InventoryLayer)
        AggregateRoot.__init__(layer, aggregate_id=aggregate_id)
        domain_events = [_to_domain_event(e) for e in stored_events]
        layer.load_from_history([e for e in domain_events if e is not None])
        if not hasattr(layer, "intake_at"):
            layer.intake_at = datetime.now(timezone.utc)
        return layer


def _to_domain_event(stored):
    """Map a StoredEvent row back to a domain event for replay."""
    payload = stored.payload or {}
    if stored.event_type == "InventoryLayerCreatedEvent":
        return InventoryLayerCreatedEvent(
            aggregate_id=uuid.UUID(stored.aggregate_id),
            aggregate_type=stored.aggregate_type,
            sequence_number=stored.sequence_number,
            product_id=(
                uuid.UUID(payload["product_id"])
                if payload.get("product_id")
                else uuid.uuid4()
            ),
            quantity_received=int(payload.get("quantity_received", 0)),
            unit_cost=Decimal(str(payload.get("unit_cost", "0.00"))),
            supplier_ref=payload.get("supplier_ref", ""),
        )
        return None
        return None
