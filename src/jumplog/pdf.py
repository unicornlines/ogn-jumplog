"""Native ReportLab renderer for the jump-ops log sheet (A4 landscape).

Layout is laid out by hand in fixed point coordinates; no Platypus, no
templates, no overlay. The page is split into three blocks:

    +--------------------------------------------------+
    | header strip (callsign / airport / date / op)    |
    +--------------------------------------------------+
    | column headers (2-line, grey)                    |
    | 15 lift rows (lift # pre-printed, OGN values     |
    | filled where available, the rest blank)          |
    +--------------------------------------------------+
    | footer block 1 (pilot / cycles / fuel / hobbs)   |
    | footer block 2 (engine reading at FL 90)         |
    +--------------------------------------------------+
"""

from __future__ import annotations

from dataclasses import dataclass

from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from jumplog.ogn import Lift

PAGE_W, PAGE_H = landscape(A4)            # (842, 595) pt
MARGIN = 10 * mm
USABLE_W = PAGE_W - 2 * MARGIN             # ~785.3 pt
USABLE_H = PAGE_H - 2 * MARGIN

GREY = HexColor("#D9D9D9")
HAIRLINE = 0.5

FONT_LABEL = "Helvetica-Bold"
FONT_VALUE = "Helvetica"
SIZE_LABEL = 8
SIZE_VALUE = 10
SIZE_LIFTNO = 11
SIZE_HEADER_LABEL = 9
SIZE_HEADER_VALUE = 11

LIFTS_PER_PAGE = 15

# Lift table column widths, sum == USABLE_W
COL_WIDTHS = [
    32,   # Lift
    42,   # Paxe
    56,   # Height (Fl)
    56,   # TO
    56,   # LDG
    52,   # TIME
    42,   # CYC
    50,   # Temp
    65,   # Fuel Used
    60,   # Refuel
    274,  # Remarks
]
assert abs(sum(COL_WIDTHS) - USABLE_W) < 1.0, (sum(COL_WIDTHS), USABLE_W)

COL_HEADERS = [
    ("Lift", ""),
    ("Paxe", ""),
    ("Height", "(Fl)"),
    ("TO", "hh:mm"),
    ("LDG", "hh:mm"),
    ("TIME", "min"),
    ("CYC", ""),
    ("Temp", "°C"),
    ("Fuel Used", "gal"),
    ("Refuel", "ltrs"),
    ("Remarks", ""),
]

HEADER_STRIP_H = 24
COL_HEADER_H = 28
ROW_H = 22
FOOTER_ROW_H = 25
FOOTER_BLOCK_H = 2 * FOOTER_ROW_H


@dataclass
class SheetMeta:
    callsign: str
    airport: str
    date: str
    pilot: str = ""
    operator: str = ""
    tz_label: str = ""


@dataclass
class LiftRow:
    """A single row on the lift table — every column is a string, ready to draw.

    The renderer is OGN-agnostic: it just paints whatever string is in each
    field. OGN-derived rows are produced by `lift_to_row`; web-app rows are
    built from JSON form data."""

    number: int
    paxe: str = ""
    fl: str = ""
    to: str = ""
    ldg: str = ""
    time_min: str = ""
    cyc: str = ""
    temp: str = ""
    fuel_used: str = ""
    refuel: str = ""
    remarks: str = ""


def lift_to_row(lift: Lift, *, number: int | None = None) -> LiftRow:
    """Convert an OGN-derived Lift into a renderable LiftRow.

    Pre-fills the OGN-derivable columns and auto-flags out-of-band durations
    in Remarks (the same plausibility hint the CLI used to do inline)."""
    dur = lift.duration_minutes
    return LiftRow(
        number=number if number is not None else lift.number,
        fl=str(lift.flight_level),
        to=lift.takeoff.strftime("%H:%M"),
        ldg=lift.landing.strftime("%H:%M"),
        time_min=str(dur),
        remarks="?" if dur < 3 or dur > 60 else "",
    )


