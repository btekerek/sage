"""
AI Invoice Processing Pipeline — orchestrates all three stages.

Stage 1: Layout analysis / text extraction
    - pdfplumber for digital PDFs (fast, accurate)
    - pytesseract OCR fallback for scanned images

Stage 2: Field extraction via Claude  (see extractor.py)

Stage 3: Validation + review routing
    - Numeric constraint checks (line_total ≈ qty × unit_price)
    - Footer cross-check
    - Confidence threshold routing
"""

import logging
from decimal import Decimal
from io import BytesIO

import pdfplumber
from PIL import Image

from .extractor import extract_with_claude
from .models import ExtractedLineItem, InvoiceExtractionResult, InvoiceHeader

logger = logging.getLogger(__name__)

# Tolerance for line_total vs qty*unit_price mismatch (2 %)
_LINE_TOTAL_TOLERANCE = Decimal("0.02")
# Tolerance for footer_total vs sum(line_totals) (1 %)
_FOOTER_TOTAL_TOLERANCE = Decimal("0.01")


def run_pipeline(
    file_bytes: bytes,
    filename: str,
    api_key: str,
    confidence_threshold: float,
    ocr_engine_path: str | None = None,
) -> InvoiceExtractionResult:
    """
    Entry point.  Feed it the raw bytes of an uploaded invoice file and get
    back a fully-validated InvoiceExtractionResult.
    """
    # ── Stage 1: extract text ──────────────────────────────────────────────
    raw_text = _extract_text(file_bytes, filename, ocr_engine_path)
    if not raw_text.strip():
        raise ValueError("Could not extract any text from the uploaded file.")

    # ── Stage 2: Claude extraction ─────────────────────────────────────────
    header, line_items = extract_with_claude(raw_text, api_key)

    # ── Stage 3: validate + route ──────────────────────────────────────────
    line_items = _validate(line_items, header)
    line_items = _route(line_items, confidence_threshold)

    flagged = [i for i in line_items if i.flags]
    auto_accepted = [i for i in line_items if not i.flags]
    overall_confidence = (
        sum(i.confidence for i in line_items) / len(line_items) if line_items else 0.0
    )

    return InvoiceExtractionResult(
        header=header,
        line_items=line_items,
        overall_confidence=round(overall_confidence, 3),
        requires_review=len(flagged) > 0,
        auto_accepted_count=len(auto_accepted),
        flagged_count=len(flagged),
        raw_text=raw_text,
    )


# ── Stage 1 helpers ────────────────────────────────────────────────────────


def _extract_text(file_bytes: bytes, filename: str, ocr_path: str | None) -> str:
    """
    Try pdfplumber first.  If we get very little text (scanned PDF / image),
    fall back to pytesseract OCR.
    """
    text = ""
    lower = filename.lower()

    if lower.endswith(".pdf"):
        text = _extract_pdf(file_bytes)

    elif lower.endswith((".png", ".jpg", ".jpeg", ".tiff", ".bmp")):
        text = _ocr_image(file_bytes, ocr_path)

    # If PDF gave almost nothing, try OCR on each page as an image
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
        import pytesseract # type: ignore[import-untyped]

        if ocr_path:
            pytesseract.pytesseract.tesseract_cmd = ocr_path
        image = Image.open(BytesIO(file_bytes))
        return pytesseract.image_to_string(image)
    except Exception as exc:
        logger.warning("OCR failed: %s", exc)
        return ""


def _ocr_pdf_pages(file_bytes: bytes, ocr_path: str | None) -> str:
    """Render each PDF page as an image and OCR it."""
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


# ── Stage 3 helpers ────────────────────────────────────────────────────────


def _validate(
    items: list[ExtractedLineItem], header: InvoiceHeader
) -> list[ExtractedLineItem]:
    """Apply numeric constraint checks and populate item.flags."""
    computed_total = Decimal("0.00")

    for item in items:
        # Check 1: quantity must be positive
        if item.quantity <= 0:
            item.flags.append("invalid_quantity")

        # Check 2: unit_price must be positive
        if item.unit_price <= Decimal("0"):
            item.flags.append("invalid_unit_price")

        # Check 3: line_total ≈ qty × unit_price
        if item.quantity > 0 and item.unit_price > Decimal("0"):
            expected = (item.unit_price * item.quantity).quantize(Decimal("0.01"))
            if item.line_total == Decimal("0"):
                # Claude left it blank — fill it in
                item.line_total = expected
            else:
                diff = abs(item.line_total - expected)
                tolerance = expected * _LINE_TOTAL_TOLERANCE
                if diff > tolerance:
                    item.flags.append("line_total_mismatch")

        computed_total += item.line_total

    # Check 4: footer total cross-check
    if header.footer_total and header.footer_total > Decimal("0"):
        diff = abs(computed_total - header.footer_total)
        tolerance = header.footer_total * _FOOTER_TOTAL_TOLERANCE
        if diff > tolerance:
            logger.warning(
                "Footer total mismatch: computed=%s, stated=%s",
                computed_total,
                header.footer_total,
            )
            # Flag every item so the manager reviews all of them
            for item in items:
                if "footer_total_mismatch" not in item.flags:
                    item.flags.append("footer_total_mismatch")

    return items


def _route(items: list[ExtractedLineItem], threshold: float) -> list[ExtractedLineItem]:
    """Flag items whose confidence is below the configured threshold."""
    for item in items:
        if item.confidence < threshold and "low_confidence" not in item.flags:
            item.flags.append("low_confidence")
    return items
