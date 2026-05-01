"""
Stage 1 of the invoice pipeline: PDF layout analysis.

Uses pdfplumber to extract words with bounding-box coordinates, then:
  1. Groups words into rows by Y-midpoint proximity.
  2. Detects column zones from header-row keyword positions.
  3. Maps each data row's words to the nearest column zone.
  4. Produces a LayoutRow per invoice line with exact Y-fraction for highlighting.

Column-zone detection avoids the "column bleed" problem that occurs when
raw concatenated text is sent to an LLM: narrow number columns run together
and Claude reads digits from the wrong column.  By assigning each word to a
column by its X position we pass only the logically correct value to Stage 2.

Returns a LayoutResult.  If the PDF is a scanned image (no selectable text),
pdfplumber returns no words and LayoutResult.has_content is False — the
pipeline then falls back to pure Claude Vision extraction.
"""

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── Column header patterns ──────────────────────────────────────────────────
# Each entry: (column_key, set_of_lowercase_triggers)
# English is the primary language; Hungarian terms are the fallback for
# supplier invoices that use Hungarian column headers.
_HEADER_PATTERNS: list[tuple[str, set[str]]] = [
    # Article / SKU number
    ("cikkszam", {
        # English
        "item no", "item #", "item code", "product code", "sku", "code",
        "ref", "art no", "article no", "article", "art.", "no.",
        # Hungarian
        "cikkszám", "cikkszam", "cikk", "cikkszám.",
    }),
    # Product / service description
    ("product", {
        # English
        "description", "product", "item", "name", "goods", "service",
        "product name", "item description", "details",
        # Hungarian
        "megnevezés", "megnevezes", "termék", "termek",
        "leírás", "leiras", "árucikk", "arucikk",
    }),
    # Packaging unit type (e.g. carton, pallet, box)
    ("pack_unit", {
        # English
        "pack unit", "case unit", "pack type", "package unit",
        "pack", "case", "uom", "unit type",
        # Hungarian
        "csom.egys", "csomegys", "csomag", "csomagolási egység",
    }),
    # Units per package (the multiplier, e.g. 6 bottles per case)
    ("pack_size", {
        # English
        "pack size", "units/case", "qty/pack", "per pack", "pack qty",
        "case size", "units per case", "items/pack", "pcs/pack",
        "pcs/case", "units/pack", "qty per pack",
        # Hungarian
        "db/csom", "db/cs", "db/csomag", "darab/csomag", "db/karton",
    }),
    # Order quantity (how many packs/units were ordered)
    ("quantity", {
        # English
        "qty", "quantity", "ordered", "order qty", "units", "count",
        "pieces", "pcs", "nos", "no of units",
        # Hungarian
        "menny", "mennyiség", "mennyiseg", "rendelt", "rendelt menny",
    }),
    # Unit of measure label (e.g. kg, pcs, box, litre)
    ("unit", {
        # English
        "unit", "uom", "u/m", "measure", "unit of measure",
        "um", "u.m.",
        # Hungarian
        "egys", "egység", "egyseg", "me", "mértékegység", "mertekegyseg",
    }),
    # Net unit price
    ("unit_price", {
        # English
        "unit price", "price", "rate", "each", "per unit", "list price",
        "net price", "price each", "net unit price", "cost", "unit cost",
        # Hungarian
        "egységár", "egysegar", "egys.ár", "egys.ar",
        "nettó egységár", "netto egysegar",
        "ár/egység", "ar/egyseg", "nettó ár/egység", "netto ar/egyseg",
    }),
    # Net line total
    ("line_total", {
        # English
        "total", "net total", "line total", "amount", "net amount",
        "subtotal", "ext", "extended", "ext price", "net",
        "line amount", "net value",
        # Hungarian
        "nettó ár", "netto ar", "nettóár", "nettoar",
        "nettó összeg", "netto osszeg",
        "összeg", "osszeg", "nettó érték", "netto ertek",
    }),
    # VAT / tax rate
    ("vat_rate", {
        # English
        "vat%", "vat", "tax%", "tax", "gst", "gst%",
        "vat rate", "tax rate",
        # Hungarian
        "áfa%", "afa%", "áfa", "afa",
    }),
    # Gross / brutto line total (VAT included)
    ("brutto", {
        # English
        "gross", "gross total", "incl vat", "gross amount",
        "gross price", "total incl", "price incl vat",
        # Hungarian
        "bruttó ár", "brutto ar", "bruttóár", "bruttoar",
        "bruttó összeg", "brutto osszeg", "bruttó", "brutto",
    }),
]