def _chunks(seq: list, size: int) -> list[list]:
    out: list[list] = []
    bucket: list = []
    for item in seq:
        bucket.append(item)
        if len(bucket) == size:
            out.append(bucket)
            bucket = []
    if bucket:
        out.append(bucket)
    return out


# ---------------------------------------------------------------------------
# Low-level cell helpers
# ---------------------------------------------------------------------------


def _rect(c: canvas.Canvas, x: float, y: float, w: float, h: float, *, fill: bool = False) -> None:
    c.setStrokeColor(black)
    c.setLineWidth(HAIRLINE)
    c.rect(x, y, w, h, stroke=1, fill=1 if fill else 0)


def _fill_rect(c: canvas.Canvas, x: float, y: float, w: float, h: float, color) -> None:
    c.setFillColor(color)
    c.setStrokeColor(black)
    c.setLineWidth(HAIRLINE)
    c.rect(x, y, w, h, stroke=1, fill=1)
    c.setFillColor(black)


def _text_centered(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    text: str,
    *,
    font: str = FONT_LABEL,
    size: float = SIZE_LABEL,
    color=black,
) -> None:
    if not text:
        return
    c.setFont(font, size)
    c.setFillColor(color)
    tw = c.stringWidth(text, font, size)
    cx = x + (w - tw) / 2
    # vertical centering: baseline = bottom + (h - cap) / 2 where cap ≈ 0.7 * size
    cy = y + (h - size * 0.7) / 2
    c.drawString(cx, cy, text)
    c.setFillColor(black)


def _text_left(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    text: str,
    *,
    font: str = FONT_VALUE,
    size: float = SIZE_VALUE,
    pad: float = 3,
    color=black,
) -> None:
    if not text:
        return
    c.setFont(font, size)
    c.setFillColor(color)
    cy = y + (h - size * 0.7) / 2
    c.drawString(x + pad, cy, text)
    c.setFillColor(black)


def _two_line_label(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    line1: str,
    line2: str,
    *,
    font: str = FONT_LABEL,
    size: float = SIZE_LABEL,
) -> None:
    c.setFont(font, size)
    if line2:
        t1y = y + h - size - 3
        t2y = y + 4
        for text, ty in [(line1, t1y), (line2, t2y)]:
            tw = c.stringWidth(text, font, size)
            c.drawString(x + (w - tw) / 2, ty, text)
    else:
        tw = c.stringWidth(line1, font, size)
        c.drawString(x + (w - tw) / 2, y + (h - size * 0.7) / 2, line1)


def _label_value_cell(
    c: canvas.Canvas,
    x: float,
    y: float,
    label_w: float,
    value_w: float,
    h: float,
    label: str,
    value: str = "",
    *,
    value_align: str = "left",
) -> None:
    _fill_rect(c, x, y, label_w, h, GREY)
    _text_centered(c, x, y, label_w, h, label, font=FONT_LABEL, size=SIZE_LABEL)
    _rect(c, x + label_w, y, value_w, h)
    if value:
        if value_align == "center":
            _text_centered(c, x + label_w, y, value_w, h, value, font=FONT_VALUE, size=SIZE_VALUE)
        else:
            _text_left(c, x + label_w, y, value_w, h, value)


# ---------------------------------------------------------------------------
# Block renderers
# ---------------------------------------------------------------------------


def _draw_header_strip(c: canvas.Canvas, y_top: float, meta: SheetMeta) -> None:
    """Four label/value pairs across the page top."""
    h = HEADER_STRIP_H
    y = y_top - h
    x = MARGIN

    # widths chosen to total USABLE_W
    pairs = [
        (60, 140, "Callsign", meta.callsign),
        (55, 140, "Airport", meta.airport),
        (40, 155, "Date", meta.date + (f"  ({meta.tz_label})" if meta.tz_label else "")),
        (65, 130, "Operator", meta.operator),
    ]
    assert abs(sum(lw + vw for lw, vw, _, _ in pairs) - USABLE_W) < 1.0

    for label_w, value_w, label, value in pairs:
        _label_value_cell(
            c, x, y, label_w, value_w, h, label, value,
            value_align="left",
        )
        x += label_w + value_w


