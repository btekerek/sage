"""
Stage 2 of the invoice pipeline: field extraction via Claude.

Sends the text extracted from the invoice document to Claude and asks it to
return structured JSON with per-field confidence scores. Large invoices are
split into chunks and merged.
"""

import json
import logging
from decimal import Decimal, InvalidOperation

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
- quantity = number of PACKAGES ordered (how many boxes/cases/cartons delivered)
- packaging_size = units per package (e.g. 90 for "90DB/KARTON", 150 for a case of 150)
- "XKG", "XG", "XL", "XML" in the product name describe WEIGHT or VOLUME — never use these as packaging_size
- packaging_size only comes from explicit count indicators: "XDB/KARTON", the Csom.Egys column value, "CASE OF X"
- If unsure about packaging_size, default to 1
- unit_price = price per PACKAGE (as printed on the invoice)
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