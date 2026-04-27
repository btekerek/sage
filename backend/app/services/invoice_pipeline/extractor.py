"""
Stage 2 of the invoice pipeline: field extraction via Claude.

Two extraction paths:
  • Text path  — pdfplumber extracted readable text → chunked text prompts
  • Vision path — scanned PDF / image → pages converted to PNG → Claude vision
"""

import base64
import json
import logging
from decimal import Decimal, InvalidOperation
from io import BytesIO

import anthropic
from anthropic.types import TextBlock

from .models import ExtractedLineItem, InvoiceHeader

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """
You are an invoice data extraction assistant.
Your only job is to read supplier invoice text and return structured JSON.
Be conservative with confidence scores: only give 1.0 when the value is
completely unambiguous in the text.
""".strip()

_USER_PROMPT_TEMPLATE = """
Extract all line items from the following invoice text.

Return ONLY valid JSON — no explanation, no markdown, no code fences.
Use exactly this structure:

{{
  "supplier_name": "string or null",
  "invoice_ref": "string or null",
  "invoice_date": "string or null",
  "footer_total": number or null,
  "footer_net_total": number or null,
  "line_items": [
    {{
      "product_name": "string",
      "quantity": integer,
      "unit": "string (e.g. kg, pcs, box, litre)",
      "unit_price": number,
      "line_total": number,
      "packaging_size": integer,
      "confidence": float between 0.0 and 1.0
    }}
  ]
}}

Rules:
- footer_total is the GROSS/BRUTTO total (VAT included)
- footer_net_total is the NET/NETTO total (before VAT) — use this for validation
- If only one total is present, put it in footer_net_total and set footer_total to null

METRO-FORMAT INVOICES — column order is:
  Csom.Egys | Db/Csom | Menny | egys.ár | Egységár | Nettó ár
  - "Db/Csom" (2nd column) = packaging_size  → units per package, e.g. 1, 6, 12 (usually a small number)
  - "Menny"   (3rd column) = quantity        → number of packages ordered (usually the larger number)

Example row:   PIROS ALMA 13KG/KARTON  |  KA  |  1  |  2  |  ...
  → packaging_size = 1  (the Db/Csom column value)
  → quantity       = 2  (the Menny column value)
  NOTE: "13KG/KARTON" describes weight/volume — do NOT use 13 as packaging_size.

COLUMN MAPPING RULES (apply to all invoice formats):
- quantity   = how many packages/units were ORDERED (the "how many did you buy?" number)
- packaging_size = how many individual items are INSIDE each package (the multiplier)

On METRO invoices specifically, columns appear in this order:
  Csom.Egys | Db/Csom | Menny | egys.ár | Egységár | Nettó ár
  - "Db/Csom" (2nd column) → packaging_size  (units inside one package, usually small: 1, 6, 12)
  - "Menny"   (3rd column) → quantity         (packages ordered, usually the larger number)

On STANDARD invoices (no Metro columns), use the printed labels:
  - "Qty", "Quantity", "Mennyiség", "Amount" → quantity
  - "Pack size", "Units/case", "DB/CS" → packaging_size

General rules for all formats:
- "XKG", "XG", "XL", "XML" in a product name describe WEIGHT or VOLUME — NEVER use these as packaging_size
- packaging_size only from explicit count indicators: "Db/Csom" column, "6DB/KARTON", "CASE OF 12", "Pack of 6"
- If packaging_size is not stated, default to 1
- unit_price = price per package as printed on the invoice
- line_total = the NET price printed on the invoice for this line
- confidence = 1.0 only when the value is explicitly printed and unambiguous
- confidence = 0.7 when you inferred the value from context
- confidence = 0.4 when you had to guess
- If a numeric field is missing, use 0 and set confidence to 0.3
- quantity must be an integer (round if needed)

Invoice text:
---
{invoice_text}
---
""".strip()


