"""SQLAlchemy models for read-side projections (denormalized views of aggregates)."""

from datetime import datetime

from sqlalchemy import UUID, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class ReadBase(DeclarativeBase):
    """Base class for read-side models."""

    pass


class ProductReadEntity(ReadBase):
    """Denormalized Product aggregate read model."""

    __tablename__ = "product_read"

    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    category_id: Mapped[str] = mapped_column(UUID)
    base_price: Mapped[float] = mapped_column(Numeric(10, 2))
    current_price: Mapped[float] = mapped_column(Numeric(10, 2))
    last_price_override_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    version: Mapped[int] = mapped_column(default=0)


class CategoryReadEntity(ReadBase):
    """Denormalized Category aggregate read model."""

    __tablename__ = "category_read"

    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    version: Mapped[int] = mapped_column(default=0)


class InventoryLayerReadEntity(ReadBase):
    """Denormalized InventoryLayer aggregate read model."""

    __tablename__ = "inventory_layer_read"

    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    product_id: Mapped[str] = mapped_column(UUID)
    layer_name: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[int] = mapped_column(default=0)
    last_intake_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    version: Mapped[int] = mapped_column(default=0)


class InvoiceRecordEntity(ReadBase):
    """
    Persisted record of every approved supplier invoice.
    Written by the /api/invoices/approve endpoint so managers can
    browse invoice history without replaying the full event store.
    """

    __tablename__ = "invoice_record"

    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    supplier_ref: Mapped[str] = mapped_column(String(255))
    invoice_ref: Mapped[str] = mapped_column(String(255))
    invoice_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    approved_by: Mapped[str] = mapped_column(String(100))
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    line_item_count: Mapped[int] = mapped_column(Integer, default=0)
    net_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0.0)
    # Full JSON snapshot of line items as submitted (for audit / re-display)
    line_items_json: Mapped[str] = mapped_column(Text, default="[]")


class DraftSaleReadEntity(ReadBase):
    """Denormalized DraftSale aggregate read model."""

    __tablename__ = "draft_sale_read"

    id: Mapped[str] = mapped_column(UUID, primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(255))
    total_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0.0)
    status: Mapped[str] = mapped_column(
        String(50), default="draft"
    )  # draft, finalized, voided
    line_items_json: Mapped[str] = mapped_column(
        String, default="[]"
    )  # JSON serialized
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    version: Mapped[int] = mapped_column(default=0)
