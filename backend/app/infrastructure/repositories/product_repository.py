from __future__ import annotations

import uuid
from decimal import Decimal

from app.domain.aggregates.product import Product
from app.domain.events.events import PriceOverrideEvent
from app.infrastructure.repositories.event_store_repository import EventStoreRepository
from sqlalchemy.ext.asyncio import AsyncSession


class ProductRepository:
    """
    Loads and persists Product aggregates via the event stream.
    Does NOT commit — commit is the UnitOfWork's responsibility.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._event_store = EventStoreRepository(session)

    async def get(self, aggregate_id: uuid.UUID) -> Product | None:
        """
        Reconstruct a Product from its event history.
        Returns None if no events exist for the given id.
        """
        stored_events = await self._event_store.load_stream(str(aggregate_id))
        if not stored_events:
            return None

        # Peek at the first event to recover constructor arguments
        first = stored_events[0]
        payload = first.payload or {}

        product = Product.__new__(Product)
        Product.__init__(
            product,
            name=payload.get("name", ""),
            unit_price=Decimal(str(payload.get("unit_price", "0.00"))),
            category_id=(
                uuid.UUID(payload["category_id"])
                if payload.get("category_id")
                else uuid.uuid4()
            ),
            aggregate_id=aggregate_id,
            is_active=payload.get("is_active", True),
        )
        # Reset version — load_from_history will increment it per event
        product.version = 0

        domain_events = [_to_domain_event(e) for e in stored_events]
        product.load_from_history(domain_events)
        return product


# ── Helpers ──────────────────────────────────────────────────────


def _to_domain_event(stored):
    """Map a StoredEvent row back to a domain event object for replay."""
    payload = stored.payload or {}
    if stored.event_type == "PriceOverrideEvent":
        return PriceOverrideEvent(
            aggregate_id=uuid.UUID(stored.aggregate_id),
            aggregate_type=stored.aggregate_type,
            sequence_number=stored.sequence_number,
            product_id=uuid.UUID(payload.get("product_id", stored.aggregate_id)),
            previous_price=Decimal(str(payload.get("previous_price", "0.00"))),
            new_price=Decimal(str(payload.get("new_price", "0.00"))),
            authorized_by=(
                uuid.UUID(payload["authorized_by"])
                if payload.get("authorized_by")
                else uuid.uuid4()
            ),
        )
    # Unknown event types are skipped during replay
    return None