def _draw_column_headers(c: canvas.Canvas, y_top: float) -> None:
    h = COL_HEADER_H
    y = y_top - h
    x = MARGIN
    for (line1, line2), w in zip(COL_HEADERS, COL_WIDTHS):
        _fill_rect(c, x, y, w, h, GREY)
        _two_line_label(c, x, y, w, h, line1, line2)
        x += w


def _draw_lift_rows(
    c: canvas.Canvas, y_top: float, rows: list[LiftRow], number_offset: int = 0
) -> None:
    """Grid of LIFTS_PER_PAGE rows. Pre-prints lift numbers in column 1 and
    fills whatever string fields are present on each LiftRow."""

    h = ROW_H
    by_number = {r.number: r for r in rows}

    col_x = [MARGIN]
    for w in COL_WIDTHS:
        col_x.append(col_x[-1] + w)

    # column index → LiftRow attribute name; col 0 (Lift number) is always
    # the on-grid row index, drawn separately.
    col_field = [
        None, "paxe", "fl", "to", "ldg", "time_min",
        "cyc", "temp", "fuel_used", "refuel", "remarks",
    ]

    for i in range(LIFTS_PER_PAGE):
        y = y_top - (i + 1) * h
        x = MARGIN
        for w in COL_WIDTHS:
            _rect(c, x, y, w, h)
            x += w

        lift_no = number_offset + i + 1
        _text_centered(
            c, MARGIN, y, COL_WIDTHS[0], h, str(lift_no),
            font=FONT_VALUE, size=SIZE_LIFTNO,
        )

        row = by_number.get(lift_no)
        if row is None:
            continue

        for ci, field in enumerate(col_field):
            if field is None:
                continue
            text = (getattr(row, field) or "").strip()
            if not text:
                continue
            # Remarks left-aligned; everything else centered.
            if field == "remarks":
                _text_left(
                    c, col_x[ci], y, COL_WIDTHS[ci], h, text,
                    font=FONT_VALUE, size=SIZE_VALUE,
                )
            else:
                _text_centered(
                    c, col_x[ci], y, COL_WIDTHS[ci], h, text,
                    font=FONT_VALUE, size=SIZE_VALUE,
                )


