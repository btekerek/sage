from decimal import Decimal
from uuid import UUID

from app.application.handlers.sale_handlers import SaleCommandHandler
from app.core.db import get_db_session
from app.domain.commands.sale_commands import (
    AddLineItemCommand,
    CreateDraftSaleCommand,
    FinalizeSaleCommand,
    RemoveLineItemCommand,
    UpdateLineItemCommand,
    VoidSaleCommand,
)
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/draft-sales", tags=["draft-sales"])


class CreateDraftSaleRequest(BaseModel):
    operator_id: UUID
    session_id: UUID


class AddLineItemRequest(BaseModel):
    product_id: UUID
    product_name: str = Field(min_length=1, max_length=255)
    unit_price: Decimal
    quantity: int = Field(gt=0)
    available_stock: int = Field(ge=0)


class UpdateLineItemRequest(BaseModel):
    quantity: int = Field(gt=0)
    available_stock: int = Field(ge=0)


class FinalizeSaleRequest(BaseModel):
    payment_method: str = Field(min_length=1, max_length=50)


class VoidSaleRequest(BaseModel):
    reason: str = Field(default="", max_length=500)


class SaleWriteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    aggregate_id: UUID
    status: str


@router.post("", response_model=SaleWriteResponse, status_code=status.HTTP_201_CREATED)
async def create_draft_sale(
    payload: CreateDraftSaleRequest,
    session: AsyncSession = Depends(get_db_session),
) -> SaleWriteResponse:
    handler = SaleCommandHandler(session)
    command = CreateDraftSaleCommand(
        operator_id=payload.operator_id,
        session_id=payload.session_id,
    )
    await handler.handle_create_draft_sale(command)
    return SaleWriteResponse(aggregate_id=command.aggregate_id, status="accepted")


@router.post("/{sale_id}/items", response_model=SaleWriteResponse)
async def add_line_item(
    sale_id: UUID,
    payload: AddLineItemRequest,
    session: AsyncSession = Depends(get_db_session),
) -> SaleWriteResponse:
    handler = SaleCommandHandler(session)
    command = AddLineItemCommand(
        sale_id=sale_id,
        product_id=payload.product_id,
        product_name=payload.product_name,
        unit_price=payload.unit_price,
        quantity=payload.quantity,
        available_stock=payload.available_stock,
    )

    try:
        await handler.handle_add_line_item(command)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return SaleWriteResponse(aggregate_id=sale_id, status="accepted")


@router.delete("/{sale_id}/items/{product_id}", response_model=SaleWriteResponse)
async def remove_line_item(
    sale_id: UUID,
    product_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> SaleWriteResponse:
    handler = SaleCommandHandler(session)
    command = RemoveLineItemCommand(sale_id=sale_id, product_id=product_id)

    try:
        await handler.handle_remove_line_item(command)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return SaleWriteResponse(aggregate_id=sale_id, status="accepted")


@router.patch("/{sale_id}/items/{product_id}", response_model=SaleWriteResponse)
async def update_line_item(
    sale_id: UUID,
    product_id: UUID,
    payload: UpdateLineItemRequest,
    session: AsyncSession = Depends(get_db_session),
) -> SaleWriteResponse:
    handler = SaleCommandHandler(session)
    command = UpdateLineItemCommand(
        sale_id=sale_id,
        product_id=product_id,
        quantity=payload.quantity,
        available_stock=payload.available_stock,
    )

    try:
        await handler.handle_update_line_item(command)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return SaleWriteResponse(aggregate_id=sale_id, status="accepted")


@router.post("/{sale_id}/finalize", response_model=SaleWriteResponse)
async def finalize_sale(
    sale_id: UUID,
    payload: FinalizeSaleRequest,
    session: AsyncSession = Depends(get_db_session),
) -> SaleWriteResponse:
    handler = SaleCommandHandler(session)
    command = FinalizeSaleCommand(
        sale_id=sale_id, payment_method=payload.payment_method
    )

    try:
        await handler.handle_finalize_sale(command)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return SaleWriteResponse(aggregate_id=sale_id, status="accepted")


@router.post("/{sale_id}/void", response_model=SaleWriteResponse)
async def void_sale(
    sale_id: UUID,
    payload: VoidSaleRequest,
    session: AsyncSession = Depends(get_db_session),
) -> SaleWriteResponse:
    handler = SaleCommandHandler(session)
    command = VoidSaleCommand(sale_id=sale_id, reason=payload.reason)

    try:
        await handler.handle_void_sale(command)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return SaleWriteResponse(aggregate_id=sale_id, status="accepted")
