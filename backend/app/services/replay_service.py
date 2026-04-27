"""
Deterministic in-memory replay service.

Given an `as_of` timestamp, queries every StoredEvent with
occurred_at_utc <= as_of (in chronological order) and projects them
into a complete system snapshot — products, stock levels, categories —
without touching any live read-model table.

This is the core of the time-travel feature: pure read, zero side-effects.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy import asc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.event_store.models import StoredEvent


# ── Response models ────────────────────────────────────────────────────────────


class ReplayCategoryItem(BaseModel):
    id: str
    name: str


class ReplayProductItem(BaseModel):
    id: str
    name: str
    category_id: str
    category_name: str | None
    base_price: float
    current_price: float
    stock: int


class ReplayTimelineEntry(BaseModel):
    occurred_at: str          # ISO-8601
    event_type: str
    aggregate_type: str
    aggregate_id: str
    summary: str              # Human-readable one-liner


class ReplaySnapshot(BaseModel):
    as_of: str                # ISO-8601 of the requested timestamp
    categories: list[ReplayCategoryItem]
    products: list[ReplayProductItem]
    event_timeline: list[ReplayTimelineEntry]
    events_replayed: int
    first_event_at: str | None
    last_event_at: str | None


class ReplayBounds(BaseModel):
    first_event_at: str | None
    last_event_at: str | None
    total_events: int


# ── Service ────────────────────────────────────────────────────────────────────


async def get_event_bounds(session: AsyncSession) -> ReplayBounds:
    """Return the temporal range of the event store."""
    result = await session.execute(
        select(
            func.min(StoredEvent.occurred_at_utc).label("first"),
            func.max(StoredEvent.occurred_at_utc).label("last"),
            func.count().label("total"),
        )
    )
    row = result.one()
    return ReplayBounds(
        first_event_at=row.first.isoformat() if row.first else None,
        last_event_at=row.last.isoformat() if row.last else None,
        total_events=int(row.total or 0),
    )


async def replay_at(session: AsyncSession, as_of: datetime) -> ReplaySnapshot:
    """
    Replay all events up to `as_of` in memory and return a full snapshot.

    No database writes happen — this is a pure projection over the event log.
    """
    # Ensure as_of is tz-aware
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)

    stmt = (
        select(StoredEvent)
        .where(StoredEvent.occurred_at_utc <= as_of)
        .order_by(asc(StoredEvent.occurred_at_utc), asc(StoredEvent.id))
    )
    result = await session.execute(stmt)
    events: list[StoredEvent] = list(result.scalars().all())

    # ── In-memory projection state ──────────────────────────────────────────
    categories: dict[str, dict[str, Any]] = {}       # id → {id, name}
    products: dict[str, dict[str, Any]] = {}          # id → {id, name, cat_id, base, current}
    layer_to_product: dict[str, str] = {}             # layer_id → product_id
    layer_qty: dict[str, int] = {}                    # layer_id → current qty
    stock: dict[str, int] = {}                        # product_id → total stock
    timeline: list[ReplayTimelineEntry] = []

    for ev in events:
        p = ev.payload or {}
        ts = ev.occurred_at_utc.isoformat()

        if ev.event_type == "CategoryCreatedEvent":
            name = p.get("name", "?")
            categories[ev.aggregate_id] = {"id": ev.aggregate_id, "name": name}
            timeline.append(ReplayTimelineEntry(
                occurred_at=ts,
                event_type=ev.event_type,
                aggregate_type=ev.aggregate_type,
                aggregate_id=ev.aggregate_id,
                summary=f"Category '{name}' created",
            ))

        elif ev.event_type == "ProductCreatedEvent":
            name = p.get("name", "?")
            price = float(p.get("unit_price", 0))
            cat_id = p.get("category_id", "")
            products[ev.aggregate_id] = {
                "id": ev.aggregate_id,
                "name": name,
                "category_id": cat_id,
                "base_price": price,
                "current_price": price,
            }
            stock.setdefault(ev.aggregate_id, 0)
            timeline.append(ReplayTimelineEntry(
                occurred_at=ts,
                event_type=ev.event_type,
                aggregate_type=ev.aggregate_type,
                aggregate_id=ev.aggregate_id,
                summary=f"Product '{name}' added — {price:,.0f} Ft",
            ))

        elif ev.event_type == "PriceOverrideEvent":
            prod_id = p.get("product_id", ev.aggregate_id)
            new_price = float(p.get("new_price", 0))
            prev_price = float(p.get("previous_price", 0))
            if prod_id in products:
                products[prod_id]["current_price"] = new_price
                name = products[prod_id]["name"]
            else:
                name = prod_id[:8]
            timeline.append(ReplayTimelineEntry(
                occurred_at=ts,
                event_type=ev.event_type,
                aggregate_type=ev.aggregate_type,
                aggregate_id=ev.aggregate_id,
                summary=f"Price override '{name}': {prev_price:,.0f} → {new_price:,.0f} Ft",
            ))

        elif ev.event_type == "InventoryLayerCreatedEvent":
            prod_id = p.get("product_id", "")
            qty = int(p.get("quantity_received", 0))
            supplier = p.get("supplier_ref", "")
            layer_to_product[ev.aggregate_id] = prod_id
            layer_qty[ev.aggregate_id] = qty
            stock[prod_id] = stock.get(prod_id, 0) + qty
            prod_name = products.get(prod_id, {}).get("name", prod_id[:8])
            timeline.append(ReplayTimelineEntry(
                occurred_at=ts,
                event_type=ev.event_type,
                aggregate_type=ev.aggregate_type,
                aggregate_id=ev.aggregate_id,
                summary=f"Intake: {qty}× '{prod_name}' from {supplier or 'supplier'}",
            ))

        elif ev.event_type == "InventoryIntakeEvent":
            # Updates an existing layer's quantity in place
            prod_id = layer_to_product.get(ev.aggregate_id, "")
            new_qty = int(p.get("quantity_received", 0))
            old_qty = layer_qty.get(ev.aggregate_id, 0)
            if prod_id:
                stock[prod_id] = stock.get(prod_id, 0) - old_qty + new_qty
                layer_qty[ev.aggregate_id] = new_qty
            timeline.append(ReplayTimelineEntry(
                occurred_at=ts,
                event_type=ev.event_type,
                aggregate_type=ev.aggregate_type,
                aggregate_id=ev.aggregate_id,
                summary=f"Inventory update: layer qty {old_qty} → {new_qty}",
            ))

        elif ev.event_type == "SaleEvent":
            total = float(p.get("total_amount", 0))
            line_items = p.get("line_items", [])
            for item in line_items:
                prod_id = item.get("product_id", "")
                qty = int(item.get("quantity", 0))
                if prod_id:
                    stock[prod_id] = max(0, stock.get(prod_id, 0) - qty)
            n = len(line_items)
            timeline.append(ReplayTimelineEntry(
                occurred_at=ts,
                event_type=ev.event_type,
                aggregate_type=ev.aggregate_type,
                aggregate_id=ev.aggregate_id,
                summary=f"Sale: {n} item{'s' if n != 1 else ''}, total {total:,.0f} Ft",
            ))

        elif ev.event_type == "VoidEvent":
            reason = p.get("reason", "")
            timeline.append(ReplayTimelineEntry(
                occurred_at=ts,
                event_type=ev.event_type,
                aggregate_type=ev.aggregate_type,
                aggregate_id=ev.aggregate_id,
                summary=f"Transaction voided{': ' + reason if reason else ''}",
            ))

        # DraftSale events are transient — skip them in the timeline
        # to keep it readable (they don't change durable state).

    # ── Build response ─────────────────────────────────────────────────────
    cat_list = [ReplayCategoryItem(id=c["id"], name=c["name"]) for c in categories.values()]

    product_list = [
        ReplayProductItem(
            id=p["id"],
            name=p["name"],
            category_id=p["category_id"],
            category_name=categories.get(p["category_id"], {}).get("name"),
            base_price=p["base_price"],
            current_price=p["current_price"],
            stock=stock.get(p["id"], 0),
        )
        for p in sorted(products.values(), key=lambda x: x["name"])
    ]

    first_at = events[0].occurred_at_utc.isoformat() if events else None
    last_at = events[-1].occurred_at_utc.isoformat() if events else None

    return ReplaySnapshot(
        as_of=as_of.isoformat(),
        categories=cat_list,
        products=product_list,
        event_timeline=list(reversed(timeline)),   # newest first for display
        events_replayed=len(events),
        first_event_at=first_at,
        last_event_at=last_at,
    )