def _draw_footer_block1(c: canvas.Canvas, y_top: float, meta: SheetMeta) -> None:
    """Pilot / Total Cycles / time-refuel-cycles mini / Fuel / Hobbs."""
    h_row = FOOTER_ROW_H
    block_h = FOOTER_BLOCK_H
    y_bottom = y_top - block_h
    y_mid = y_bottom + h_row

    x = MARGIN

    # Group 1: Pilot — label 50, value 150 (spans both rows)
    g1_label_w, g1_value_w = 50, 150
    _fill_rect(c, x, y_bottom, g1_label_w, block_h, GREY)
    _text_centered(c, x, y_bottom, g1_label_w, block_h, "Pilot", font=FONT_LABEL, size=SIZE_LABEL)
    _rect(c, x + g1_label_w, y_bottom, g1_value_w, block_h)
    if meta.pilot:
        _text_left(
            c, x + g1_label_w, y_bottom, g1_value_w, block_h, meta.pilot,
            font=FONT_VALUE, size=SIZE_VALUE,
        )
    x += g1_label_w + g1_value_w

    # Group 2: Total Cycles — label 75, value 55 (spans both rows)
    g2_label_w, g2_value_w = 75, 55
    _fill_rect(c, x, y_bottom, g2_label_w, block_h, GREY)
    _text_centered(
        c, x, y_bottom, g2_label_w, block_h, "Total Cycles",
        font=FONT_LABEL, size=SIZE_LABEL,
    )
    _rect(c, x + g2_label_w, y_bottom, g2_value_w, block_h)
    x += g2_label_w + g2_value_w

    # Group 3: mini (time/refuel + cycles) — 75 + 35 + 50 = 160 pt
    mini_label_w, mini_value_w = 35, 40
    # Row 1 — time label + value (top)
    _fill_rect(c, x, y_mid, mini_label_w, h_row, GREY)
    _text_centered(c, x, y_mid, mini_label_w, h_row, "time", font=FONT_LABEL, size=SIZE_LABEL)
    _rect(c, x + mini_label_w, y_mid, mini_value_w, h_row)
    # Row 2 — refuel label + value (bottom)
    _fill_rect(c, x, y_bottom, mini_label_w, h_row, GREY)
    _text_centered(c, x, y_bottom, mini_label_w, h_row, "refuel", font=FONT_LABEL, size=SIZE_LABEL)
    _rect(c, x + mini_label_w, y_bottom, mini_value_w, h_row)
    x += mini_label_w + mini_value_w
    # cycles label + value, spans both rows
    cyc_label_w, cyc_value_w = 35, 50
    _fill_rect(c, x, y_bottom, cyc_label_w, block_h, GREY)
    _text_centered(c, x, y_bottom, cyc_label_w, block_h, "cycles", font=FONT_LABEL, size=SIZE_LABEL)
    _rect(c, x + cyc_label_w, y_bottom, cyc_value_w, block_h)
    x += cyc_label_w + cyc_value_w

    # Group 4: Fuel Start / Fuel End — label 60, then L 35, R 35, TOTAL 50
    fuel_label_w = 60
    fuel_l_w, fuel_r_w, fuel_total_w = 35, 35, 50
    for row_y, row_label in [(y_mid, "Fuel Start"), (y_bottom, "Fuel End")]:
        cx = x
        _fill_rect(c, cx, row_y, fuel_label_w, h_row, GREY)
        _text_centered(c, cx, row_y, fuel_label_w, h_row, row_label,
                       font=FONT_LABEL, size=SIZE_LABEL)
        cx += fuel_label_w
        for sub_label, sub_w in [("left", fuel_l_w), ("right", fuel_r_w), ("TOTAL", fuel_total_w)]:
            # mini sub-header in the cell top-left: render as grey label strip + white below?
            # simpler: just one cell with the sub-label faint on top
            _rect(c, cx, row_y, sub_w, h_row)
            # tiny label in top-left corner
            c.setFont(FONT_LABEL, 6)
            c.setFillColor(black)
            c.drawString(cx + 2, row_y + h_row - 8, sub_label)
            cx += sub_w
    x += fuel_label_w + fuel_l_w + fuel_r_w + fuel_total_w

    # Group 5: Hobbs Start / Hobbs End — label 60, value 55 (per row)
    hobbs_label_w, hobbs_value_w = 60, 55
    for row_y, row_label in [(y_mid, "Hobbs Start"), (y_bottom, "Hobbs End")]:
        cx = x
        _fill_rect(c, cx, row_y, hobbs_label_w, h_row, GREY)
        _text_centered(c, cx, row_y, hobbs_label_w, h_row, row_label,
                       font=FONT_LABEL, size=SIZE_LABEL)
        cx += hobbs_label_w
        _rect(c, cx, row_y, hobbs_value_w, h_row)
    x += hobbs_label_w + hobbs_value_w

    assert abs(x - (MARGIN + USABLE_W)) < 1.0, (x, MARGIN + USABLE_W)