def extract_with_claude(
    invoice_text: str,
    api_key: str,
    model: str = "claude-haiku-4-5",
) -> tuple[InvoiceHeader, list[ExtractedLineItem]]:
    """
    Call the Claude API to extract structured data from invoice text.
    Large invoices are split into chunks and results merged.
    Returns (header, line_items).
    """
    client = anthropic.Anthropic(api_key=api_key)

    # Split into chunks of 6000 chars with 500 char overlap
    chunk_size = 6000
    overlap = 500
    chunks: list[str] = []

    if len(invoice_text) <= chunk_size:
        chunks = [invoice_text]
    else:
        chunks.append(invoice_text[:chunk_size])
        pos = chunk_size - overlap
        while pos < len(invoice_text):
            chunks.append(invoice_text[pos:pos + chunk_size])
            pos += chunk_size - overlap

    all_line_items: list[ExtractedLineItem] = []
    header = InvoiceHeader()

    for i, chunk in enumerate(chunks):
        prompt = _USER_PROMPT_TEMPLATE.format(invoice_text=chunk)

        try:
            message = client.messages.create(
                model=model,
                max_tokens=4096,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIError as exc:
            raise ValueError(f"Claude API error: {exc}") from exc

        block = message.content[0]
        if not isinstance(block, TextBlock):
            raise ValueError("Unexpected response type from Claude API — expected text block.")

        raw = block.text.strip()

        # Strip accidental markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Skipping unparseable chunk %d", i)
            continue

        # First chunk provides the base header
        if i == 0:
            header = InvoiceHeader(
                supplier_name=data.get("supplier_name"),
                invoice_ref=data.get("invoice_ref"),
                invoice_date=data.get("invoice_date"),
                footer_total=_to_decimal(data.get("footer_total")),
                footer_net_total=_to_decimal(data.get("footer_net_total")),
            )
        else:
            # Subsequent chunks may contain the footer totals (last page)
            if data.get("footer_net_total"):
                header.footer_net_total = _to_decimal(data.get("footer_net_total"))
            if data.get("footer_total"):
                header.footer_total = _to_decimal(data.get("footer_total"))

        # Extract line items from every chunk
        for raw_item in data.get("line_items", []):
            unit_price = _to_decimal(raw_item.get("unit_price", 0)) or Decimal("0.00")
            line_total = _to_decimal(raw_item.get("line_total", 0)) or Decimal("0.00")
            quantity = int(raw_item.get("quantity", 0))
            confidence = float(raw_item.get("confidence", 0.5))
            packaging_size = int(raw_item.get("packaging_size", 1))

            all_line_items.append(
                ExtractedLineItem(
                    product_name=str(raw_item.get("product_name", "Unknown")),
                    quantity=quantity,
                    unit=str(raw_item.get("unit", "pcs")),
                    unit_price=unit_price,
                    line_total=line_total,
                    packaging_size=packaging_size,
                    confidence=confidence,
                    flags=[],
                )
            )

    # Deduplicate using normalized name + quantity + price key
    seen: set[tuple] = set()
    unique_items: list[ExtractedLineItem] = []
    for item in all_line_items:
        normalized = item.product_name.strip()
        for suffix in [' DB', ' KA', ' CS', ' ZA', ' DO', ' VD', ' ZS', ' PA', ' LA', ' TZ']:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)].strip()
        key = (normalized[:25], item.quantity, str(item.unit_price))
        if key not in seen:
            seen.add(key)
            unique_items.append(item)

    return header, unique_items


def _to_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return Decimal("0.00")


# ── Vision-based extraction (scanned PDFs / images) ────────────────────────────

_VISION_PROMPT = """
You are looking at a scanned supplier invoice or receipt image.
Extract all line items and return ONLY valid JSON — no explanation, no markdown, no code fences.

Use exactly this structure:
{
  "supplier_name": "string or null",
  "invoice_ref": "string or null",
  "invoice_date": "string or null",
  "footer_total": number or null,
  "footer_net_total": number or null,
  "line_items": [
    {
      "product_name": "string",
      "cikkszam": "string or empty string",
      "quantity": integer,
      "unit": "string (e.g. DB, kg, pcs)",
      "unit_price": number,
      "line_total": number,
      "packaging_size": integer,
      "vat_rate": number,
      "brutto_line_total": number,
      "confidence": float between 0.0 and 1.0
    }
  ]
}

Rules for reading the image:
- cikkszam = the article/SKU number printed at the far left of each line (e.g. "0436128", "0384280"). Copy it exactly as printed. Leave empty string "" if not present (e.g. retail receipts).
- footer_total is the GROSS/BRUTTO total (with VAT). footer_net_total is NET/NETTO (before VAT).
- If only one total is visible use footer_net_total and set footer_total to null.
- For RETAIL RECEIPTS (e.g. SPAR, Tesco, Lidl) the line format is often:
    N DB × PRICE Ft/DB  PRODUCT_NAME
  so quantity = N, unit_price = PRICE, line_total = N × PRICE, packaging_size = 1.
- For WHOLESALE INVOICES with Menny / Db/Csom columns:
    Db/Csom = packaging_size (units per package, usually small)
    Menny   = quantity (number of packages ordered, usually larger)
- Never use weight/volume numbers from product names (e.g. "1.5%" or "1KG") as packaging_size.
- If packaging_size is unclear, default to 1.
- unit_price = NET price per unit/package as printed (Egységár / Nettó egységár).
- line_total = NET price for the whole line as printed (Nettó ár); if not shown calculate quantity × unit_price.
- vat_rate = VAT percentage as a number, e.g. 5 or 27 (from the ÁFA% column). Use 0 if not shown.
- brutto_line_total = gross line total including VAT (Bruttó ár column). If not shown, calculate line_total × (1 + vat_rate/100).
- CONFIDENCE SCALE — be generous when values are clearly printed:
    1.0 = value is explicitly printed and clearly legible in the image
    0.9 = value is printed but partially obscured or requires minor reading
    0.7 = value was calculated/inferred (e.g. line_total derived from qty × price)
    0.4 = value is uncertain or ambiguous
    0.3 = field missing or illegible, using 0
- A line where all values are cleanly printed should have confidence 1.0.
- quantity must be an integer.
""".strip()


