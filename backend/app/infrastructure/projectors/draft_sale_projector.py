"""Projectors for DraftSale aggregate events."""

import json
from decimal import Decimal
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.events.base import BaseEvent
from app.infrastructure.projectors.base import BaseProjector
from app.infrastructure.projectors.read_entities import (
    DraftSaleReadEntity,
    InventoryLayerReadEntity,
)


class DraftSaleProjector(BaseProjector):

    async def project(self, event: BaseEvent, session: AsyncSession) -> None:
        if event.event_type == "DraftSaleCreatedEvent":
            await self._handle_draft_sale_created(event, session)
        elif event.event_type == "LineItemAddedEvent":
            await self._handle_line_item_added(event, session)
        elif event.event_type == "LineItemRemovedEvent":
            await self._handle_line_item_removed(event, session)
        elif event.event_type == "LineItemUpdatedEvent":
            await self._handle_line_item_updated(event, session)
        elif event.event_type == "SaleEvent":
            await self._handle_sale_finalized(event, session)
        elif event.event_type == "VoidEvent":
            await self._handle_sale_voided(event, session)

    async def get_current_state(
        self, aggregate_id: str, session: AsyncSession
    ) -> DraftSaleReadEntity | None:
        stmt = select(DraftSaleReadEntity).where(
            DraftSaleReadEntity.id == UUID(aggregate_id)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def _handle_draft_sale_created(
        self, event: BaseEvent, session: AsyncSession
    ) -> None:
        payload = event.to_dict().get("payload", {})
        stmt = (
            pg_insert(DraftSaleReadEntity)
            .values(
                id=event.aggregate_id,
                customer_id=payload.get("operator_id"),
                total_amount=0.0,
                status="draft",
                line_items_json="[]",
                created_at=event.occurred_at,
                version=event.sequence_number,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "status": "draft",
                    "line_items_json": "[]",
                    "total_amount": 0.0,
                    "version": event.sequence_number,
                },
            )
        )
        await session.execute(stmt)

    async def _handle_line_item_added(
        self, event: BaseEvent, session: AsyncSession
    ) -> None:
        entity = await self.get_current_state(str(event.aggregate_id), session)
        if not entity:
            return

        payload = event.to_dict().get("payload", {})
        line_items = json.loads(entity.line_items_json or "[]")
        new_item = {
            "product_id": payload.get("product_id"),
            "quantity": int(payload.get("quantity", 0)),
            "unit_price": float(payload.get("unit_price", 0)),
        }
        line_items.append(new_item)
        total = sum(
            Decimal(str(i["quantity"])) * Decimal(str(i["unit_price"]))
            for i in line_items
        )
        stmt = (
            update(DraftSaleReadEntity)
            .where(DraftSaleReadEntity.id == event.aggregate_id)
            .values(
                line_items_json=json.dumps(line_items),
                total_amount=float(total),
                version=event.sequence_number,
            )
        )
        await session.execute(stmt)

    async def _handle_line_item_removed(
        self, event: BaseEvent, session: AsyncSession
    ) -> None:
        entity = await self.get_current_state(str(event.aggregate_id), session)
        if not entity:
            return

        payload = event.to_dict().get("payload", {})
        product_id = payload.get("product_id")
        line_items = [
            i for i in json.loads(entity.line_items_json or "[]")
            if i["product_id"] != product_id
        ]
        total = sum(
            Decimal(str(i["quantity"])) * Decimal(str(i["unit_price"]))
            for i in line_items
        )
        stmt = (
            update(DraftSaleReadEntity)
            .where(DraftSaleReadEntity.id == event.aggregate_id)
            .values(
                line_items_json=json.dumps(line_items),
                total_amount=float(total),
                version=event.sequence_number,
            )
        )
        await session.execute(stmt)

    async def _handle_line_item_updated(
        self, event: BaseEvent, session: AsyncSession
    ) -> None:
        entity = await self.get_current_state(str(event.aggregate_id), session)
        if not entity:
            return

        payload = event.to_dict().get("payload", {})
        product_id = payload.get("product_id")
        new_quantity = int(payload.get("quantity", 0))
        line_items = json.loads(entity.line_items_json or "[]")
        for item in line_items:
            if item["product_id"] == product_id:
                item["quantity"] = new_quantity
                break
        total = sum(
            Decimal(str(i["quantity"])) * Decimal(str(i["unit_price"]))
            for i in line_items
        )
        stmt = (
            update(DraftSaleReadEntity)
            .where(DraftSaleReadEntity.id == event.aggregate_id)
            .values(
                line_items_json=json.dumps(line_items),
                total_amount=float(total),
                version=event.sequence_number,
            )
        )
        await session.execute(stmt)

    async def _handle_sale_finalized(
        self, event: BaseEvent, session: AsyncSession
    ) -> None:
        # Mark sale as finalized
        await session.execute(
            update(DraftSaleReadEntity)
            .where(DraftSaleReadEntity.id == event.aggregate_id)
            .values(status="finalized", version=event.sequence_number)
        )
        # Deplete inventory using FIFO across cost layers
        payload = event.to_dict().get("payload", {})
        await self._deplete_inventory_fifo(payload.get("line_items", []), session)

    async def _deplete_inventory_fifo(
        self, line_items: list, session: AsyncSession
    ) -> None:
        """
        For each sold item, deduct its quantity from inventory_layer_read
        consuming the oldest layers first (FIFO).

        If total stock is insufficient the newest layer is allowed to go
        negative — the manager will see a red badge in the inventory view
        and can investigate / correct the count.
        """
        for item in line_items:
            product_id = str(item["product_id"])
            qty_to_deduct = int(item["quantity"])

            # Fetch layers oldest-first; include zero/negative so we don't skip them
            result = await session.execute(
                select(InventoryLayerReadEntity)
                .where(InventoryLayerReadEntity.product_id == product_id)
                .order_by(InventoryLayerReadEntity.created_at.asc())
            )
            layers = result.scalars().all()

            if not layers:
                # Product has no inventory record yet — nothing to deduct
                continue

            for idx, layer in enumerate(layers):
                if qty_to_deduct <= 0:
                    break

                is_last = idx == len(layers) - 1
                if is_last:
                    # Last (or only) layer absorbs the remainder, even if negative
                    await session.execute(
                        update(InventoryLayerReadEntity)
                        .where(InventoryLayerReadEntity.id == layer.id)
                        .values(quantity=layer.quantity - qty_to_deduct)
                    )
                    qty_to_deduct = 0
                else:
                    # Take what's available from this layer before moving on
                    available = max(0, layer.quantity)
                    take = min(available, qty_to_deduct)
                    if take > 0:
                        await session.execute(
                            update(InventoryLayerReadEntity)
                            .where(InventoryLayerReadEntity.id == layer.id)
                            .values(quantity=layer.quantity - take)
                        )
                        qty_to_deduct -= take

    async def _handle_sale_voided(
        self, event: BaseEvent, session: AsyncSession
    ) -> None:
        stmt = (
            update(DraftSaleReadEntity)
            .where(DraftSaleReadEntity.id == event.aggregate_id)
            .values(status="voided", version=event.sequence_number)
        )
        await session.execute(stmt)