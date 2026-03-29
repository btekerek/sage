from __future__ import annotations

from typing import Any

from app.domain.aggregates.base import AggregateRoot
from app.domain.events.base import BaseEvent
from app.infrastructure.projectors.base import BaseProjector
from app.infrastructure.repositories.event_store_repository import EventStoreRepository
from sqlalchemy.ext.asyncio import AsyncSession


class UnitOfWork:
    """
    Wraps a single database transaction.

    Usage:
        async with UnitOfWork(session) as uow:
            product = Product(...)
            product.apply_price_override(...)
            uow.track(product)
        # on __aexit__ all pending events are flushed and the transaction commits
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tracked: list[AggregateRoot] = []
        self.event_store = EventStoreRepository(session)

    # ── Tracking ────────────────────────────────────────────────

    def track(self, aggregate: AggregateRoot) -> None:
        """Register an aggregate whose pending events should be saved on commit."""
        self._tracked.append(aggregate)

    # ── Context manager ─────────────────────────────────────────

    async def __aenter__(self) -> "UnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is None:
            await self.commit()
        else:
            await self.rollback()

    # ── Persistence ─────────────────────────────────────────────

    async def commit(self) -> None:
        """Flush all pending events from tracked aggregates, then commit."""
        await self._flush_events()
        await self._session.commit()
        self._tracked.clear()

    async def rollback(self) -> None:
        await self._session.rollback()
        self._tracked.clear()

    # ── Internal ────────────────────────────────────────────────

    async def _flush_events(self) -> None:
        for aggregate in self._tracked:
            events: list[BaseEvent] = aggregate.collect_events()
            for event in events:
                await self.event_store.append_event(
                    aggregate_type=event.aggregate_type,
                    aggregate_id=str(event.aggregate_id),
                    event_type=event.event_type,
                    payload=event.to_dict().get("payload", {}),
                    causation_id=(
                        str(event.causation_id) if event.causation_id else None
                    ),
                )
                # Project event to read model
                await self._project_event(event)

    async def _project_event(self, event: BaseEvent) -> None:
        """Project an event to the appropriate read model."""
        # Lazy import to avoid circular dependencies
        from app.infrastructure.projectors.category_projector import CategoryProjector
        from app.infrastructure.projectors.draft_sale_projector import (
            DraftSaleProjector,
        )
        from app.infrastructure.projectors.inventory_layer_projector import (
            InventoryLayerProjector,
        )
        from app.infrastructure.projectors.product_projector import ProductProjector

        projector: BaseProjector[Any] | None = None
        if event.aggregate_type == "Product":
            projector = ProductProjector()
        elif event.aggregate_type == "Category":
            projector = CategoryProjector()
        elif event.aggregate_type == "InventoryLayer":
            projector = InventoryLayerProjector()
        elif event.aggregate_type == "DraftSale":
            projector = DraftSaleProjector()

        if projector is not None:
            await projector.project(event, self._session)
            await projector.project(event, self._session)