def extract_with_claude_vision(
    file_bytes: bytes,
    api_key: str,
    model: str = "claude-haiku-4-5",
    filename: str = "invoice.pdf",
) -> tuple[InvoiceHeader, list[ExtractedLineItem]]:
    """
    Vision-based extraction for any invoice file.
    PDFs are rendered page-by-page via pypdfium2 (no system deps).
    Images are sent directly as base64.
    All pages/images are sent to Claude in one message.
    """
    images_b64: list[str] = []
    lower = filename.lower()

    if lower.endswith((".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp")):
        # Image upload — send directly
        ext = lower.rsplit(".", 1)[-1]
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "tiff": "image/tiff", "bmp": "image/bmp", "webp": "image/webp"}.get(ext, "image/png")
        images_b64.append((base64.b64encode(file_bytes).decode("utf-8"), mime))
    else:
        # PDF — render each page to PNG via pypdfium2
        try:
            import pypdfium2  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ValueError(
                "pypdfium2 is required for PDF extraction but is not installed."
            ) from exc

        pdf = pypdfium2.PdfDocument(file_bytes)
        for i, page in enumerate(pdf):
            if i >= 10:
                break
            bitmap = page.render(scale=2.0)
            pil_image = bitmap.to_pil()
            buf = BytesIO()
            pil_image.save(buf, format="PNG", optimize=True)
            images_b64.append((base64.b64encode(buf.getvalue()).decode("utf-8"), "image/png"))

    if not images_b64:
        return InvoiceHeader(), []

    # ── Build multi-modal message ─────────────────────────────────────────
    content: list[dict] = []
    for b64, mime in images_b64:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": mime, "data": b64},
        })
    content.append({"type": "text", "text": _VISION_PROMPT})

    api_client = anthropic.Anthropic(api_key=api_key)
    try:
        message = api_client.messages.create(
            model=model,
            max_tokens=8192,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.APIError as exc:
        raise ValueError(f"Claude Vision API error: {exc}") from exc

    block = message.content[0]
    if not isinstance(block, TextBlock):
        raise ValueError("Unexpected response type from Claude Vision API — expected text block.")

    raw = block.text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Vision extractor returned unparseable JSON")
        return InvoiceHeader(), []

    header = InvoiceHeader(
        supplier_name=data.get("supplier_name"),
        invoice_ref=data.get("invoice_ref"),
        invoice_date=data.get("invoice_date"),
        footer_total=_to_decimal(data.get("footer_total")),
        footer_net_total=_to_decimal(data.get("footer_net_total")),
    )

    line_items: list[ExtractedLineItem] = []
    for raw_item in data.get("line_items", []):
        vat_rate = float(raw_item.get("vat_rate", 0) or 0)
        net_total = _to_decimal(raw_item.get("line_total", 0)) or Decimal("0.00")
        brutto_raw = _to_decimal(raw_item.get("brutto_line_total", 0))
        # Fall back to calculating brutto if not provided
        if not brutto_raw or brutto_raw == Decimal("0"):
            brutto_raw = (net_total * Decimal(str(1 + vat_rate / 100))).quantize(Decimal("0.01"))
        line_items.append(
            ExtractedLineItem(
                product_name=str(raw_item.get("product_name", "Unknown")),
                cikkszam=str(raw_item.get("cikkszam", "") or "").strip(),
                quantity=int(raw_item.get("quantity", 0)),
                unit=str(raw_item.get("unit", "pcs")),
                unit_price=_to_decimal(raw_item.get("unit_price", 0)) or Decimal("0.00"),
                line_total=net_total,
                packaging_size=int(raw_item.get("packaging_size", 1)),
                vat_rate=vat_rate,
                brutto_line_total=brutto_raw,
                confidence=float(raw_item.get("confidence", 0.5)),
                flags=[],
            )
        )

    return header, line_items