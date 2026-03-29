"""Projectors for Category aggregate events."""

from uuid import UUID

from app.domain.events.base import BaseEvent
from app.infrastructure.projectors.base import BaseProjector
from app.infrastructure.projectors.read_entities import CategoryReadEntity
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession


class CategoryProjector(BaseProjector):
    """Projector for Category aggregate events to read model."""

    async def project(self, event: BaseEvent, session: AsyncSession) -> None:
        """
        Project a Category event into the read model.

        Handles CategoryCreatedEvent.
        """
        if event.event_type == "CategoryCreatedEvent":
            await self._handle_category_created(event, session)

    async def get_current_state(
        self, aggregate_id: str, session: AsyncSession
    ) -> CategoryReadEntity | None:
        """Retrieve the current category read model."""
        stmt = select(CategoryReadEntity).where(
            CategoryReadEntity.id == UUID(aggregate_id)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def _handle_category_created(
        self, event: BaseEvent, session: AsyncSession
    ) -> None:
        """Handle CategoryCreatedEvent projection."""
        payload = event.to_dict().get("payload", {})
        stmt = insert(CategoryReadEntity).values(
            id=event.aggregate_id,
            name=payload.get("name"),
            description=None,
            created_at=event.occurred_at,
            version=event.sequence_number,
        )
        await session.execute(stmt)
