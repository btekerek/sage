"""
Replenishment API route.

GET /api/replenishment/suggestions
POST /api/replenishment/accept
"""

from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.settings import get_settings
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

_DEFAULT_DAILY_DEMAND = Decimal("5.0")


@router.get("/suggestions", response_model=ReplenishmentResult)
async def get_replenishment_suggestions(
    budget: float = Query(default=None),
    target_days: int = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> ReplenishmentResult:
    settings = get_settings()
    effective_budget = budget or settings.replenishment_budget
    effective_target = target_days or settings.replenishment_target_days

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
            budget_used=Decimal("0.00"),
            budget_remaining=Decimal(str(effective_budget)),
            feasible=True,
            solver_status="no_inventory_data",
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
        daily_demand = demand_by_product.get(product_id, _DEFAULT_DAILY_DEMAND)
        milp_inputs.append(
            ProductReplenishmentInput(
                product_id=UUID(product_id),
                product_name=product.name,
                current_stock=stock,
                daily_demand=daily_demand,
                unit_cost=Decimal(str(product.current_price)),
            )
        )

    return run_milp(milp_inputs, effective_budget, effective_target)


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