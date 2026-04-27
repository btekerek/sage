from decimal import Decimal
from uuid import UUID

from app.api.read_models import ProductReadModel
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
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/products", tags=["products"])


class CreateProductRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    unit_price: Decimal
    category_id: UUID


class ApplyPriceOverrideRequest(BaseModel):
    new_price: Decimal
    authorized_by: UUID


class ProductWriteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    aggregate_id: UUID
    status: str


class POSProductModel(BaseModel):
    """Lightweight product model for the POS screen — includes live stock count."""
    id: str
    name: str
    current_price: Decimal
    category_id: str
    category_name: str | None
    current_stock: int


# ── Fixed routes (must come before /{product_id} to avoid UUID parse errors) ──

@router.get("/pos-catalog", response_model=list[POSProductModel])
async def get_pos_catalog(
    session: AsyncSession = Depends(get_db_session),
) -> list[POSProductModel]:
    """
    Returns all products with their current aggregated stock level and category name.
    Used by the POS so it can enforce real stock limits and group by category.
    Must be declared before /{product_id} or FastAPI will try to parse
    the literal string 'pos-catalog' as a UUID and return 422.
    """
    stock_sq = (
        select(
            InventoryLayerReadEntity.product_id,
            func.coalesce(func.sum(InventoryLayerReadEntity.quantity), 0).label("total_qty"),
        )
        .group_by(InventoryLayerReadEntity.product_id)
        .subquery()
    )
    stmt = (
        select(
            ProductReadEntity.id,
            ProductReadEntity.name,
            ProductReadEntity.current_price,
            ProductReadEntity.category_id,
            CategoryReadEntity.name.label("category_name"),
            func.coalesce(stock_sq.c.total_qty, 0).label("current_stock"),
        )
        .outerjoin(stock_sq, ProductReadEntity.id == stock_sq.c.product_id)
        .outerjoin(CategoryReadEntity, ProductReadEntity.category_id == CategoryReadEntity.id)
        .order_by(CategoryReadEntity.name, ProductReadEntity.name)
    )
    result = await session.execute(stmt)
    rows = result.mappings().all()
    return [
        POSProductModel(
            id=str(row["id"]),
            name=row["name"],
            current_price=Decimal(str(row["current_price"])),
            category_id=str(row["category_id"]),
            category_name=row["category_name"],
            current_stock=int(row["current_stock"] or 0),
        )
        for row in rows
    ]


@router.get("", response_model=list[ProductReadModel])
async def list_products(
    session: AsyncSession = Depends(get_db_session),
) -> list[ProductReadModel]:
    stmt = select(ProductReadEntity)
    result = await session.execute(stmt)
    return [ProductReadModel.model_validate(p) for p in result.scalars().all()]


# ── Parameterised routes (/{product_id} must come last) ───────────────────────

@router.post(
    "", response_model=ProductWriteResponse, status_code=status.HTTP_201_CREATED
)
async def create_product(
    payload: CreateProductRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ProductWriteResponse:
    handler = ProductCommandHandler(session)
    command = CreateProductCommand(
        name=payload.name,
        unit_price=payload.unit_price,
        category_id=payload.category_id,
    )
    await handler.handle_create_product(command)
    assert command.aggregate_id is not None
    return ProductWriteResponse(aggregate_id=command.aggregate_id, status="accepted")


@router.patch("/{product_id}/price", response_model=ProductWriteResponse)
async def apply_price_override(
    product_id: UUID,
    payload: ApplyPriceOverrideRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ProductWriteResponse:
    handler = ProductCommandHandler(session)
    command = ApplyPriceOverrideCommand(
        product_id=product_id,
        new_price=payload.new_price,
        authorized_by=payload.authorized_by,
    )

    try:
        await handler.handle_apply_price_override(command)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    return ProductWriteResponse(aggregate_id=product_id, status="accepted")


@router.get("/{product_id}", response_model=ProductReadModel)
async def get_product(
    product_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> ProductReadModel:
    """Retrieve a product from the read model."""
    stmt = select(ProductReadEntity).where(ProductReadEntity.id == product_id)
    result = await session.execute(stmt)
    entity = result.scalar_one_or_none()

    if not entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
        )

    return ProductReadModel.model_validate(entity)
