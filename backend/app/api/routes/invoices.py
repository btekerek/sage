"""
Invoice API route.

POST /api/invoices/process
    Upload a supplier invoice (PDF or image).
    Returns the extraction result immediately — the manager then
    reviews flagged items and calls POST /api/invoices/approve to
    commit the InventoryIntakeEvent.

POST /api/invoices/approve
    Approve a reviewed extraction result.
    Creates an InventoryIntakeEvent via the existing inventory handler.
"""

from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.settings import get_settings
from app.services.invoice_pipeline import InvoiceExtractionResult, run_pipeline

router = APIRouter(prefix="/api/invoices", tags=["invoices"])

# 10 MB upload limit
_MAX_FILE_BYTES = 10 * 1024 * 1024

_ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/tiff",
}


# ── Process endpoint ───────────────────────────────────────────────────────


@router.post("/process", response_model=InvoiceExtractionResult)
async def process_invoice(
    file: UploadFile,
) -> InvoiceExtractionResult:
    """
    Stage 1–3: upload → extract text → Claude → validate → route.
    Returns the extraction result for manager review.
    No database writes happen here.
    """
    settings = get_settings()

    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ANTHROPIC_API_KEY is not configured on this server.",
        )

    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '{file.content_type}'. "
                   f"Accepted: PDF, PNG, JPEG, TIFF.",
        )

    file_bytes = await file.read()
    if len(file_bytes) > _MAX_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds the 10 MB limit.",
        )

    try:
        result = run_pipeline(
            file_bytes=file_bytes,
            filename=file.filename or "invoice",
            api_key=settings.anthropic_api_key,
            confidence_threshold=settings.ai_confidence_threshold,
            ocr_engine_path=settings.ocr_engine_path,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return result


# ── Approve endpoint ───────────────────────────────────────────────────────


class ApproveLineItem(BaseModel):
    product_name: str
    quantity: int
    unit_price: Decimal
    supplier_ref: str


class ApproveInvoiceRequest(BaseModel):
    supplier_ref: str
    invoice_ref: str
    approved_by: UUID
    line_items: list[ApproveLineItem]


class ApproveInvoiceResponse(BaseModel):
    status: str
    intake_event_ids: list[UUID]


@router.post(
    "/approve",
    response_model=ApproveInvoiceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def approve_invoice(
    payload: ApproveInvoiceRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ApproveInvoiceResponse:
    """
    Manager submits the corrected/approved line items.
    Creates one InventoryLayer aggregate per line item.
    """
    from app.application.handlers.inventory_handlers import InventoryCommandHandler
    from app.domain.commands.inventory_commands import CreateInventoryLayerCommand

    handler = InventoryCommandHandler(session)
    created_ids: list[UUID] = []

    for item in payload.line_items:
        layer_id = uuid4()
        command = CreateInventoryLayerCommand(
            product_id=uuid4(),  # TODO: resolve product_name → product_id via read model
            quantity_received=item.quantity,
            unit_cost=item.unit_price,
            supplier_ref=f"{payload.supplier_ref} | {item.supplier_ref}",
            aggregate_id=layer_id,
        )
        await handler.handle_create_inventory_layer(command)
        created_ids.append(layer_id)

    return ApproveInvoiceResponse(
        status="accepted",
        intake_event_ids=created_ids,
    )