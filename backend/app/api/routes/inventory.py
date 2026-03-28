from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.handlers.inventory_handlers import InventoryCommandHandler
from app.core.db import get_db_session
from app.domain.commands.inventory_commands import CreateInventoryLayerCommand

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


@router.post("", response_model=InventoryWriteResponse, status_code=status.HTTP_201_CREATED)
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
    return InventoryWriteResponse(aggregate_id=command.aggregate_id, status="accepted")
