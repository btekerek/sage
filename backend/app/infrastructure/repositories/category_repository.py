from __future__ import annotations

import uuid

from app.domain.aggregates.category import Category
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

        first = stored_events[0]
        payload = first.payload or {}

        category = Category(
            name=payload.get("name", ""),
            aggregate_id=aggregate_id,
            parent_category_id=(
                uuid.UUID(payload["parent_category_id"])
                if payload.get("parent_category_id")
                else None
            ),
        )
        category.version = 0
        # Category has no event handlers yet; version is set from stream length
        category.version = len(stored_events)
        return category
