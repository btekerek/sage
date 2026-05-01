"""
AI Invoice Processing Pipeline — three-stage orchestration.

Stage 1: Layout extraction (pdfplumber)
    Extract words with bounding-box coordinates, group into rows, detect
    column zones from header-keyword positions, assign each numeric value
    to its correct column by X position.  Produces a LayoutResult with
    y_fraction for each row (used by the frontend PDF highlight feature).

    Avoids the "column bleed" problem: raw concatenated text causes Claude
    to read numbers from the wrong column.  Bounding-box assignment is
    deterministic and column-aware.

Stage 2: Reconciliation / fallback via Claude Vision
    A) If Stage 1 produced content (machine-readable PDF):
       Send the layout summary + page images to Claude Vision.  Claude
       verifies each value against the image rather than extracting from
       scratch — higher accuracy, lower token cost.
    B) If Stage 1 found no text (scanned PDF or image upload):
       Fall back to pure Claude Vision extraction (original behaviour).

Stage 3: Validation + review routing (unchanged)
    Numeric constraint checks, line-total verification, confidence-based
    flagging for manager review.
"""

import base64
import logging
from decimal import Decimal
from io import BytesIO

from .extractor import (
    extract_with_claude_vision,
    reconcile_with_claude_vision,
)
from .layout_extractor import extract_layout, layout_to_text_summary
from .models import ExtractedLineItem, InvoiceExtractionResult, InvoiceHeader

logger = logging.getLogger(__name__)

_LINE_TOTAL_TOLERANCE = Decimal("0.02")
_FOOTER_TOTAL_TOLERANCE = Decimal("0.05")
_MIN_LAYOUT_ROWS = 2    # need at least this many rows to use Stage 1 path


def run_pipeline(
    file_bytes: bytes,
    filename: str,
    api_key: str,
    confidence_threshold: float,
    ocr_engine_path: str | None = None,
) -> InvoiceExtractionResult:
    """
    Run the three-stage invoice extraction pipeline and return a validated result.
    """
    # ── Stage 1: Layout extraction ────────────────────────────────────────
    layout = extract_layout(file_bytes, filename)
    logger.info(
        "Layout extraction: has_content=%s, rows=%d, pages=%d",
        layout.has_content, len(layout.rows), layout.page_count,
    )

    # ── Render page images for Vision (Stage 2) ───────────────────────────
    images_b64 = _render_images(file_bytes, filename)

    # ── Stage 2: Reconciliation or Vision-only ───────────────────────────
    if layout.has_content and len(layout.rows) >= _MIN_LAYOUT_ROWS and images_b64:
        logger.info(
            "Stage 2: reconciling layout (%d rows) with Claude Vision", len(layout.rows)
        )
        layout_summary = layout_to_text_summary(layout)
        try:
            header, line_items = reconcile_with_claude_vision(
                layout_summary, images_b64, api_key, filename=filename
            )
            logger.info("Reconciliation produced %d line items", len(line_items))
        except Exception as exc:
            logger.warning("Reconciliation failed (%s) — falling back to Vision-only", exc)
            header, line_items = extract_with_claude_vision(
                file_bytes, api_key, filename=filename
            )
    else:
        logger.info("Stage 2: Vision-only extraction (scanned PDF or image)")
        header, line_items = extract_with_claude_vision(
            file_bytes, api_key, filename=filename
        )

    line_items = _drop_fee_lines(line_items)

    # ── Stage 3: Validation + review routing ─────────────────────────────
    document_warning: str | None = None

    if header.document_type == "delivery_note":
        document_warning = (
            "This appears to be a delivery note, not a price invoice. "
            "Quantities have been extracted but no prices are available. "
            "This document cannot be approved for inventory costing."
        )
        for item in line_items:
            if "delivery_note_no_price" not in item.flags:
                item.flags.append("delivery_note_no_price")
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


def _render_images(file_bytes: bytes, filename: str) -> list[tuple[str, str]]:
    """
    Render all pages of a PDF to PNG base64 strings, or wrap an image directly.
    Returns a list of (base64_string, mime_type) tuples.
    """
    lower = filename.lower()
    images_b64: list[tuple[str, str]] = []

    if lower.endswith((".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp")):
        ext = lower.rsplit(".", 1)[-1]
        mime = {
            "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "tiff": "image/tiff", "bmp": "image/bmp", "webp": "image/webp",
        }.get(ext, "image/png")
        images_b64.append((base64.b64encode(file_bytes).decode("utf-8"), mime))
    else:
        try:
            import pypdfium2  # type: ignore[import-untyped]
            pdf = pypdfium2.PdfDocument(file_bytes)
            for i, page in enumerate(pdf):
                if i >= 10:
                    break
                bitmap = page.render(scale=2.0)
                pil_image = bitmap.to_pil()
                buf = BytesIO()
                pil_image.save(buf, format="PNG", optimize=True)
                images_b64.append(
                    (base64.b64encode(buf.getvalue()).decode("utf-8"), "image/png")
                )
        except ImportError:
            logger.warning("pypdfium2 not installed — Vision stage skipped")
        except Exception as exc:
            logger.warning("PDF render failed: %s", exc)

    return images_b64


# ── Fee-line filter ────────────────────────────────────────────────────────

_FEE_KEYWORDS = (
    "packaging fee",
    "deposit fee",
    "díjtétel",
    "dijtétel",
)


def _drop_fee_lines(items: list[ExtractedLineItem]) -> list[ExtractedLineItem]:
    kept = []
    for item in items:
        name_lower = item.product_name.lower()
        if any(kw in name_lower for kw in _FEE_KEYWORDS):
            logger.info("Dropping fee line: %r", item.product_name)
            continue
        kept.append(item)
    return kept


# ── Numeric validation ─────────────────────────────────────────────────────

def _validate_line_items(items: list[ExtractedLineItem]) -> list[ExtractedLineItem]:
    for item in items:
        if item.quantity <= 0:
            item.flags.append("invalid_quantity")
        if item.unit_price <= Decimal("0"):
            item.flags.append("invalid_unit_price")
        if item.quantity > 0 and item.unit_price > Decimal("0"):
            pack = Decimal(str(item.packaging_size)) if item.packaging_size > 1 else Decimal("1")
            expected_per_pack = (item.unit_price * item.quantity).quantize(Decimal("0.01"))
            expected_per_unit = (item.unit_price * item.quantity * pack).quantize(Decimal("0.01"))
            if item.line_total == Decimal("0"):
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
    for item in items:
        if item.confidence < threshold and "low_confidence" not in item.flags:
            item.flags.append("low_confidence")
    return items
