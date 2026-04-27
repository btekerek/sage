"""
Invoice API route.

POST /api/invoices/process
    Upload a supplier invoice (PDF or image).
    Returns the extraction result immediately — the manager then
    reviews flagged items and calls POST /api/invoices/approve to
    commit the InventoryIntakeEvent.

POST /api/invoices/approve
    Approve a reviewed extraction result.
    Creates one InventoryLayer aggregate per line item and persists
    an InvoiceRecordEntity for the invoice history page.

GET /api/invoices
    List all approved invoices (newest first), paginated.
"""

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status

logger = logging.getLogger(__name__)
from pydantic import BaseModel, ConfigDict
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.settings import get_settings
from app.infrastructure.projectors.read_entities import (
    CategoryReadEntity,
    InvoiceRecordEntity,
    ProductReadEntity,
)
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
    session: AsyncSession = Depends(get_db_session),
) -> InvoiceExtractionResult:
    """
    Stage 1–3: upload → extract text → Claude → validate → route.
    Returns the extraction result for manager review.
    No database writes happen here.
    """
    from app.api.routes.config import get_runtime_config
    settings = get_settings()
    live_cfg = await get_runtime_config(session)

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
            confidence_threshold=float(live_cfg["ai_confidence_threshold"]),
            ocr_engine_path=settings.ocr_engine_path,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline error: {exc}",
        ) from exc

    return result


# ── Approve endpoint ───────────────────────────────────────────────────────


class ApproveLineItem(BaseModel):
    product_name: str
    quantity: int
    unit_price: Decimal
    supplier_ref: str
    cikkszam: str = ""
    packaging_size: int = 1
    line_total: Decimal = Decimal("0")


class ApproveInvoiceRequest(BaseModel):
    supplier_ref: str
    invoice_ref: str
    invoice_date: str | None = None
    approved_by: UUID
    line_items: list[ApproveLineItem]


class ApproveInvoiceResponse(BaseModel):
    status: str
    intake_event_ids: list[UUID]


async def _get_or_create_default_category(session: AsyncSession) -> UUID:
    """
    Return the id of the first category found, or create a sentinel
    'Invoice Imports' category so auto-created products have a valid FK.
    """
    from app.application.handlers.category_handlers import CategoryCommandHandler
    from app.domain.commands.category_commands import CreateCategoryCommand

    result = await session.execute(select(CategoryReadEntity).limit(1))
    row = result.scalars().first()
    if row is not None:
        return UUID(str(row.id))

    # No categories exist yet — create a placeholder
    cat_id = uuid4()
    try:
        handler = CategoryCommandHandler(session)
        await handler.handle_create_category(
            CreateCategoryCommand(
                name="Invoice Imports",
                aggregate_id=cat_id,
            )
        )
    except Exception as exc:
        logger.warning("Could not create default category: %s", exc)
    return cat_id


