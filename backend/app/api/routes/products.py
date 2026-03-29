from decimal import Decimal
from uuid import UUID

from app.api.read_models import ProductReadModel
from app.application.handlers.product_handlers import ProductCommandHandler
from app.core.db import get_db_session
from app.domain.commands.product_commands import (
    ApplyPriceOverrideCommand,
    CreateProductCommand,
)
from app.infrastructure.projectors.read_entities import ProductReadEntity
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
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