_ROW_Y_TOLERANCE_PT = 5.0  # points — words within this vertical range = same row
_HEADER_MIN_SCORE = 2       # how many header keywords needed to accept a row as the header


@dataclass
class LayoutWord:
    text: str
    x0: float
    y0: float   # distance from top of page (pdfplumber convention)
    x1: float
    y1: float
    page: int
    page_height: float

    @property
    def x_mid(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def y_mid(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class ColumnZone:
    key: str        # e.g. "quantity", "unit_price", "line_total"
    x_center: float
    x_left: float
    x_right: float


@dataclass
class LayoutRow:
    """One data row extracted by position."""
    page: int
    y_fraction: float           # 0.0 = top of page, 1.0 = bottom
    columns: dict[str, str]     # column_key → raw text
    raw_text: str               # full concatenated row text


@dataclass
class LayoutResult:
    rows: list[LayoutRow] = field(default_factory=list)
    has_content: bool = False
    raw_text_by_page: dict[int, str] = field(default_factory=dict)
    page_count: int = 0


# ── Public entry point ──────────────────────────────────────────────────────

def extract_layout(file_bytes: bytes, filename: str = "invoice.pdf") -> LayoutResult:
    """
    Run Stage 1 layout extraction on a PDF or image file.
    Images and scanned PDFs return LayoutResult(has_content=False).
    """
    lower = filename.lower()
    if not lower.endswith(".pdf"):
        # Images go straight to Vision — no layout extraction possible
        return LayoutResult(has_content=False)

    try:
        import pdfplumber  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("pdfplumber not installed — skipping layout extraction")
        return LayoutResult(has_content=False)

    from io import BytesIO
    result = LayoutResult()

    try:
        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            result.page_count = len(pdf.pages)
            all_words: list[LayoutWord] = []
            page_texts: dict[int, str] = {}

            for page_num, page in enumerate(pdf.pages, start=1):
                words = page.extract_words(
                    x_tolerance=2,
                    y_tolerance=2,
                    keep_blank_chars=False,
                    use_text_flow=False,
                )
                page_height = float(page.height)
                for w in words:
                    all_words.append(LayoutWord(
                        text=str(w["text"]),
                        x0=float(w["x0"]),
                        y0=float(w["top"]),
                        x1=float(w["x1"]),
                        y1=float(w["bottom"]),
                        page=page_num,
                        page_height=page_height,
                    ))
                page_texts[page_num] = page.extract_text() or ""

            result.raw_text_by_page = page_texts
    except Exception as exc:
        logger.warning("pdfplumber failed on %s: %s", filename, exc)
        return LayoutResult(has_content=False)

    if not all_words:
        logger.info("No selectable text in %s — scanned PDF, using Vision", filename)
        return LayoutResult(has_content=False, page_count=result.page_count)

    # Group words by (page, row-bucket)
    rows_by_page = _group_into_rows(all_words)
    if not rows_by_page:
        return LayoutResult(has_content=False, page_count=result.page_count,
                            raw_text_by_page=page_texts)

    # Detect column zones from the header row across all pages
    column_zones = _detect_column_zones(rows_by_page)
    logger.info("Detected column zones: %s", [z.key for z in column_zones])

    # Build LayoutRows
    data_rows = _build_layout_rows(rows_by_page, column_zones)
    result.rows = data_rows
    result.has_content = len(data_rows) > 0
    result.raw_text_by_page = page_texts
    return result


# ── Internal helpers ────────────────────────────────────────────────────────

def _group_into_rows(
    words: list[LayoutWord],
) -> dict[int, list[list[LayoutWord]]]:
    """Group words into rows by page, bucketing by Y-midpoint proximity."""
    from collections import defaultdict
    by_page: dict[int, list[LayoutWord]] = defaultdict(list)
    for w in words:
        by_page[w.page].append(w)

    result: dict[int, list[list[LayoutWord]]] = {}
    for page_num, page_words in sorted(by_page.items()):
        page_words.sort(key=lambda w: (w.y_mid, w.x0))
        rows: list[list[LayoutWord]] = []
        current_row: list[LayoutWord] = []
        last_y: float | None = None

        for word in page_words:
            if last_y is None or abs(word.y_mid - last_y) <= _ROW_Y_TOLERANCE_PT:
                current_row.append(word)
                last_y = (last_y + word.y_mid) / 2 if last_y else word.y_mid
            else:
                if current_row:
                    current_row.sort(key=lambda w: w.x0)
                    rows.append(current_row)
                current_row = [word]
                last_y = word.y_mid

        if current_row:
            current_row.sort(key=lambda w: w.x0)
            rows.append(current_row)

        result[page_num] = rows
    return result


def _detect_column_zones(
    rows_by_page: dict[int, list[list[LayoutWord]]],
) -> list[ColumnZone]:
    """
    Find the table header row (the row with the most column-header hits)
    and derive column X-zones from the header word positions.
    """
    best_row: list[LayoutWord] = []
    best_score = 0

    for page_rows in rows_by_page.values():
        for row in page_rows:
            row_text = " ".join(w.text for w in row).lower()
            score = sum(
                1 for _, triggers in _HEADER_PATTERNS
                if any(t in row_text for t in triggers)
            )
            if score > best_score:
                best_score = score
                best_row = row

    if best_score < _HEADER_MIN_SCORE:
        logger.info("No confident header row found (best score %d)", best_score)
        return []

    zones: list[ColumnZone] = []
    for key, triggers in _HEADER_PATTERNS:
        for word in best_row:
            wl = word.text.lower()
            if any(t in wl for t in triggers):
                zones.append(ColumnZone(
                    key=key,
                    x_center=word.x_mid,
                    x_left=word.x0,
                    x_right=word.x1,
                ))
                break  # first match wins for this column key

    # Sort zones left to right
    zones.sort(key=lambda z: z.x_center)

    # Expand zone boundaries to cover the gap between adjacent zones
    for i, zone in enumerate(zones):
        if i > 0:
            mid = (zones[i - 1].x_center + zone.x_center) / 2
            zones[i - 1].x_right = mid
            zone.x_left = mid
        if i == 0:
            zone.x_left = 0.0
        if i == len(zones) - 1:
            zone.x_right = 9999.0

    return zones


def _assign_word_to_zone(word: LayoutWord, zones: list[ColumnZone]) -> str | None:
    """Return the key of the column zone that best contains this word's X-midpoint."""
    for zone in zones:
        if zone.x_left <= word.x_mid < zone.x_right:
            return zone.key
    return None


def _build_layout_rows(
    rows_by_page: dict[int, list[list[LayoutWord]]],
    column_zones: list[ColumnZone],
) -> list[LayoutRow]:
    """
    For each row that looks like a data row, assign words to columns and
    compute y_fraction.  Skip rows that are header/footer candidates.
    """
    layout_rows: list[LayoutRow] = []
    header_keys = {z.key for z in column_zones}

    for page_num, rows in sorted(rows_by_page.items()):
        for row in rows:
            if not row:
                continue
            page_height = row[0].page_height
            y_mid = sum(w.y_mid for w in row) / len(row)
            y_fraction = round(y_mid / page_height, 4) if page_height > 0 else 0.5

            raw_text = " ".join(w.text for w in row)

            if column_zones:
                cols: dict[str, list[str]] = {k: [] for k in header_keys}
                unassigned: list[str] = []
                for word in row:
                    key = _assign_word_to_zone(word, column_zones)
                    if key:
                        cols[key].append(word.text)
                    else:
                        unassigned.append(word.text)

                col_values = {k: " ".join(v).strip() for k, v in cols.items() if v}
            else:
                col_values = {}

            layout_rows.append(LayoutRow(
                page=page_num,
                y_fraction=y_fraction,
                columns=col_values,
                raw_text=raw_text,
            ))

    return layout_rows


def layout_to_text_summary(result: LayoutResult) -> str:
    """
    Render a LayoutResult as a compact structured text string for inclusion
    in the reconciliation prompt sent to Claude Vision.
    Format: one row per line with labelled columns.
    """
    lines: list[str] = []
    for i, row in enumerate(result.rows):
        if not row.columns and not row.raw_text.strip():
            continue
        parts = [f"[ROW {i+1} p{row.page} y={row.y_fraction:.3f}]"]
        for key, val in row.columns.items():
            if val:
                parts.append(f"{key}={val!r}")
        if not row.columns:
            parts.append(f"text={row.raw_text!r}")
        lines.append("  ".join(parts))
    return "\n".join(lines)
