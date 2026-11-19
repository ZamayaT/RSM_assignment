"""PDF renderer: a pure function from a snapshot to bytes (ReportLab, built-in Helvetica).

Characters Helvetica cannot show are replaced by "?". Page compression and ASCII85 are off so tests can read the
text straight from the file (documents are small).
"""
import io
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

rl_config.useA85 = 0

ITEM_STATUS = {
    "estimate": "Estimate",
    "expired_quote": "Quote expired",
    "booking_pending": "Booking in progress",
    "confirmed": "Confirmed",
    "failed": "Booking failed",
    "unknown": "Booking outcome unknown",
}
BOOKING_STATUS = {
    "initiated": "In progress (not yet answered)",
    "pending": "Pending (not confirmed yet)",
    "unknown": "Unknown (the outcome is not confirmed)",
    "confirmed": "Confirmed",
    "failed": "Failed",
}
CATEGORY = {"transport": "Transport", "accommodation": "Accommodation", "activity": "Activity"}


def clean(value) -> str:
    """Text safe for the PDF: only characters Helvetica (WinAnsi) can show; others become "?"."""
    return str(value).encode("cp1252", errors="replace").decode("cp1252")


def _p(value, style) -> Paragraph:
    return Paragraph(escape(clean(value)).replace("\n", "<br/>"), style)


def _utc(value: str | None) -> str:
    if not value:
        return "-"
    return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")


def _money(amount: str | None, currency: str = "USD") -> str:
    return "-" if amount is None else f"{amount} {currency}"


def render_pdf(snapshot: dict, document_id: str) -> bytes:
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["Normal"], fontName="Helvetica", fontSize=9, leading=11)
    cell = ParagraphStyle("cell", parent=body, fontSize=8, leading=10)
    head = ParagraphStyle("head", parent=cell, fontName="Helvetica-Bold", textColor=colors.white)
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=18, spaceAfter=4)
    h2 = ParagraphStyle(
        "h2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12, spaceBefore=12, spaceAfter=4
    )
    note = ParagraphStyle("note", parent=body, textColor=colors.HexColor("#444444"))

    def table(header: list[str], rows: list[list[str]], widths: list[float]) -> Table:
        data = [[_p(h, head) for h in header]] + [[_p(c, cell) for c in row] for row in rows]
        t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
                ]
            )
        )
        return t

    trip, budget = snapshot["trip"], snapshot["budget"]
    currency = budget.get("currency", "USD")
    story = [
        _p(
            f"Generated at {_utc(snapshot['generatedAt'])} UTC by {snapshot['generatedBy']['displayName']} "
            f"from trip version {snapshot['tripVersion']}",
            body,
        ),
        Spacer(1, 6),
        _p(trip["name"], h1),
        _p(f"Dates: {trip['startDate']} to {trip['endDate']}", body),
        _p(f"Destinations: {', '.join(trip['destinations'])}", body),
        _p(f"Travelers: {trip['travelers']}", body),
        _p(f"Budget: {_money(trip['budget'], currency)}", body),
    ]
    if trip.get("notes"):
        story.append(_p(f"Notes: {trip['notes']}", body))

    story.append(_p("Itinerary", h2))
    if snapshot["itinerary"]:
        rows = []
        for n, i in enumerate(snapshot["itinerary"], start=1):
            when = "-"
            if i["startsAt"]:
                when = _utc(i["startsAt"]) + (f" to {_utc(i['endsAt'])}" if i["endsAt"] else "")
            price = i["acceptedPrice"] or i["price"]
            rows.append(
                [
                    str(n),
                    i["title"],
                    CATEGORY.get(i["category"], i["category"]),
                    i["destination"],
                    when,
                    _money(price["amount"], price["currency"]) if price else "-",
                    ITEM_STATUS.get(i["status"], i["status"]),
                    "; ".join(w["message"] for w in i["warnings"]) or "-",
                ]
            )
        story.append(
            table(
                ["#", "Title", "Category", "Destination", "Schedule (UTC)", "Cost", "Status", "Warnings"],
                rows,
                [8, 52, 24, 28, 40, 24, 30, 51],
            )
        )
    else:
        story.append(_p("The itinerary is empty.", body))

    story.append(_p("Costs", h2))
    over = budget["overBudget"]
    totals = [
        ["Estimated (not booked)", _money(budget["estimatedTotal"], currency)],
        ["Confirmed (accepted prices)", _money(budget["confirmedTotal"], currency)],
        ["Combined total", _money(budget["combinedTotal"], currency)],
        ["Budget", _money(budget["budget"], currency)],
        ["Over budget by" if over else "Remaining", _money(budget["remaining"].lstrip("-"), currency)],
    ]
    story.append(table(["Total", "Amount"], totals, [70, 40]))
    story.append(Spacer(1, 6))
    if budget["lines"]:
        lines = [
            [
                line["title"],
                CATEGORY.get(line["category"], line["category"]),
                "Confirmed" if line["kind"] == "confirmed" else "Estimate" + (" (quote expired)" if line["expired"] else ""),
                _money(line["amount"], currency) if line["amount"] is not None else "No price (not counted)",
            ]
            for line in budget["lines"]
        ]
        story.append(table(["Item", "Category", "Kind", "Amount"], lines, [90, 35, 50, 45]))

    story.append(_p("Bookings", h2))
    if snapshot["bookings"]:
        rows = []
        for b in snapshot["bookings"]:
            accepted = b["acceptedPrice"]
            if b["failure"]:
                detail = b["failure"]["message"]
            elif b["unresolved"]:
                detail = "Still unknown after a long wait"
            else:
                detail = "-"
            rows.append(
                [
                    b["itemTitle"],
                    BOOKING_STATUS.get(b["status"], b["status"]),
                    _money(accepted["amount"], accepted["currency"]) if accepted else "-",
                    detail,
                ]
            )
        story.append(table(["Item", "Status", "Accepted price", "Details"], rows, [70, 55, 30, 65]))
    else:
        story.append(_p("No bookings were requested.", body))

    story.append(Spacer(1, 10))
    story.append(
        _p(
            "Prices are estimates unless marked confirmed. This document is a snapshot taken at the time shown above; "
            "later changes to the trip or its bookings are not reflected.",
            note,
        )
    )

    def footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawString(15 * mm, 8 * mm, clean(f"Document {document_id}"))
        canvas.drawRightString(landscape(A4)[0] - 15 * mm, 8 * mm, f"Page {doc.page}")
        canvas.restoreState()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=16 * mm,
        pageCompression=0,
        title=clean(f"{trip['name']} - trip summary"),
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
