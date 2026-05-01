"""
Replenishment API route.

GET /api/replenishment/suggestions
POST /api/replenishment/accept

Resolution order for per-product replenishment parameters:
  1. product.lead_time_days / product.target_coverage_days  (product-level override)
  2. system config replenishment_lead_time_days / replenishment_target_days (global)
"""

import hashlib
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.api.routes.config import get_runtime_config
from app.infrastructure.projectors.read_entities import (
    InventoryLayerReadEntity,
    ProductReadEntity,
)
from app.services.milp_engine import (
    ProductReplenishmentInput,
    ReplenishmentResult,
    run_milp,
)

router = APIRouter(prefix="/api/replenishment", tags=["replenishment"])


def _default_daily_demand(product_id: str, selling_price: float) -> Decimal:
    """
    Price-aware randomised fallback demand for products with no sale history.
    Uses an MD5 hash of the product ID for deterministic +-35% variation.
    """
    if selling_price < 200:
        base = 12.0
    elif selling_price < 400:
        base = 8.0
    elif selling_price < 700:
        base = 5.0
    elif selling_price < 1000:
        base = 3.0
    else:
        base = 1.5
    digest = hashlib.md5(product_id.encode()).digest()
    variation = 0.65 + (int.from_bytes(digest[-4:], "big") / 0xFFFFFFFF) * 0.70
    return Decimal(str(round(base * variation, 2)))


@router.get("/suggestions", response_model=ReplenishmentResult)
async def get_replenishment_suggestions(
    target_days: int = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> ReplenishmentResult:
    live_cfg = await get_runtime_config(session)
    effective_target = target_days or int(live_cfg["replenishment_target_days"])
    effective_lead_time = int(live_cfg["replenishment_lead_time_days"])
    effective_budget = Decimal(str(live_cfg["replenishment_weekly_budget"]))

    stock_stmt = (
        select(
            InventoryLayerReadEntity.product_id,
            func.sum(InventoryLayerReadEntity.quantity).label("total_stock"),
        )
        .group_by(InventoryLayerReadEntity.product_id)
    )
    stock_result = await session.execute(stock_stmt)
    stock_by_product = {
        str(row.product_id): int(row.total_stock)
        for row in stock_result.all()
    }

    if not stock_by_product:
        return ReplenishmentResult(
            suggestions=[],
            total_estimated_cost=Decimal("0.00"),
            feasible=True,
            solver_status="no_inventory_data",
            budget=effective_budget,
            budget_used=Decimal("0.00"),
            budget_constrained=False,
        )

    product_ids = list(stock_by_product.keys())
    products_stmt = select(ProductReadEntity).where(
        ProductReadEntity.id.in_(product_ids)
    )
    products_result = await session.execute(products_stmt)
    products_by_id = {
        str(p.id): p for p in products_result.scalars().all()
    }

    demand_by_product = await _get_daily_demand(session, product_ids)

    milp_inputs: list[ProductReplenishmentInput] = []
    for product_id, stock in stock_by_product.items():
        product = products_by_id.get(product_id)
        if not product:
            continue
        daily_demand = demand_by_product.get(
            product_id,
            _default_daily_demand(product_id, float(product.current_price)),
        )
        # 2-level resolution: product override → global config
        product_lead_time = (
            int(product.lead_time_days)
            if product.lead_time_days is not None
            else effective_lead_time
        )
        product_target_days = (
            int(product.target_coverage_days)
            if product.target_coverage_days is not None
            else None  # engine uses effective_target as fallback
        )
        milp_inputs.append(
            ProductReplenishmentInput(
                product_id=UUID(product_id),
                product_name=product.name,
                current_stock=stock,
                daily_demand=daily_demand,
                unit_cost=Decimal(str(product.current_price)),
                lead_time_days=product_lead_time,
                target_coverage_days=product_target_days,
            )
        )

    return run_milp(milp_inputs, effective_target, effective_budget)


class AcceptedOrder(BaseModel):
    product_id: UUID
    quantity: int


class AcceptReplenishmentRequest(BaseModel):
    orders: list[AcceptedOrder]
    approved_by: UUID


class AcceptReplenishmentResponse(BaseModel):
    status: str
    accepted_count: int


@router.post("/accept", response_model=AcceptReplenishmentResponse)
async def accept_replenishment_orders(
    payload: AcceptReplenishmentRequest,
    session: AsyncSession = Depends(get_db_session),
) -> AcceptReplenishmentResponse:
    from app.infrastructure.repositories.event_store_repository import EventStoreRepository

    repo = EventStoreRepository(session)
    for order in payload.orders:
        await repo.append_event(
            aggregate_type="Replenishment",
            aggregate_id=str(uuid4()),
            event_type="PurchaseOrderEvent",
            payload={
                "product_id": str(order.product_id),
                "quantity": order.quantity,
                "approved_by": str(payload.approved_by),
            },
            actor_id=str(payload.approved_by),
        )
    await session.commit()
    return AcceptReplenishmentResponse(status="accepted", accepted_count=len(payload.orders))


async def _get_daily_demand(
    session: AsyncSession,
    product_ids: list[str],
) -> dict[str, Decimal]:
    try:
        stmt = text("""
            SELECT
                line_item->>'product_id' AS product_id,
                SUM((line_item->>'quantity')::int) / 30.0 AS daily_demand
            FROM events,
                 jsonb_array_elements(payload->'line_items') AS line_item
            WHERE event_type = 'SaleEvent'
              AND occurred_at_utc >= NOW() - INTERVAL '30 days'
              AND line_item->>'product_id' = ANY(:product_ids)
            GROUP BY line_item->>'product_id'
        """)
        result = await session.execute(stmt, {"product_ids": product_ids})
        return {
            row.product_id: Decimal(str(row.daily_demand)).quantize(Decimal("0.01"))
            for row in result.all()
        }
    except Exception:
        return {}
