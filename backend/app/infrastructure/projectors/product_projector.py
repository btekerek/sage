"""Projectors for Product aggregate events."""

from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.events.base import BaseEvent
from app.infrastructure.projectors.base import BaseProjector
from app.infrastructure.projectors.read_entities import ProductReadEntity


class ProductProjector(BaseProjector):

    async def project(self, event: BaseEvent, session: AsyncSession) -> None:
        if event.event_type == "ProductCreatedEvent":
            await self._handle_product_created(event, session)
        elif event.event_type == "PriceOverrideEvent":
            await self._handle_price_overridden(event, session)

    async def get_current_state(
        self, aggregate_id: str, session: AsyncSession
    ) -> ProductReadEntity | None:
        stmt = select(ProductReadEntity).where(
            ProductReadEntity.id == UUID(aggregate_id)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def _handle_product_created(
        self, event: BaseEvent, session: AsyncSession
    ) -> None:
        payload = event.to_dict().get("payload", {})
        stmt = (
            pg_insert(ProductReadEntity)
            .values(
                id=event.aggregate_id,
                name=payload.get("name"),
                category_id=UUID(payload.get("category_id")),
                base_price=float(payload.get("unit_price", 0)),
                current_price=float(payload.get("unit_price", 0)),
                created_at=event.occurred_at,
                version=event.sequence_number,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "name": payload.get("name"),
                    "current_price": float(payload.get("unit_price", 0)),
                    "version": event.sequence_number,
                },
            )
        )
        await session.execute(stmt)

    async def _handle_price_overridden(
        self, event: BaseEvent, session: AsyncSession
    ) -> None:
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