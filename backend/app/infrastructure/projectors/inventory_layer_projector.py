"""Projectors for InventoryLayer aggregate events."""

from uuid import UUID

from app.domain.events.base import BaseEvent
from app.infrastructure.projectors.base import BaseProjector
from app.infrastructure.projectors.read_entities import InventoryLayerReadEntity
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession


class InventoryLayerProjector(BaseProjector):
    """Projector for InventoryLayer aggregate events to read model."""

    async def project(self, event: BaseEvent, session: AsyncSession) -> None:
        """
        Project an InventoryLayer event into the read model.

        Handles InventoryLayerCreatedEvent and InventoryIntakeEvent.
        """
        if event.event_type == "InventoryLayerCreatedEvent":
            await self._handle_inventory_layer_created(event, session)
        elif event.event_type == "InventoryIntakeEvent":
            await self._handle_inventory_intake(event, session)

    async def get_current_state(
        self, aggregate_id: str, session: AsyncSession
    ) -> InventoryLayerReadEntity | None:
        """Retrieve the current inventory layer read model."""
        stmt = select(InventoryLayerReadEntity).where(
            InventoryLayerReadEntity.id == UUID(aggregate_id)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def _handle_inventory_layer_created(
        self, event: BaseEvent, session: AsyncSession
    ) -> None:
        """Handle InventoryLayerCreatedEvent projection."""
        payload = event.to_dict().get("payload", {})
        stmt = insert(InventoryLayerReadEntity).values(
            id=event.aggregate_id,
            product_id=UUID(payload.get("product_id")),
            layer_name=payload.get("supplier_ref", "layer"),
            quantity=int(payload.get("quantity_received", 0)),
            created_at=event.occurred_at,
            version=event.sequence_number,
        )
        await session.execute(stmt)

    async def _handle_inventory_intake(
        self, event: BaseEvent, session: AsyncSession
    ) -> None:
        """Handle InventoryIntakeEvent projection."""
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
        await session.execute(stmt)
