from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.aggregates.base import AggregateRoot
from app.domain.events.base import BaseEvent
from app.infrastructure.repositories.event_store_repository import EventStoreRepository


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
                    causation_id=str(event.causation_id) if event.causation_id else None,
                )