def _draw_footer_block2(c: canvas.Canvas, y_top: float) -> None:
    """Engine Reading at FL 90 — block label + 2 rows of label/value pairs.
    Row 1 has 5 pairs, row 2 has 4 pairs."""

    h_row = FOOTER_ROW_H
    block_h = FOOTER_BLOCK_H
    y_bottom = y_top - block_h
    y_mid = y_bottom + h_row

    x = MARGIN

    # Block label (spans both rows), wrapped over 2 lines
    block_label_w = 120
    _fill_rect(c, x, y_bottom, block_label_w, block_h, GREY)
    c.setFont(FONT_LABEL, SIZE_LABEL)
    c.setFillColor(black)
    for line, ty in [
        ("Engine Reading", y_bottom + block_h - SIZE_LABEL - 6),
        ("at FL 90", y_bottom + 6),
    ]:
        tw = c.stringWidth(line, FONT_LABEL, SIZE_LABEL)
        c.drawString(x + (block_label_w - tw) / 2, ty, line)
    x += block_label_w

    right_w = USABLE_W - block_label_w

    # Row 1: 5 evenly-spaced label/value pairs
    row1_labels = ["OAT", "IAS", "NG", "ITT", "Hobbs Total"]
    pair_w = right_w / len(row1_labels)
    label_w = pair_w * 0.42
    value_w = pair_w - label_w
    cx = x
    for lbl in row1_labels:
        _fill_rect(c, cx, y_mid, label_w, h_row, GREY)
        _text_centered(c, cx, y_mid, label_w, h_row, lbl, font=FONT_LABEL, size=SIZE_LABEL)
        _rect(c, cx + label_w, y_mid, value_w, h_row)
        cx += pair_w

    # Row 2: 4 evenly-spaced label/value pairs
    row2_labels = ["QNH", "RPM/Prop", "Tourque", "Fuel Flow"]
    pair_w2 = right_w / len(row2_labels)
    label_w2 = pair_w2 * 0.42
    value_w2 = pair_w2 - label_w2
    cx = x
    for lbl in row2_labels:
        _fill_rect(c, cx, y_bottom, label_w2, h_row, GREY)
        _text_centered(c, cx, y_bottom, label_w2, h_row, lbl, font=FONT_LABEL, size=SIZE_LABEL)
        _rect(c, cx + label_w2, y_bottom, value_w2, h_row)
        cx += pair_w2


# ---------------------------------------------------------------------------
# Page composition
# ---------------------------------------------------------------------------


def _render_page(
    c: canvas.Canvas, meta: SheetMeta, rows: list[LiftRow], number_offset: int
) -> None:
    # vertical layout — start from the top, walk down
    gap = 6

    y_header_top = PAGE_H - MARGIN
    y_after_header = y_header_top - HEADER_STRIP_H - gap

    y_col_header_top = y_after_header
    y_after_col_header = y_col_header_top - COL_HEADER_H

    y_after_rows = y_after_col_header - LIFTS_PER_PAGE * ROW_H

    # footer blocks stacked at the bottom
    y_footer2_top = MARGIN + FOOTER_BLOCK_H
    y_footer1_top = y_footer2_top + gap + FOOTER_BLOCK_H

    # sanity: rows shouldn't collide with footer
    assert y_after_rows >= y_footer1_top, (
        f"Layout overflow: lift rows end at {y_after_rows:.1f} pt but "
        f"footer block 1 starts at {y_footer1_top:.1f} pt — shrink ROW_H "
        f"or footer heights."
    )

    _draw_header_strip(c, y_header_top, meta)
    _draw_column_headers(c, y_col_header_top)
    _draw_lift_rows(c, y_after_col_header, rows, number_offset=number_offset)
    _draw_footer_block1(c, y_footer1_top, meta)
    _draw_footer_block2(c, y_footer2_top)


def render_sheet(
    out_path_or_stream,
    meta: SheetMeta,
    rows: list[LiftRow],
) -> None:
    """Render the log sheet to a file path or any binary-writable stream."""
    c = canvas.Canvas(out_path_or_stream, pagesize=landscape(A4))
    c.setTitle(f"Jump Log {meta.callsign} {meta.date}")
    c.setAuthor(meta.pilot or "jumplog")

    pages = _chunks(rows, LIFTS_PER_PAGE) or [[]]
    for page_idx, page_rows in enumerate(pages):
        offset = page_idx * LIFTS_PER_PAGE
        _render_page(c, meta, page_rows, number_offset=offset)
        c.showPage()
    c.save()
