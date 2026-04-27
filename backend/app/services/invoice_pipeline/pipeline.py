"""
AI Invoice Processing Pipeline — orchestrates all three stages.

Stage 1: Layout analysis / text extraction
Stage 2: Field extraction via Claude
Stage 3: Validation + review routing
"""

import logging
from decimal import Decimal

from .extractor import extract_with_claude_vision
from .models import ExtractedLineItem, InvoiceExtractionResult, InvoiceHeader

logger = logging.getLogger(__name__)

_LINE_TOTAL_TOLERANCE = Decimal("0.02")
_FOOTER_TOTAL_TOLERANCE = Decimal("0.05")


def run_pipeline(
    file_bytes: bytes,
    filename: str,
    api_key: str,
    confidence_threshold: float,
    ocr_engine_path: str | None = None,
) -> InvoiceExtractionResult:
    # Always use Claude Vision for extraction.
    #
    # Text-based extraction (pdfplumber → plain text → Claude) looked attractive
    # but consistently fails on multi-column invoices: narrow column widths cause
    # numbers to bleed across column boundaries in the extracted text, so Claude
    # reads the right digits but in the wrong column (e.g. Menny=4 instead of 12).
    # Claude Vision reads the rendered page image directly — column positions are
    # visually unambiguous, making extraction reliable for both text-based and
    # scanned PDFs as well as image uploads.
    logger.info("Routing %s through Claude Vision", filename)
    header, line_items = extract_with_claude_vision(file_bytes, api_key, filename=filename)
    line_items = _drop_fee_lines(line_items)

    document_warning: str | None = None

    if header.document_type == "delivery_note":
        # Delivery notes have quantities but no prices — mark every item so the
        # UI can warn the user and skip costing validation entirely.
        document_warning = (
            "This appears to be a delivery note (szállítólevél), not a price invoice. "
            "Quantities have been extracted but no prices are available. "
            "This document cannot be approved for inventory costing."
        )
        for item in line_items:
            if "delivery_note_no_price" not in item.flags:
                item.flags.append("delivery_note_no_price")
        # Skip numeric validation — it would all fail with zero prices
        flagged = line_items
        auto_accepted: list = []
    else:
        line_items = _validate_line_items(line_items)
        line_items = _route(line_items, confidence_threshold)
        flagged = [i for i in line_items if i.flags]
        auto_accepted = [i for i in line_items if not i.flags]

    computed_total = sum((i.line_total for i in line_items), Decimal("0"))
    footer_discrepancy = _check_footer(computed_total, header)

    overall_confidence = (
        sum(i.confidence for i in line_items) / len(line_items)
        if line_items else 0.0
    )

    return InvoiceExtractionResult(
        header=header,
        line_items=line_items,
        overall_confidence=round(overall_confidence, 3),
        requires_review=len(flagged) > 0,
        auto_accepted_count=len(auto_accepted),
        flagged_count=len(flagged),
        raw_text="",
        computed_net_total=str(computed_total.quantize(Decimal("0.01"))),
        footer_discrepancy=footer_discrepancy,
        document_warning=document_warning,
    )


# Line types that are purely administrative and carry no physical goods.
# "visszaváltási díj" (bottle deposit) IS a real cost and stays in — it gets
# booked as a product line so it appears in inventory/costing.
_FEE_KEYWORDS = (
    "packaging fee",
    "deposit fee",
    "díjtétel",
    "dijtétel",
)


def _drop_fee_lines(items: list[ExtractedLineItem]) -> list[ExtractedLineItem]:
    """
    Remove non-product fee lines (e.g. bottle deposit, packaging surcharge)
    before validation so they don't pollute the extracted line item list or
    trigger false confidence flags.
    """
    kept = []
    for item in items:
        name_lower = item.product_name.lower()
        if any(kw in name_lower for kw in _FEE_KEYWORDS):
            logger.info("Dropping fee line: %r", item.product_name)
            continue
        kept.append(item)
    return kept


def _validate_line_items(items: list[ExtractedLineItem]) -> list[ExtractedLineItem]:
    """Apply item-level numeric constraint checks."""
    for item in items:
        if item.quantity <= 0:
            item.flags.append("invalid_quantity")

        if item.unit_price <= Decimal("0"):
            item.flags.append("invalid_unit_price")

        if item.quantity > 0 and item.unit_price > Decimal("0"):
            # Suppliers use two different pricing conventions:
            #   A) Egységár is price-per-pack:  Nettó ár = Menny × Egységár
            #   B) Egységár is price-per-unit:  Nettó ár = (Menny × Db/Csom) × Egységár
            # We accept either — only flag when neither explains the total.
            pack = Decimal(str(item.packaging_size)) if item.packaging_size > 1 else Decimal("1")
            expected_per_pack = (item.unit_price * item.quantity).quantize(Decimal("0.01"))
            expected_per_unit = (item.unit_price * item.quantity * pack).quantize(Decimal("0.01"))

            if item.line_total == Decimal("0"):
                # No line total extracted — derive it (prefer per-pack when pack=1)
                item.line_total = expected_per_unit if pack > 1 else expected_per_pack
            else:
                diff_pack = abs(item.line_total - expected_per_pack)
                diff_unit = abs(item.line_total - expected_per_unit)
                tol_pack = expected_per_pack * _LINE_TOTAL_TOLERANCE
                tol_unit = expected_per_unit * _LINE_TOTAL_TOLERANCE
                if diff_pack > tol_pack and diff_unit > tol_unit:
                    item.flags.append("line_total_mismatch")

    return items


def _check_footer(
    computed_total: Decimal,
    header: InvoiceHeader,
) -> str | None:
    """
    Compare computed line total against invoice footer.
    Returns a discrepancy message if totals don't match, None if OK.
    Footer mismatch is an invoice-level concern, not per-item.
    """
    validation_total = header.footer_net_total or header.footer_total
    if not validation_total or validation_total <= Decimal("0"):
        return None

    diff = abs(computed_total - validation_total)
    tolerance = validation_total * _FOOTER_TOTAL_TOLERANCE

    if diff > tolerance:
        return (
            f"Computed net total {computed_total:,.2f} "
            f"vs invoice {validation_total:,.2f} "
            f"(difference {diff:,.2f})"
        )
    return None


def _route(items: list[ExtractedLineItem], threshold: float) -> list[ExtractedLineItem]:
    """Flag items whose confidence is below the configured threshold."""
    for item in items:
        if item.confidence < threshold and "low_confidence" not in item.flags:
            item.flags.append("low_confidence")
    return items