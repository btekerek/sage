"""Projectors for Category aggregate events."""

from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.events.base import BaseEvent
from app.infrastructure.projectors.base import BaseProjector
from app.infrastructure.projectors.read_entities import CategoryReadEntity


class CategoryProjector(BaseProjector):

    async def project(self, event: BaseEvent, session: AsyncSession) -> None:
        if event.event_type == "CategoryCreatedEvent":
            await self._handle_category_created(event, session)

    async def get_current_state(
        self, aggregate_id: str, session: AsyncSession
    ) -> CategoryReadEntity | None:
        stmt = select(CategoryReadEntity).where(
            CategoryReadEntity.id == UUID(aggregate_id)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def _handle_category_created(
        self, event: BaseEvent, session: AsyncSession
    ) -> None:
        payload = event.to_dict().get("payload", {})
        stmt = (
            pg_insert(CategoryReadEntity)
            .values(
                id=event.aggregate_id,
                name=payload.get("name"),
                description=None,
                created_at=event.occurred_at,
                version=event.sequence_number,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "name": payload.get("name"),
                    "version": event.sequence_number,
                },
            )
        )
        await session.execute(stmt)