async def _resolve_product_id(
    session: AsyncSession,
    product_name: str,
    unit_price: Decimal,
    category_id: UUID,
) -> UUID:
    """
    Find an existing product by name (case-insensitive) or create a new one.
    Returns the product UUID.
    """
    from app.application.handlers.product_handlers import ProductCommandHandler
    from app.domain.commands.product_commands import CreateProductCommand
    from sqlalchemy import func as sqlfunc

    result = await session.execute(
        select(ProductReadEntity).where(
            sqlfunc.lower(ProductReadEntity.name) == product_name.strip().lower()
        ).limit(1)
    )
    row = result.scalars().first()
    if row is not None:
        return UUID(str(row.id))

    # Product not found — create it
    product_id = uuid4()
    command = CreateProductCommand(
        name=product_name.strip(),
        unit_price=unit_price,
        category_id=category_id,
        aggregate_id=product_id,
    )
    handler = ProductCommandHandler(session)
    await handler.handle_create_product(command)
    logger.info("Auto-created product '%s' with id %s", product_name, product_id)
    return product_id


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
    Creates one InventoryLayer aggregate per line item and persists
    an InvoiceRecordEntity for the invoice history page.
    """
    from app.application.handlers.inventory_handlers import InventoryCommandHandler
    from app.domain.commands.inventory_commands import CreateInventoryLayerCommand

    inv_handler = InventoryCommandHandler(session)
    created_ids: list[UUID] = []

    # Resolve the default category once for any new products we need to create
    default_category_id = await _get_or_create_default_category(session)

    for item in payload.line_items:
        # Resolve or create the product in the catalog
        product_id = await _resolve_product_id(
            session,
            product_name=item.product_name,
            unit_price=item.unit_price,
            category_id=default_category_id,
        )

        # Total individual units = packages ordered × units per package
        total_units = item.quantity * max(item.packaging_size, 1)

        # Per-unit cost: prefer line_total (net) ÷ total_units; fall back to unit_price
        if item.line_total > Decimal("0") and total_units > 0:
            unit_cost = (item.line_total / Decimal(str(total_units))).quantize(Decimal("0.0001"))
        else:
            unit_cost = item.unit_price

        layer_id = uuid4()
        command = CreateInventoryLayerCommand(
            product_id=product_id,
            quantity_received=total_units,
            unit_cost=unit_cost,
            supplier_ref=f"{payload.supplier_ref} | {item.supplier_ref}",
            aggregate_id=layer_id,
        )
        await inv_handler.handle_create_inventory_layer(command)
        created_ids.append(layer_id)

    # Persist invoice record for history page.
    # Use a fresh begin() to ensure we're in a clean transaction after the
    # UnitOfWork commits that happened inside the loop above.
    net_total = sum(
        float(i.line_total) if i.line_total > Decimal("0") else float(i.unit_price) * i.quantity
        for i in payload.line_items
    )
    now = datetime.now(timezone.utc)   # set explicitly — don't rely on server_default
    record = InvoiceRecordEntity(
        id=str(uuid4()),
        supplier_ref=payload.supplier_ref,
        invoice_ref=payload.invoice_ref,
        invoice_date=payload.invoice_date,
        approved_by=str(payload.approved_by),
        approved_at=now,
        line_item_count=len(payload.line_items),
        net_total=net_total,
        line_items_json=json.dumps([
            {
                "product_name": i.product_name,
                "quantity": i.quantity,
                "unit_price": str(i.unit_price),
                "supplier_ref": i.supplier_ref,
            }
            for i in payload.line_items
        ]),
    )
    try:
        session.add(record)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.error("Failed to persist invoice record: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Inventory updated but invoice record could not be saved: {exc}",
        ) from exc

    return ApproveInvoiceResponse(
        status="accepted",
        intake_event_ids=created_ids,
    )


# ── Invoice history endpoint ───────────────────────────────────────────────────


class InvoiceRecordModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    supplier_ref: str
    invoice_ref: str
    invoice_date: str | None
    approved_by: str
    approved_at: str
    line_item_count: int
    net_total: float
    line_items_json: str


class InvoiceListResponse(BaseModel):
    invoices: list[InvoiceRecordModel]
    total: int
    page: int
    page_size: int


@router.get("", response_model=InvoiceListResponse)
async def list_invoices(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> InvoiceListResponse:
    """Return approved invoices newest-first, paginated."""
    try:
        total_result = await session.execute(
            select(func.count()).select_from(InvoiceRecordEntity)
        )
        total = total_result.scalar_one()

        stmt = (
            select(InvoiceRecordEntity)
            .order_by(desc(InvoiceRecordEntity.approved_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
    except Exception as exc:
        logger.error("Failed to query invoice_record table: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not load invoices — the table may not exist yet. "
                   f"Run 'docker compose restart backend' once to create it. ({exc})",
        ) from exc

    return InvoiceListResponse(
        invoices=[
            InvoiceRecordModel(
                id=str(r.id),
                supplier_ref=r.supplier_ref,
                invoice_ref=r.invoice_ref,
                invoice_date=r.invoice_date,
                approved_by=str(r.approved_by),
                approved_at=r.approved_at.isoformat() if r.approved_at else "",
                line_item_count=r.line_item_count,
                net_total=float(r.net_total),
                line_items_json=r.line_items_json,
            )
            for r in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )