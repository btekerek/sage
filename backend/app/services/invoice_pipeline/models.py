"""Pydantic models for the AI invoice processing pipeline."""

from decimal import Decimal
from pydantic import BaseModel


class ExtractedLineItem(BaseModel):
    """A single line item extracted from a supplier invoice."""

    product_name: str
    cikkszam: str = ""             # Article / SKU number for reliable PDF highlighting
    quantity: int
    unit: str
    unit_price: Decimal
    line_total: Decimal
    packaging_size: int = 1
    vat_rate: float = 0.0          # ÁFA% e.g. 5.0, 27.0
    brutto_line_total: Decimal = Decimal("0")   # Bruttó ár (VAT included)
    confidence: float
    flags: list[str]


class InvoiceHeader(BaseModel):
    """Supplier and reference info extracted from invoice header."""

    supplier_name: str | None = None
    invoice_ref: str | None = None
    invoice_date: str | None = None
    footer_total: Decimal | None = None
    footer_net_total: Decimal | None = None


class InvoiceExtractionResult(BaseModel):
    """Full result returned by the pipeline to the API layer."""

    header: InvoiceHeader
    line_items: list[ExtractedLineItem]
    overall_confidence: float
    requires_review: bool
    auto_accepted_count: int
    flagged_count: int
    raw_text: str
    computed_net_total: str = "0.00"
    footer_discrepancy: str | None = None