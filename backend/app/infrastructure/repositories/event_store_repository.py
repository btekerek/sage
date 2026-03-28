from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.event_store.models import StoredEvent


class EventStoreRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_last_sequence_number(self, aggregate_id: str) -> int:
        stmt = select(func.max(StoredEvent.sequence_number)).where(
            StoredEvent.aggregate_id == aggregate_id
        )
        result = await self.session.execute(stmt)
        max_sequence = result.scalar_one()
        return max_sequence or 0

    async def append_event(
        self,
        *,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, Any],
        actor_id: str | None = None,
        causation_id: str | None = None,
        correlation_id: str | None = None,
        event_version: int = 1,
        expected_sequence: int | None = None,
    ) -> StoredEvent:
        last_sequence = await self.get_last_sequence_number(aggregate_id)

        if expected_sequence is not None and last_sequence != expected_sequence:
            raise ValueError(
                f"Concurrency conflict for aggregate {aggregate_id}: "
                f"expected {expected_sequence}, found {last_sequence}"
            )

        event = StoredEvent(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            event_version=event_version,
            sequence_number=last_sequence + 1,
            actor_id=actor_id,
            causation_id=causation_id,
            correlation_id=correlation_id,
            payload=payload,
        )
        self.session.add(event)

        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ValueError("Event append failed due to sequence conflict.") from exc

        return event

    async def load_stream(self, aggregate_id: str) -> list[StoredEvent]:
        stmt = (
            select(StoredEvent)
            .where(StoredEvent.aggregate_id == aggregate_id)
            .order_by(StoredEvent.sequence_number.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())