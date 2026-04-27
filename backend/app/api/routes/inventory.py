from decimal import Decimal
from uuid import UUID

from app.api.read_models import InventoryLayerReadModel
from app.application.handlers.inventory_handlers import InventoryCommandHandler
from app.core.db import get_db_session
from app.domain.commands.inventory_commands import CreateInventoryLayerCommand
from app.infrastructure.projectors.read_entities import InventoryLayerReadEntity
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/inventory-layers", tags=["inventory"])


class CreateInventoryLayerRequest(BaseModel):
    product_id: UUID
    quantity_received: int = Field(gt=0)
    unit_cost: Decimal
    supplier_ref: str = Field(min_length=1, max_length=255)


class InventoryWriteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    aggregate_id: UUID
    status: str


@router.post(
    "", response_model=InventoryWriteResponse, status_code=status.HTTP_201_CREATED
)
async def create_inventory_layer(
    payload: CreateInventoryLayerRequest,
    session: AsyncSession = Depends(get_db_session),
) -> InventoryWriteResponse:
    handler = InventoryCommandHandler(session)
    command = CreateInventoryLayerCommand(
        product_id=payload.product_id,
        quantity_received=payload.quantity_received,
        unit_cost=payload.unit_cost,
        supplier_ref=payload.supplier_ref,
    )
    await handler.handle_create_inventory_layer(command)
    assert command.aggregate_id is not None
    return InventoryWriteResponse(aggregate_id=command.aggregate_id, status="accepted")


@router.get("/{inventory_layer_id}", response_model=InventoryLayerReadModel)
async def get_inventory_layer(
    inventory_layer_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> InventoryLayerReadModel:
    """Retrieve an inventory layer from the read model."""
    stmt = select(InventoryLayerReadEntity).where(
        InventoryLayerReadEntity.id == inventory_layer_id
    )
    result = await session.execute(stmt)
    entity = result.scalar_one_or_none()

    if not entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Inventory layer not found"
        )

    return InventoryLayerReadModel.model_validate(entity)