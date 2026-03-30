"""
AI Invoice Processing Pipeline — orchestrates all three stages.

Stage 1: Layout analysis / text extraction
Stage 2: Field extraction via Claude
Stage 3: Validation + review routing
"""

import logging
from decimal import Decimal
from io import BytesIO

import pdfplumber
from PIL import Image

from .extractor import extract_with_claude
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
    raw_text = _extract_text(file_bytes, filename, ocr_engine_path)
    if not raw_text.strip():
        raise ValueError("Could not extract any text from the uploaded file.")

    header, line_items = extract_with_claude(raw_text, api_key)
    line_items = _validate_line_items(line_items)
    line_items = _route(line_items, confidence_threshold)

    computed_total = sum(i.line_total for i in line_items)
    footer_discrepancy = _check_footer(computed_total, header)

    flagged = [i for i in line_items if i.flags]
    auto_accepted = [i for i in line_items if not i.flags]
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
        raw_text=raw_text,
        computed_net_total=str(computed_total.quantize(Decimal("0.01"))),
        footer_discrepancy=footer_discrepancy,
    )


def _extract_text(file_bytes: bytes, filename: str, ocr_path: str | None) -> str:
    text = ""
    lower = filename.lower()

    if lower.endswith(".pdf"):
        text = _extract_pdf(file_bytes)
    elif lower.endswith((".png", ".jpg", ".jpeg", ".tiff", ".bmp")):
        text = _ocr_image(file_bytes, ocr_path)

    if len(text.strip()) < 80 and lower.endswith(".pdf"):
        logger.info("pdfplumber yielded little text — falling back to OCR")
        text = _ocr_pdf_pages(file_bytes, ocr_path)

    return text


def _extract_pdf(file_bytes: bytes) -> str:
    parts: list[str] = []
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            parts.append(page_text)
    return "\n".join(parts)


def _ocr_image(file_bytes: bytes, ocr_path: str | None) -> str:
    try:
        import pytesseract  # type: ignore[import-untyped]
        if ocr_path:
            pytesseract.pytesseract.tesseract_cmd = ocr_path
        image = Image.open(BytesIO(file_bytes))
        return pytesseract.image_to_string(image)
    except Exception as exc:
        logger.warning("OCR failed: %s", exc)
        return ""


def _ocr_pdf_pages(file_bytes: bytes, ocr_path: str | None) -> str:
    try:
        import pytesseract  # type: ignore[import-untyped]
        from pdf2image import convert_from_bytes  # type: ignore[import-untyped]
        if ocr_path:
            pytesseract.pytesseract.tesseract_cmd = ocr_path
        images = convert_from_bytes(file_bytes, dpi=200)
        return "\n".join(pytesseract.image_to_string(img) for img in images)
    except ImportError:
        logger.warning("pdf2image not installed — OCR fallback unavailable")
        return ""
    except Exception as exc:
        logger.warning("PDF OCR fallback failed: %s", exc)
        return ""


def _validate_line_items(items: list[ExtractedLineItem]) -> list[ExtractedLineItem]:
    """Apply item-level numeric constraint checks."""
    for item in items:
        if item.quantity <= 0:
            item.flags.append("invalid_quantity")

        if item.unit_price <= Decimal("0"):
            item.flags.append("invalid_unit_price")

        if item.quantity > 0 and item.unit_price > Decimal("0"):
            pack = Decimal(str(item.packaging_size)) if item.packaging_size > 1 else Decimal("1")
            expected = (item.unit_price * item.quantity * pack).quantize(Decimal("0.01"))
            if item.line_total == Decimal("0"):
                item.line_total = expected
            else:
                diff = abs(item.line_total - expected)
                tolerance = expected * _LINE_TOTAL_TOLERANCE
                if diff > tolerance:
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