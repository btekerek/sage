from __future__ import annotations

import uuid
from decimal import Decimal

from app.domain.aggregates.base import AggregateRoot
from app.domain.aggregates.draft_sale import DraftSale
from app.domain.events.events import (
    DraftSaleCreatedEvent,
    LineItemAddedEvent,
    LineItemRemovedEvent,
    LineItemUpdatedEvent,
    SaleEvent,
    SaleLineItem,
    VoidEvent,
)
from app.infrastructure.repositories.event_store_repository import EventStoreRepository
from sqlalchemy.ext.asyncio import AsyncSession


class DraftSaleRepository:
    """
    Loads DraftSale aggregates from their event stream.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._event_store = EventStoreRepository(session)

    async def get(self, aggregate_id: uuid.UUID) -> DraftSale | None:
        """
        Reconstruct a DraftSale from its event history.
        Returns None if no events exist for the given id.
        """
        stored_events = await self._event_store.load_stream(str(aggregate_id))
        if not stored_events:
            return None

        sale = DraftSale.__new__(DraftSale)
        AggregateRoot.__init__(sale, aggregate_id=aggregate_id)
        domain_events = [_to_domain_event(e) for e in stored_events]
        sale.load_from_history([e for e in domain_events if e is not None])
        return sale


def _to_domain_event(stored):
    """Map a StoredEvent row back to a domain event for replay."""
    payload = stored.payload or {}
    if stored.event_type == "DraftSaleCreatedEvent":
        return DraftSaleCreatedEvent(
            aggregate_id=uuid.UUID(stored.aggregate_id),
            aggregate_type=stored.aggregate_type,
            sequence_number=stored.sequence_number,
            operator_id=(
                uuid.UUID(payload["operator_id"])
                if payload.get("operator_id")
                else uuid.uuid4()
            ),
            session_id=(
                uuid.UUID(payload["session_id"])
                if payload.get("session_id")
                else uuid.uuid4()
            ),
        )
    elif stored.event_type == "LineItemAddedEvent":
        return LineItemAddedEvent(
            aggregate_id=uuid.UUID(stored.aggregate_id),
            aggregate_type=stored.aggregate_type,
            sequence_number=stored.sequence_number,
            product_id=(
                uuid.UUID(payload["product_id"])
                if payload.get("product_id")
                else uuid.uuid4()
            ),
            product_name=payload.get("product_name", ""),
            unit_price=Decimal(str(payload.get("unit_price", "0.00"))),
            quantity=int(payload.get("quantity", 0)),
        )
    elif stored.event_type == "LineItemRemovedEvent":
        return LineItemRemovedEvent(
            aggregate_id=uuid.UUID(stored.aggregate_id),
            aggregate_type=stored.aggregate_type,
            sequence_number=stored.sequence_number,
            product_id=(
                uuid.UUID(payload["product_id"])
                if payload.get("product_id")
                else uuid.uuid4()
            ),
        )
    elif stored.event_type == "LineItemUpdatedEvent":
        return LineItemUpdatedEvent(
            aggregate_id=uuid.UUID(stored.aggregate_id),
            aggregate_type=stored.aggregate_type,
            sequence_number=stored.sequence_number,
            product_id=(
                uuid.UUID(payload["product_id"])
                if payload.get("product_id")
                else uuid.uuid4()
            ),
            quantity=int(payload.get("quantity", 0)),
        )
    elif stored.event_type == "SaleEvent":
        return SaleEvent(
            aggregate_id=uuid.UUID(stored.aggregate_id),
            aggregate_type=stored.aggregate_type,
            sequence_number=stored.sequence_number,
            operator_id=(
                uuid.UUID(payload["operator_id"])
                if payload.get("operator_id")
                else uuid.uuid4()
            ),
            session_id=(
                uuid.UUID(payload["session_id"])
                if payload.get("session_id")
                else uuid.uuid4()
            ),
            payment_method=payload.get("payment_method", ""),
            total_amount=Decimal(str(payload.get("total_amount", "0.00"))),
        )
    elif stored.event_type == "VoidEvent":
        return VoidEvent(
            aggregate_id=uuid.UUID(stored.aggregate_id),
            aggregate_type=stored.aggregate_type,
            sequence_number=stored.sequence_number,
            operator_id=(
                uuid.UUID(payload["operator_id"])
                if payload.get("operator_id")
                else uuid.uuid4()
            ),
            session_id=(
                uuid.UUID(payload["session_id"])
                if payload.get("session_id")
                else uuid.uuid4()
            ),
            reason=payload.get("reason", ""),
        )
    return None
