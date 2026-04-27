"""
Dashboard API route.

GET /api/dashboard/kpis          — today's sales KPIs from the event store
GET /api/dashboard/recent-sales  — last N finalized / voided transactions
GET /api/dashboard/stream        — SSE live feed of new SaleEvent / VoidEvent
GET /api/events                  — paginated audit trail
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.db as _db
from app.core.db import get_db_session
from app.core.security import decode_token
from app.infrastructure.event_store.models import StoredEvent

from app.infrastructure.projectors.read_entities import (
    InventoryLayerReadEntity,
    ProductReadEntity,
)

router = APIRouter(tags=["dashboard"])


# ── KPI Summary ────────────────────────────────────────────────────────────


class KPISummary(BaseModel):
    today_revenue: float
    today_transactions: int
    today_units_sold: int
    total_revenue: float
    total_transactions: int


@router.get("/api/dashboard/kpis", response_model=KPISummary)
async def get_kpis(
    session: AsyncSession = Depends(get_db_session),
) -> KPISummary:
    """Compute live KPIs directly from the event store."""
    try:
        result = await session.execute(text("""
            SELECT
                COALESCE(SUM(CASE
                    WHEN event_type = 'SaleEvent'
                     AND occurred_at_utc::date = CURRENT_DATE
                    THEN (payload->>'total_amount')::numeric
                    ELSE 0
                END), 0) AS today_revenue,

                COUNT(CASE
                    WHEN event_type = 'SaleEvent'
                     AND occurred_at_utc::date = CURRENT_DATE
                    THEN 1
                END) AS today_transactions,

                (
                    SELECT COALESCE(SUM((item->>'quantity')::int), 0)
                    FROM events e2
                    CROSS JOIN LATERAL jsonb_array_elements(
                        COALESCE(e2.payload->'line_items', '[]'::jsonb)
                    ) AS item
                    WHERE e2.event_type = 'SaleEvent'
                      AND e2.occurred_at_utc::date = CURRENT_DATE
                ) AS today_units_sold,

                COALESCE(SUM(CASE
                    WHEN event_type = 'SaleEvent'
                    THEN (payload->>'total_amount')::numeric
                    ELSE 0
                END), 0) AS total_revenue,

                COUNT(CASE
                    WHEN event_type = 'SaleEvent'
                    THEN 1
                END) AS total_transactions

            FROM events
        """))
        row = result.one()
        return KPISummary(
            today_revenue=float(row.today_revenue),
            today_transactions=int(row.today_transactions),
            today_units_sold=int(row.today_units_sold),
            total_revenue=float(row.total_revenue),
            total_transactions=int(row.total_transactions),
        )
    except Exception:
        return KPISummary(
            today_revenue=0,
            today_transactions=0,
            today_units_sold=0,
            total_revenue=0,
            total_transactions=0,
        )


# ── Portfolio Margin ──────────────────────────────────────────────────────


class MarginProduct(BaseModel):
    product_id: str
    product_name: str
    selling_price: float
    avg_unit_cost: float
    stock: int
    margin: float          # (selling - cost) / selling


class MarginSummary(BaseModel):
    portfolio_margin: float         # revenue-weighted average
    margin_target: float
    meets_target: bool
    products: list[MarginProduct]


@router.get("/api/dashboard/margin", response_model=MarginSummary)
async def get_margin(
    session: AsyncSession = Depends(get_db_session),
) -> MarginSummary:
    """
    Compute the current portfolio gross margin.

    Method:
      - avg unit cost per product = weighted average from InventoryLayerCreatedEvent
      - selling price = product_read.current_price
      - margin per product = (selling - cost) / selling
      - portfolio margin = weighted by (selling_price × stock) across all stocked products
    """
    from app.api.routes.config import get_runtime_config

    live_cfg = await get_runtime_config(session)
    margin_target = float(live_cfg.get("margin_target", 0.70))

    try:
        # Weighted average cost per product from intake events
        cost_result = await session.execute(text("""
            SELECT
                payload->>'product_id'                                          AS product_id,
                SUM((payload->>'quantity_received')::int
                    * (payload->>'unit_cost')::numeric)
                / NULLIF(SUM((payload->>'quantity_received')::int), 0)          AS avg_cost
            FROM events
            WHERE event_type = 'InventoryLayerCreatedEvent'
            GROUP BY payload->>'product_id'
        """))
        avg_cost_by_product: dict[str, float] = {
            row.product_id: float(row.avg_cost)
            for row in cost_result.all()
            if row.avg_cost is not None
        }

        # Current stock per product
        stock_result = await session.execute(
            select(
                InventoryLayerReadEntity.product_id,
                func.sum(InventoryLayerReadEntity.quantity).label("total_stock"),
            ).group_by(InventoryLayerReadEntity.product_id)
        )
        stock_by_product: dict[str, int] = {
            str(row.product_id): int(row.total_stock)
            for row in stock_result.all()
        }

        if not stock_by_product:
            return MarginSummary(
                portfolio_margin=0.0,
                margin_target=margin_target,
                meets_target=False,
                products=[],
            )

        # Selling prices
        products_result = await session.execute(
            select(ProductReadEntity).where(
                ProductReadEntity.id.in_(list(stock_by_product.keys()))
            )
        )
        products = products_result.scalars().all()

        product_rows: list[MarginProduct] = []
        weighted_margin_sum = 0.0
        weight_sum = 0.0

        for p in products:
            pid = str(p.id)
            stock = stock_by_product.get(pid, 0)
            if stock <= 0:
                continue
            selling = float(p.current_price)
            cost = avg_cost_by_product.get(pid)
            if cost is None or selling <= 0:
                continue
            margin = (selling - cost) / selling
            weight = selling * stock
            weighted_margin_sum += margin * weight
            weight_sum += weight
            product_rows.append(MarginProduct(
                product_id=pid,
                product_name=p.name,
                selling_price=selling,
                avg_unit_cost=cost,
                stock=stock,
                margin=round(margin, 4),
            ))

        portfolio_margin = (weighted_margin_sum / weight_sum) if weight_sum > 0 else 0.0
        product_rows.sort(key=lambda r: r.margin)   # worst first

        return MarginSummary(
            portfolio_margin=round(portfolio_margin, 4),
            margin_target=margin_target,
            meets_target=portfolio_margin >= margin_target,
            products=product_rows,
        )

    except Exception as exc:
        logger.exception("Failed to compute margin: %s", exc)
        return MarginSummary(
            portfolio_margin=0.0,
            margin_target=margin_target,
            meets_target=False,
            products=[],
        )


# ── Recent Transactions ────────────────────────────────────────────────────


class TransactionEntry(BaseModel):
    id: int
    event_type: str   # "SaleEvent" | "VoidEvent"
    aggregate_id: str
    occurred_at_utc: datetime
    payload: dict


@router.get("/api/dashboard/recent-sales", response_model=list[TransactionEntry])
async def get_recent_sales(
    limit: int = Query(default=30, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> list[TransactionEntry]:
    """Return the most recent finalized / voided transactions for the live feed."""
    result = await session.execute(
        select(StoredEvent)
        .where(StoredEvent.event_type.in_(["SaleEvent", "VoidEvent"]))
        .order_by(StoredEvent.id.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    return [
        TransactionEntry(
            id=row.id,
            event_type=row.event_type,
            aggregate_id=row.aggregate_id,
            occurred_at_utc=row.occurred_at_utc,
            payload=row.payload,
        )
        for row in rows
    ]


# ── SSE Live Stream ────────────────────────────────────────────────────────


@router.get("/api/dashboard/stream")
async def live_stream(token: str = Query(...)) -> StreamingResponse:
    """
    Server-Sent Events feed: emits a JSON object for every new SaleEvent
    or VoidEvent written to the event store, with ~2 s latency.

    The JWT is passed as ?token= because the browser's EventSource API
    does not support custom headers.
    """
    try:
        decode_token(token)          # raises JWTError if invalid / expired
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    async def generator():
        # Find the high-water mark so we only emit genuinely new events
        async with _db.async_session_maker() as session:
            result = await session.execute(
                text("SELECT COALESCE(MAX(id), 0) FROM events")
            )
            last_id: int = result.scalar_one()

        # Send a keepalive comment immediately so the browser confirms the stream
        yield ": connected\n\n"

        while True:
            await asyncio.sleep(2)
            try:
                async with _db.async_session_maker() as session:
                    result = await session.execute(
                        select(StoredEvent)
                        .where(StoredEvent.id > last_id)
                        .where(StoredEvent.event_type.in_(["SaleEvent", "VoidEvent"]))
                        .order_by(StoredEvent.id.asc())
                    )
                    rows = result.scalars().all()

                for row in rows:
                    last_id = max(last_id, row.id)
                    data = json.dumps(
                        {
                            "id": row.id,
                            "event_type": row.event_type,
                            "aggregate_id": row.aggregate_id,
                            "occurred_at_utc": row.occurred_at_utc.isoformat(),
                            "payload": row.payload,
                        },
                        ensure_ascii=False,
                    )
                    yield f"data: {data}\n\n"
            except asyncio.CancelledError:
                break
            except Exception:
                # DB hiccup — keep the stream alive, try again next tick
                yield ": heartbeat\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering
            "Connection": "keep-alive",
        },
    )


# ── Audit Trail ────────────────────────────────────────────────────────────


class AuditEvent(BaseModel):
    id: int
    event_id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    sequence_number: int
    occurred_at_utc: datetime
    actor_id: Optional[str]
    payload: dict


class AuditTrailResponse(BaseModel):
    events: list[AuditEvent]
    total: int
    page: int
    page_size: int


@router.get("/api/events", response_model=AuditTrailResponse)
async def get_audit_trail(
    event_type: Optional[str] = Query(default=None),
    aggregate_type: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> AuditTrailResponse:
    """Return a paginated, filterable view of the event store."""
    stmt = select(StoredEvent)
    count_stmt = select(func.count()).select_from(StoredEvent)

    if event_type:
        stmt = stmt.where(StoredEvent.event_type == event_type)
        count_stmt = count_stmt.where(StoredEvent.event_type == event_type)
    if aggregate_type:
        stmt = stmt.where(StoredEvent.aggregate_type == aggregate_type)
        count_stmt = count_stmt.where(StoredEvent.aggregate_type == aggregate_type)

    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = (
        stmt.order_by(StoredEvent.occurred_at_utc.desc(), StoredEvent.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    return AuditTrailResponse(
        events=[
            AuditEvent(
                id=row.id,
                event_id=row.event_id,
                aggregate_type=row.aggregate_type,
                aggregate_id=row.aggregate_id,
                event_type=row.event_type,
                sequence_number=row.sequence_number,
                occurred_at_utc=row.occurred_at_utc,
                actor_id=row.actor_id,
                payload=row.payload,
            )
            for row in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
