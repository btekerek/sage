"""Projectors for InventoryLayer aggregate events."""

from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.events.base import BaseEvent
from app.infrastructure.projectors.base import BaseProjector
from app.infrastructure.projectors.read_entities import InventoryLayerReadEntity


class InventoryLayerProjector(BaseProjector):

    async def project(self, event: BaseEvent, session: AsyncSession) -> None:
        if event.event_type == "InventoryLayerCreatedEvent":
            await self._handle_inventory_layer_created(event, session)
        elif event.event_type == "InventoryIntakeEvent":
            await self._handle_inventory_intake(event, session)

    async def get_current_state(
        self, aggregate_id: str, session: AsyncSession
    ) -> InventoryLayerReadEntity | None:
        stmt = select(InventoryLayerReadEntity).where(
            InventoryLayerReadEntity.id == UUID(aggregate_id)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def _handle_inventory_layer_created(
        self, event: BaseEvent, session: AsyncSession
    ) -> None:
        payload = event.to_dict().get("payload", {})
        stmt = (
            pg_insert(InventoryLayerReadEntity)
            .values(
                id=event.aggregate_id,
                product_id=UUID(payload.get("product_id")),
                layer_name=payload.get("supplier_ref", "layer"),
                quantity=int(payload.get("quantity_received", 0)),
                created_at=event.occurred_at,
                version=event.sequence_number,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "quantity": int(payload.get("quantity_received", 0)),
                    "version": event.sequence_number,
                },
            )
        )
        await session.execute(stmt)

    async def _handle_inventory_intake(
        self, event: BaseEvent, session: AsyncSession
    ) -> None:
        payload = event.to_dict().get("payload", {})
        stmt = (
            update(InventoryLayerReadEntity)
            .where(InventoryLayerReadEntity.id == event.aggregate_id)
            .values(
                quantity=int(payload.get("quantity_received", 0)),
                last_intake_at=event.occurred_at,
                version=event.sequence_number,
            )
        )
        await session.execute(stmt)