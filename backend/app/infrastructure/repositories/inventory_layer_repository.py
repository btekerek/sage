from __future__ import annotations

import uuid
from decimal import Decimal
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.aggregates.inventory_layer import InventoryLayer
from app.infrastructure.repositories.event_store_repository import EventStoreRepository


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

        first = stored_events[0]
        payload = first.payload or {}

        layer = InventoryLayer(
            product_id=uuid.UUID(payload["product_id"]) if payload.get("product_id") else uuid.uuid4(),
            quantity_received=int(payload.get("quantity_received", 0)),
            unit_cost=Decimal(str(payload.get("unit_cost", "0.00"))),
            supplier_ref=payload.get("supplier_ref", ""),
            aggregate_id=aggregate_id,
            intake_at=datetime.fromisoformat(payload["intake_at"])
            if payload.get("intake_at")
            else datetime.now(timezone.utc),
        )
        layer.version = 0
        layer.version = len(stored_events)
        return layer
