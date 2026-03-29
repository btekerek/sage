"""Projectors for Product aggregate events."""

from uuid import UUID

from app.domain.events.base import BaseEvent
from app.infrastructure.projectors.base import BaseProjector
from app.infrastructure.projectors.read_entities import ProductReadEntity
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession


class ProductProjector(BaseProjector):
    """Projector for Product aggregate events to read model."""

    async def project(self, event: BaseEvent, session: AsyncSession) -> None:
        """
        Project a Product event into the read model.

        Handles ProductCreatedEvent and ProductPriceOverriddenEvent.
        """
        if event.event_type == "ProductCreatedEvent":
            await self._handle_product_created(event, session)
        elif event.event_type == "PriceOverrideEvent":
            await self._handle_price_overridden(event, session)

    async def get_current_state(
        self, aggregate_id: str, session: AsyncSession
    ) -> ProductReadEntity | None:
        """Retrieve the current product read model."""
        stmt = select(ProductReadEntity).where(
            ProductReadEntity.id == UUID(aggregate_id)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def _handle_product_created(
        self, event: BaseEvent, session: AsyncSession
    ) -> None:
        """Handle ProductCreatedEvent projection."""
        payload = event.to_dict().get("payload", {})
        stmt = insert(ProductReadEntity).values(
            id=event.aggregate_id,
            name=payload.get("name"),
            category_id=UUID(payload.get("category_id")),
            base_price=float(payload.get("unit_price", 0)),
            current_price=float(payload.get("unit_price", 0)),
            created_at=event.occurred_at,
            version=event.sequence_number,
        )
        await session.execute(stmt)

    async def _handle_price_overridden(
        self, event: BaseEvent, session: AsyncSession
    ) -> None:
        """Handle ProductPriceOverriddenEvent projection."""
        payload = event.to_dict().get("payload", {})
        stmt = (
            update(ProductReadEntity)
            .where(ProductReadEntity.id == event.aggregate_id)
            .values(
                current_price=float(payload.get("new_price", 0)),
                last_price_override_at=event.occurred_at,
                version=event.sequence_number,
            )
        )
        await session.execute(stmt)
