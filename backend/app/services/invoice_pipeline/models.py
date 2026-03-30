"""Pydantic models for the AI invoice processing pipeline."""

from decimal import Decimal
from pydantic import BaseModel


class ExtractedLineItem(BaseModel):
    """A single line item extracted from a supplier invoice."""

    product_name: str
    quantity: int
    unit: str  # e.g. "kg", "pcs", "box"
    unit_price: Decimal
    line_total: Decimal
    confidence: float  # 0.0 (guessed) → 1.0 (certain)
    flags: list[str]   # e.g. ["line_total_mismatch", "low_confidence"]


class InvoiceHeader(BaseModel):
    """Supplier and reference info extracted from invoice header."""

    supplier_name: str | None = None
    invoice_ref: str | None = None
    invoice_date: str | None = None
    footer_total: Decimal | None = None


class InvoiceExtractionResult(BaseModel):
    """Full result returned by the pipeline to the API layer."""

    header: InvoiceHeader
    line_items: list[ExtractedLineItem]
    overall_confidence: float
    requires_review: bool          # True if any item is below threshold or flagged
    auto_accepted_count: int       # Items that passed threshold — no manager action needed
    flagged_count: int             # Items that need manager correction
    raw_text: str                  # Full extracted text, useful for debugging