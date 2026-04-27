"""
Inventory management routes — combined product + stock view for managers.

Provides a single-screen overview with inline editing of:
  · product name / category / selling price   (event-sourced for price)
  · current stock quantity                     (direct read-model adjustment)
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_manager_or_above
from app.application.handlers.product_handlers import ProductCommandHandler
from app.core.db import get_db_session
from app.domain.commands.product_commands import (
    ApplyPriceOverrideCommand,
    CreateProductCommand,
)
from app.infrastructure.projectors.read_entities import (
    CategoryReadEntity,
    InventoryLayerReadEntity,
    ProductReadEntity,
)

router = APIRouter(prefix="/api/inventory-mgmt", tags=["inventory-management"])


# ── Response schemas ────────────────────────────────────────────────────────


class InventorySummaryItem(BaseModel):
    product_id: str
    product_name: str
    category_id: str
    category_name: str | None
    base_price: str
    current_price: str
    avg_unit_cost: str | None   # weighted avg purchase cost from intake events
    margin: float | None        # (selling - cost) / selling
    current_stock: int
    stock_value: str
    last_intake_at: datetime | None
    last_price_override_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class CategoryItem(BaseModel):
    id: str
    name: str


# ── Request schemas ─────────────────────────────────────────────────────────


class UpdateProductRequest(BaseModel):
    name: str | None = None
    price: Decimal | None = None
    category_id: str | None = None


class StockAdjustmentRequest(BaseModel):
    product_id: str
    new_quantity: int
    reason: str = "Manual stock count correction"


class CreateProductRequest(BaseModel):
    name: str
    unit_price: Decimal
    category_id: str


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/summary", response_model=list[InventorySummaryItem])
async def get_inventory_summary(
    session: AsyncSession = Depends(get_db_session),
    _: CurrentUser = Depends(require_manager_or_above),
) -> list[InventorySummaryItem]:
    """
    Single-query combined view: products × categories × aggregated stock.
    This is the data source for the manager's inventory screen.
    """
    stock_sq = (
        select(
            InventoryLayerReadEntity.product_id,
            func.coalesce(func.sum(InventoryLayerReadEntity.quantity), 0).label("total_qty"),
            func.max(InventoryLayerReadEntity.last_intake_at).label("last_intake"),
        )
        .group_by(InventoryLayerReadEntity.product_id)
        .subquery()
    )

    stmt = (
        select(
            ProductReadEntity.id,
            ProductReadEntity.name,
            ProductReadEntity.category_id,
            CategoryReadEntity.name.label("category_name"),
            ProductReadEntity.base_price,
            ProductReadEntity.current_price,
            ProductReadEntity.last_price_override_at,
            func.coalesce(stock_sq.c.total_qty, 0).label("current_stock"),
            stock_sq.c.last_intake,
        )
        .outerjoin(stock_sq, ProductReadEntity.id == stock_sq.c.product_id)
        .outerjoin(
            CategoryReadEntity,
            ProductReadEntity.category_id == CategoryReadEntity.id,
        )
        .order_by(ProductReadEntity.name)
    )

    result = await session.execute(stmt)
    rows = result.mappings().all()

    # Weighted-average purchase cost per product from intake events
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
    avg_cost_by_product: dict[str, Decimal] = {
        row.product_id: Decimal(str(row.avg_cost))
        for row in cost_result.all()
        if row.avg_cost is not None
    }

    items: list[InventorySummaryItem] = []
    for row in rows:
        stock = int(row["current_stock"] or 0)
        price = Decimal(str(row["current_price"]))
        pid = str(row["id"])

        avg_cost = avg_cost_by_product.get(pid)
        # Fallback: if no intake events, use base_price as cost basis
        if avg_cost is None:
            avg_cost = Decimal(str(row["base_price"]))

        margin: float | None = None
        if avg_cost is not None and avg_cost > Decimal("0") and price > Decimal("0"):
            margin = round(float((price - avg_cost) / price), 4)

        items.append(
            InventorySummaryItem(
                product_id=pid,
                product_name=row["name"],
                category_id=str(row["category_id"]),
                category_name=row["category_name"],
                base_price=str(Decimal(str(row["base_price"])).quantize(Decimal("0.01"))),
                current_price=str(price.quantize(Decimal("0.01"))),
                avg_unit_cost=str(avg_cost.quantize(Decimal("0.01"))) if avg_cost else None,
                margin=margin,
                current_stock=stock,
                stock_value=str((price * stock).quantize(Decimal("0.01"))),
                last_intake_at=row["last_intake"],
                last_price_override_at=row["last_price_override_at"],
            )
        )
    return items


@router.get("/categories", response_model=list[CategoryItem])
async def list_categories(
    session: AsyncSession = Depends(get_db_session),
    _: CurrentUser = Depends(require_manager_or_above),
) -> list[CategoryItem]:
    result = await session.execute(select(CategoryReadEntity).order_by(CategoryReadEntity.name))
    return [CategoryItem(id=str(c.id), name=c.name) for c in result.scalars().all()]


@router.patch("/products/{product_id}")
async def update_product(
    product_id: str,
    payload: UpdateProductRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: CurrentUser = Depends(require_manager_or_above),
) -> dict:
    """
    Update a product's name, category, and/or price.
    Price changes go through the event-sourced price-override command.
    Name and category are updated directly on the read model
    (no dedicated rename command exists in the domain yet).
    """
    result = await session.execute(
        select(ProductReadEntity).where(ProductReadEntity.id == product_id)
    )
    entity = result.scalar_one_or_none()
    if not entity:
        raise HTTPException(status_code=404, detail="Product not found")

    # Direct read-model update for name / category
    direct_values: dict = {}
    if payload.name is not None:
        direct_values["name"] = payload.name
    if payload.category_id is not None:
        direct_values["category_id"] = payload.category_id
    if direct_values:
        await session.execute(
            update(ProductReadEntity)
            .where(ProductReadEntity.id == product_id)
            .values(**direct_values)
        )

    # Event-sourced command for price
    if payload.price is not None:
        handler = ProductCommandHandler(session)
        command = ApplyPriceOverrideCommand(
            product_id=UUID(product_id),
            new_price=payload.price,
            authorized_by=UUID(current_user.id),
        )
        try:
            await handler.handle_apply_price_override(command)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    await session.commit()
    return {"status": "updated"}


@router.post("/stock-adjustments")
async def adjust_stock(
    payload: StockAdjustmentRequest,
    session: AsyncSession = Depends(get_db_session),
    _: CurrentUser = Depends(require_manager_or_above),
) -> dict:
    """
    Manual stock count correction.

    Finds (or creates) a dedicated 'manual_adjustment' layer for the product
    and applies the delta so the total matches the manager's declared quantity.
    The reason is stored in layer_name for full traceability via the audit trail.
    """
    # Current aggregated stock
    total_result = await session.execute(
        select(func.coalesce(func.sum(InventoryLayerReadEntity.quantity), 0)).where(
            InventoryLayerReadEntity.product_id == payload.product_id
        )
    )
    current_total = int(total_result.scalar_one())
    delta = payload.new_quantity - current_total

    if delta == 0:
        return {"status": "no_change", "current_stock": current_total}

    # Reuse or create the manual-adjustment layer
    adj_result = await session.execute(
        select(InventoryLayerReadEntity).where(
            InventoryLayerReadEntity.product_id == payload.product_id,
            InventoryLayerReadEntity.layer_name.like("manual_adjustment%"),
        )
    )
    adj_layer = adj_result.scalar_one_or_none()

    if adj_layer:
        await session.execute(
            update(InventoryLayerReadEntity)
            .where(InventoryLayerReadEntity.id == adj_layer.id)
            .values(
                quantity=adj_layer.quantity + delta,
                layer_name=f"manual_adjustment: {payload.reason}",
                last_intake_at=datetime.now(timezone.utc),
            )
        )
    else:
        session.add(
            InventoryLayerReadEntity(
                id=str(uuid4()),
                product_id=payload.product_id,
                layer_name=f"manual_adjustment: {payload.reason}",
                quantity=delta,
                last_intake_at=datetime.now(timezone.utc),
            )
        )

    await session.commit()
    return {"status": "adjusted", "delta": delta, "new_quantity": payload.new_quantity}


@router.post("/products", status_code=201)
async def create_product(
    payload: CreateProductRequest,
    session: AsyncSession = Depends(get_db_session),
    _: CurrentUser = Depends(require_manager_or_above),
) -> dict:
    """Create a new product via the event-sourced command."""
    handler = ProductCommandHandler(session)
    command = CreateProductCommand(
        name=payload.name,
        unit_price=payload.unit_price,
        category_id=UUID(payload.category_id),
    )
    await handler.handle_create_product(command)
    return {"status": "created", "product_id": str(command.aggregate_id)}
