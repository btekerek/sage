from __future__ import annotations

import uuid

from app.domain.aggregates.base import AggregateRoot
from app.domain.aggregates.category import Category
from app.domain.events.events import CategoryCreatedEvent
from app.infrastructure.repositories.event_store_repository import EventStoreRepository
from sqlalchemy.ext.asyncio import AsyncSession


class CategoryRepository:
    """
    Loads Category aggregates from their event stream.
    Category has no state-mutating events yet — this supports future extension.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._event_store = EventStoreRepository(session)

    async def get(self, aggregate_id: uuid.UUID) -> Category | None:
        stored_events = await self._event_store.load_stream(str(aggregate_id))
        if not stored_events:
            return None

        category = Category.__new__(Category)
        AggregateRoot.__init__(category, aggregate_id=aggregate_id)
        domain_events = [_to_domain_event(e) for e in stored_events]
        category.load_from_history([e for e in domain_events if e is not None])
        return category


def _to_domain_event(stored):
    """Map a StoredEvent row back to a domain event for replay."""
    payload = stored.payload or {}
    if stored.event_type == "CategoryCreatedEvent":
        return CategoryCreatedEvent(
            aggregate_id=uuid.UUID(stored.aggregate_id),
            aggregate_type=stored.aggregate_type,
            sequence_number=stored.sequence_number,
            name=payload.get("name", ""),
            parent_category_id=(
                uuid.UUID(payload["parent_category_id"])
                if payload.get("parent_category_id")
                else None
            ),
        )
        return None
        return None
