"""
Stage 2 of the invoice pipeline: field extraction via Claude.

Sends the text extracted from the invoice document to Claude and asks it to
return structured JSON with per-field confidence scores.  The response is
parsed and converted into ExtractedLineItem instances.
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
  "line_items": [
    {{
      "product_name": "string",
      "quantity": integer,
      "unit": "string (e.g. kg, pcs, box, litre)",
      "unit_price": number,
      "line_total": number,
      "confidence": float between 0.0 and 1.0
    }}
  ]
}}

Rules:
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

    Returns (header, line_items).  Raises ValueError if the API returns
    unparseable content.
    """
    client = anthropic.Anthropic(api_key=api_key)

    prompt = _USER_PROMPT_TEMPLATE.format(invoice_text=invoice_text[:12000])

    try:
        message = client.messages.create(
            model=model,
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as exc:
        raise ValueError(f"Claude API error: {exc}") from exc

    block = message.content[0]
    if not isinstance(block, TextBlock):
        raise ValueError(
            "Unexpected response type from Claude API — expected text block."
        )
    raw = block.text.strip()

    # Strip accidental markdown fences if Claude adds them
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("Claude returned non-JSON: %s", raw[:500])
        raise ValueError(f"Claude returned non-JSON response: {exc}") from exc

    header = InvoiceHeader(
        supplier_name=data.get("supplier_name"),
        invoice_ref=data.get("invoice_ref"),
        invoice_date=data.get("invoice_date"),
        footer_total=_to_decimal(data.get("footer_total")),
    )

    line_items: list[ExtractedLineItem] = []
    for raw_item in data.get("line_items", []):
        unit_price = _to_decimal(raw_item.get("unit_price", 0)) or Decimal("0.00")
        line_total = _to_decimal(raw_item.get("line_total", 0)) or Decimal("0.00")
        quantity = int(raw_item.get("quantity", 0))
        confidence = float(raw_item.get("confidence", 0.5))

        line_items.append(
            ExtractedLineItem(
                product_name=str(raw_item.get("product_name", "Unknown")),
                quantity=quantity,
                unit=str(raw_item.get("unit", "pcs")),
                unit_price=unit_price,
                line_total=line_total,
                confidence=confidence,
                flags=[],  # validation flags added in pipeline.py
            )
        )

    return header, line_items


def _to_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return Decimal("0.00")
