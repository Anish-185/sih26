"""Evidence-backed inspection report (PDF).

The report is an AUDIT TRAIL, not a decision layer. ``render_report`` formats a
persisted inspection — the saved record (``InspectionRecordOut`` as JSON) and its
stored photos — into a PDF. It never recomputes a result, never calls a model,
and never writes anything: every value comes from the stored record, and a value
that is not there is reported as not established.

Sections: header · inspection summary · package photos · OCR evidence ·
declarations · BIS standard evidence · certification guidance · relevant testing laboratories ·
Legal Metrology evidence ·
compliance results · automated system result · officer review · final outcome · evidence
and sources. The system result and the officer's decision are always shown
separately.

All stored text (OCR, product names, notes) is escaped before it reaches the
layout, so package text can never inject markup into the PDF.
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from xml.sax.saxutils import escape

from PIL import Image as PILImage, ImageDraw
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    CondPageBreak,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ------------------------------------------------------------------ identity

INK = colors.HexColor("#17181b")
INK_SOFT = colors.HexColor("#585c63")
INK_FAINT = colors.HexColor("#8b8e94")
LINE = colors.HexColor("#e8e3d5")
LINE_STRONG = colors.HexColor("#d0cbba")
SURFACE = colors.HexColor("#fdfaf1")
ACCENT = colors.HexColor("#2246ef")
RESULT_COLORS = {
    "PASS": (colors.HexColor("#1c7a4b"), colors.HexColor("#e8f1ec")),
    "FAIL": (colors.HexColor("#b0271d"), colors.HexColor("#f6e8e6")),
    "REVIEW": (colors.HexColor("#8a6200"), colors.HexColor("#f3ecd9")),
}
NEUTRAL = (INK_SOFT, colors.HexColor("#f1eee6"))

_FONTS = Path(__file__).resolve().parent / "report_fonts"
_REGISTERED = False


def _register_fonts() -> None:
    """Noto Sans (SIL OFL 1.1, bundled) — it covers the rupee sign and Indian text on labels."""
    global _REGISTERED
    if _REGISTERED:
        return
    for name, file in (("Sans", "NotoSans-Regular.ttf"), ("Sans-Medium", "NotoSans-Medium.ttf"),
                       ("Sans-Bold", "NotoSans-Bold.ttf"), ("Mono", "NotoSansMono-Regular.ttf")):
        pdfmetrics.registerFont(TTFont(name, str(_FONTS / file)))
    pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans", boldItalic="Sans-Bold")
    _REGISTERED = True


IST = ZoneInfo("Asia/Kolkata")  # every timestamp in the report is shown in Indian Standard Time

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

OFFICER_STATUS = {
    "NOT_REQUIRED": "Not required — resolved by the system",
    "PENDING": "Pending officer review",
    "IN_REVIEW": "In review",
    "COMPLETED": "Completed",
}
DECISIONS = {
    "ACCEPT_SYSTEM_RESULT": "Accept system result",
    "OVERRIDE": "Override",
    "MANUAL_REVIEW": "Manual review",
}
CHECK_RESULT = {"NOT_SUPPORTED": "UNSUPPORTED", "NOT_APPLICABLE": "NOT APPLICABLE"}
AUTHORITY = {"BIS": "BIS", "LEGAL_METROLOGY": "Legal Metrology", "HALLMARKING": "Hallmarking"}
REASON_SOURCE = {**AUTHORITY, "OCR": "OCR evidence", "PRODUCT": "Product", "PIPELINE": "Pipeline"}


# ------------------------------------------------------------------ text helpers


def _styles() -> dict[str, ParagraphStyle]:
    base = dict(fontName="Sans", textColor=INK, fontSize=8.6, leading=11.6)
    return {
        "brand": ParagraphStyle("brand", fontName="Sans-Bold", fontSize=15, leading=18, textColor=INK),
        "title": ParagraphStyle("title", fontName="Sans-Medium", fontSize=19, leading=23, textColor=INK),
        "eyebrow": ParagraphStyle("eyebrow", fontName="Mono", fontSize=7, leading=9, textColor=ACCENT),
        "h2": ParagraphStyle("h2", fontName="Sans-Medium", fontSize=12.5, leading=16, textColor=INK),
        "h3": ParagraphStyle("h3", fontName="Sans-Medium", fontSize=9.6, leading=13, textColor=INK,
                             spaceBefore=3 * mm, spaceAfter=1.5 * mm),
        "lead": ParagraphStyle("lead", fontName="Sans", fontSize=8.6, leading=11.6, textColor=INK_SOFT,
                               spaceAfter=2.5 * mm),
        "body": ParagraphStyle("body", **base),
        "soft": ParagraphStyle("soft", **{**base, "textColor": INK_SOFT}),
        "small": ParagraphStyle("small", **{**base, "fontSize": 7.4, "leading": 9.8, "textColor": INK_SOFT}),
        "faint": ParagraphStyle("faint", **{**base, "fontSize": 7.2, "leading": 9.4, "textColor": INK_FAINT}),
        "kicker": ParagraphStyle("kicker", fontName="Mono", fontSize=6.6, leading=9, textColor=INK_FAINT),
        "mono": ParagraphStyle("mono", fontName="Mono", fontSize=7.2, leading=9.6, textColor=INK),
        "cell": ParagraphStyle("cell", **{**base, "fontSize": 7.6, "leading": 10}),
        "cellsoft": ParagraphStyle("cellsoft", **{**base, "fontSize": 7.2, "leading": 9.4, "textColor": INK_SOFT}),
        "right": ParagraphStyle("right", fontName="Mono", fontSize=6.8, leading=9, textColor=INK_FAINT,
                                alignment=TA_RIGHT),
    }


def _t(value) -> str:
    """Escape stored text for a Paragraph. Stored OCR / product text is data, never markup."""
    return escape("" if value is None else str(value)).replace("\n", "<br/>")


def _fmt_time(value) -> str:
    if not value:
        return "—"
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if dt.tzinfo is None:
        return dt.strftime("%d %b %Y, %H:%M")
    return dt.astimezone(IST).strftime("%d %b %Y, %H:%M IST")


def _pct(value) -> str:
    return "—" if value is None else f"{round(float(value) * 100)}%"


# ------------------------------------------------------------------ components


class _Doc:
    """Holds the styles and builds reusable report components."""

    def __init__(self):
        self.s = _styles()
        self.number = 1  # the header is section 01

    def p(self, text: str, style: str = "body") -> Paragraph:
        return Paragraph(text, self.s[style])

    def h3(self, text: str) -> list:
        """A sub-heading that never ends a page on its own (needs room for the start of its content)."""
        return [CondPageBreak(35 * mm), self.p(text, "h3")]

    def section(self, number: int, title: str, lead: str | None = None, room: float = 45 * mm) -> list:
        """``number`` is ignored: sections are numbered in the order they are added."""
        self.number += 1
        head = Table([[self.p(f"{self.number:02d}", "eyebrow"), self.p(_t(title), "h2")]],
                     colWidths=[12 * mm, CONTENT_W - 12 * mm])
        head.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LINEBELOW", (0, 0), (-1, -1), 0.8, INK),
        ]))
        head.spaceBefore, head.spaceAfter = 7 * mm, 3 * mm
        out = [CondPageBreak(room), head]
        if lead:
            out.append(self.p(lead, "lead"))
        return out

    def badge(self, result: str | None, label: str | None = None) -> Table:
        text = label or (result or "—")
        fg, bg = RESULT_COLORS.get(result or "", NEUTRAL)
        cell = Paragraph(f"<font name='Mono'>{_t(text)}</font>",
                         ParagraphStyle("badge", fontName="Mono", fontSize=7.4, leading=9, textColor=fg))
        width = max(16 * mm, pdfmetrics.stringWidth(text, "Mono", 7.4) + 5 * mm)
        t = Table([[cell]], colWidths=[width])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg), ("BOX", (0, 0), (-1, -1), 0.6, fg),
            ("LEFTPADDING", (0, 0), (-1, -1), 2.5 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 1 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 1.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
        ]))
        t.hAlign = "LEFT"
        return t

    def definitions(self, rows: list[tuple[str, object]], label_w: float = 42 * mm) -> Table:
        data = [[self.p(_t(label.upper()), "kicker"), value if not isinstance(value, str) else self.p(value)]
                for label, value in rows]
        t = Table(data, colWidths=[label_w, CONTENT_W - label_w])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 3.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
        ]))
        return t

    def table(self, header: list[str], rows: list[list], widths: list[float], result_col: int | None = None) -> Table:
        """Evidence table: thin rules, mono header, wrapped cells."""
        data = [[self.p(_t(h.upper()), "kicker") for h in header]]
        for row in rows:
            data.append([c if not isinstance(c, str) else self.p(c, "cell") for c in row])
        t = Table(data, colWidths=widths, repeatRows=1)
        style = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm), ("TOPPADDING", (0, 0), (-1, -1), 2.6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2), ("BACKGROUND", (0, 0), (-1, 0), SURFACE),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE_STRONG), ("LINEBELOW", (0, 1), (-1, -1), 0.35, LINE),
            ("BOX", (0, 0), (-1, -1), 0.5, LINE_STRONG),
        ]
        t.setStyle(TableStyle(style))
        return t

    def callout(self, text: str, tone: str | None = None) -> Table:
        fg, bg = RESULT_COLORS.get(tone or "", (LINE_STRONG, SURFACE))
        t = Table([[self.p(text, "soft")]], colWidths=[CONTENT_W])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg), ("LINEBEFORE", (0, 0), (0, -1), 2, fg),
            ("LEFTPADDING", (0, 0), (-1, -1), 3.5 * mm), ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ]))
        return t

    def source_block(self, source: dict) -> list:
        parts = [f"<font name='Sans-Medium'>{_t(source.get('title'))}</font>"]
        meta = [x for x in (source.get("document_name"), source.get("reference"),
                            f"verified {source['last_verified']}" if source.get("last_verified") else None) if x]
        out = [self.p(" ".join(parts), "cell")]
        if meta:
            out.append(self.p(_t(" · ".join(meta)), "cellsoft"))
        if source.get("source_url"):
            out.append(self.p(_t(source["source_url"]), "mono"))
        return out


# ------------------------------------------------------------------ page chrome


def _numbered_canvas(inspection_id: str, generated: str):
    class NumberedCanvas(pdfcanvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages = []

        def showPage(self):  # noqa: N802 — ReportLab API
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self._chrome(total)
                super().showPage()
            super().save()

        def _chrome(self, total: int) -> None:
            self.setStrokeColor(LINE_STRONG)
            self.setLineWidth(0.5)
            self.line(MARGIN, 13 * mm, PAGE_W - MARGIN, 13 * mm)
            self.setFont("Mono", 6.6)
            self.setFillColor(INK_FAINT)
            self.drawString(MARGIN, 9 * mm, f"METRIQ · {inspection_id} · generated {generated}")
            self.drawRightString(PAGE_W - MARGIN, 9 * mm, f"PAGE {self._pageNumber} / {total}")
            self.setFillColor(ACCENT)
            self.rect(MARGIN, PAGE_H - 10 * mm, 14 * mm, 1.2, stroke=0, fill=1)

    return NumberedCanvas


# ------------------------------------------------------------------ images


def _annotated_image(data: bytes, regions: list[dict], max_w: float, max_h: float) -> Image | None:
    """The stored photo with its OCR boxes drawn on an in-memory copy. None if it cannot be decoded."""
    try:
        img = PILImage.open(io.BytesIO(data))
        img.load()
    except Exception:  # noqa: BLE001 — an unreadable stored photo is reported, not raised
        return None
    img = img.convert("RGB")
    draw = ImageDraw.Draw(img)
    stroke = max(2, round(max(img.size) / 500))
    for r in regions:
        x1, y1, x2, y2 = r["bbox"]
        draw.rectangle([x1, y1, x2, y2], outline=(34, 70, 239), width=stroke)
    img.thumbnail((1200, 1200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82)
    buf.seek(0)
    scale = min(max_w / img.width, max_h / img.height)
    return Image(buf, width=img.width * scale, height=img.height * scale)


# ------------------------------------------------------------------ sections


def _summary(d: _Doc, rec: dict, an: dict) -> list:
    fields = {f["field"]: f for f in an["declaration_stage"]["fields"]}

    def declared(name: str) -> str:
        f = fields.get(name)
        if not f or f["status"] == "NOT_DETECTED":
            return "<font color='#8b8e94'>Not detected in the OCR evidence</font>"
        suffix = "" if f["status"] == "DETECTED" else f" <font color='#8a6200'>({_t(f['status'])})</font>"
        return f"{_t(f['value']) or '<i>value withheld</i>'}{suffix}"

    parties = [f"{_t(fields[n]['label'])}: {declared(n)}" for n in ("manufacturer", "packer", "importer")
               if n in fields and fields[n]["status"] != "NOT_DETECTED"]
    product = (_t(rec["product_name"]) if rec["product_status"] == "MATCHED"
               else "<font color='#8a6200'>Not identified</font> — product identification needs review: "
                    + _t(an["product"]["reason"]))
    out = d.section(2, "Inspection summary")
    out.append(d.definitions([
        ("Product", product),
        ("Brand", declared("brand")),
        ("Manufacturer / packer / importer",
         "<br/>".join(parties) if parties else "<font color='#8b8e94'>None detected in the OCR evidence</font>"),
        ("Category", _t(rec["product_category"]) if rec.get("product_category")
         else "<font color='#8b8e94'>Not established</font>"),
        ("BIS standard", _t(rec["standard_number"]) if rec.get("standard_number")
         else "<font color='#8b8e94'>No verified standard identified</font>"),
        ("Package sides inspected", _t(", ".join(rec["sides"])) + f" ({rec['image_count']} "
         f"{'photo' if rec['image_count'] == 1 else 'photos'})"),
        ("Officer review status", _t(OFFICER_STATUS[rec["officer_status"]])),
    ]))
    out += [Spacer(1, 4 * mm), _outcome_boxes(d, rec)]
    return out


def _outcome_boxes(d: _Doc, rec: dict) -> Table:
    """System result and officer decision side by side — never merged."""
    status = rec["officer_status"]
    if status == "NOT_REQUIRED":
        officer = [d.p("Not required", "h3"),
                   d.p("The system resolved this inspection; it was not escalated to an officer.", "small")]
    elif status == "COMPLETED":
        officer = [d.p(_t(DECISIONS[rec["officer_decision"]]), "h3")]
        if rec["officer_decision"] == "OVERRIDE":
            officer += [d.p("Officer result", "kicker"), d.badge(rec["officer_result"])]
        elif rec["officer_decision"] == "MANUAL_REVIEW":
            officer.append(d.p("Manual / physical verification required.", "small"))
        else:
            officer.append(d.p(f"The officer accepted the system result ({_t(rec['system_result'])}).", "small"))
    else:
        officer = [d.p("None yet", "h3"),
                   d.p(f"Officer review is {_t(OFFICER_STATUS[status].lower())}; no officer has decided this "
                       "inspection.", "small")]
    left = [d.p("AUTOMATED SYSTEM RESULT", "kicker"), Spacer(1, 1.5 * mm), d.badge(rec["system_result"]),
            Spacer(1, 1.5 * mm), d.p("Deterministic rules over stored evidence. Fixed when saved.", "small")]
    right = [d.p("OFFICER FINAL DECISION", "kicker"), Spacer(1, 1.5 * mm), *officer]
    half = (CONTENT_W - 4 * mm) / 2
    t = Table([[left, "", right]], colWidths=[half, 4 * mm, half])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (0, 0), 0.6, LINE_STRONG),
        ("BOX", (2, 0), (2, 0), 0.6, LINE_STRONG), ("BACKGROUND", (0, 0), (0, 0), SURFACE),
        ("BACKGROUND", (2, 0), (2, 0), SURFACE), ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
        ("LEFTPADDING", (1, 0), (1, 0), 0),
    ]))
    return t


def _photos(d: _Doc, rec: dict, an: dict, images: dict[int, bytes]) -> list:
    out = d.section(3, "Package photos", "The photos stored with this inspection, in upload order. Blue boxes are "
                    "the OCR engine's text regions. Only sides that were photographed are shown.", room=125 * mm)
    regions_by_image: dict[str, list] = {}
    for r in an["ocr"]["regions"]:
        regions_by_image.setdefault(r["image_id"], []).append(r)
    cells = []
    col_w = (CONTENT_W - 6 * mm) / 2
    for stored in rec["images"]:
        meta = next((i for i in an["images"] if i["index"] == stored["index"]), {})
        data = images.get(stored["index"])
        pic = _annotated_image(data, regions_by_image.get(stored["image_id"], []), col_w, 88 * mm) if data else None
        caption = [d.p(f"{_t(stored['side'])} · image {stored['index']}", "kicker"),
                   d.p(f"{_t(stored['filename'])} · {_t(stored['image_id'])}", "faint")]
        if meta:
            caption.append(d.p(f"OCR {_t(meta.get('status'))} · "
                               f"{(meta.get('ocr') or {}).get('region_count', 0)} regions"
                               + (f" · mean confidence {_pct(meta['ocr']['mean_confidence'])}" if meta.get("ocr") else ""),
                               "faint"))
        body = [pic] if pic else [d.p("<i>The stored photo could not be decoded.</i>", "small")]
        cells.append(body + [Spacer(1, 1.5 * mm)] + caption)
    if not cells:
        return out + [d.p("No photos are stored with this inspection.", "soft")]
    rows = [cells[i:i + 2] + [""] * (2 - len(cells[i:i + 2])) for i in range(0, len(cells), 2)]
    t = Table([[r[0], "", r[1]] for r in rows], colWidths=[col_w, 6 * mm, col_w])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 5 * mm)]))
    return out + [t]


def _where(region_ids: list[str], sides: dict[str, str]) -> str:
    if not region_ids:
        return "—"
    by_side: dict[str, list[str]] = {}
    for rid in region_ids:
        by_side.setdefault(sides.get(rid, "UNKNOWN"), []).append(rid)
    return "; ".join(f"{s} image: {', '.join(ids)}" for s, ids in by_side.items())


def _ocr(d: _Doc, an: dict) -> list:
    ocr = an["ocr"]
    sides = {r["id"]: r.get("side", "UNKNOWN") for r in ocr["regions"]}
    out = d.section(4, "OCR evidence", f"Engine: {_t(ocr['engine'])}. {ocr['region_count']} text regions, mean "
                    f"confidence {_pct(ocr['mean_confidence'])}. Confidence is how sure the OCR engine was of the "
                    "text — not whether a declaration is correct or compliant.")
    rows = []
    for f in an["declaration_stage"]["fields"]:
        if f["status"] == "NOT_DETECTED":
            continue
        rows.append([_t(f["label"]), _t(f["value"]) or "<i>withheld</i>", _pct(f.get("ocr_confidence")),
                     _t(_where(f["source_regions"], sides)) + (f"<br/><font color='#8b8e94'>“{_t(f['raw_text'])}”</font>"
                                                              if f.get("raw_text") else "")])
    if rows:
        out += [*d.h3("Declared fields read from the package"),
                d.table(["Field", "Value", "Confidence", "Source (side, OCR region, raw text)"], rows,
                        [34 * mm, 42 * mm, 18 * mm, CONTENT_W - 94 * mm])]
    limit = 60
    regions = ocr["regions"]
    region_rows = [[_t(r["id"]), _t(r.get("side", "UNKNOWN")), _t(r["text"]), _pct(r["confidence"]),
                    f"<font name='Mono'>{_t(r['bbox'])}</font>"] for r in regions[:limit]]
    out += d.h3("Text regions")
    if region_rows:
        out.append(d.table(["Region", "Side", "Text (verbatim)", "Conf.", "Box [x1, y1, x2, y2]"], region_rows,
                           [22 * mm, 21 * mm, CONTENT_W - 109 * mm, 14 * mm, 52 * mm]))
        if len(regions) > limit:
            out.append(d.p(f"{len(regions) - limit} further regions are kept in the stored inspection record.", "faint"))
    else:
        out.append(d.p("No text regions were read from the photos.", "soft"))
    return out


def _declarations(d: _Doc, an: dict) -> list:
    out = d.section(5, "Declarations", "Every declaration field MetrIQ searches for, with its status exactly as "
                    "stored. NOT_DETECTED only means the field was not found in the OCR text of these photos — "
                    "it is not a finding that the declaration is legally missing.")
    tone = {"DETECTED": "#1c7a4b", "UNCERTAIN": "#8a6200"}
    rows = []
    for f in an["declaration_stage"]["fields"]:
        status = f"<font name='Mono' color='{tone.get(f['status'], '#8b8e94')}'>{_t(f['status'])}</font>"
        if f.get("consistency") == "CONFLICT":
            status += "<br/><font name='Mono' color='#b0271d'>CONFLICT</font>"
        note = f.get("reason") or f.get("note") or ""
        if f.get("extraction_method") == "deterministic_normalization":
            note = f"Normalized from OCR. {note}"
        rows.append([_t(f["label"]), status, _t(f["value"]) if f.get("value") else "—", _t(note)])
    out.append(d.table(["Field", "Status", "Value", "Note"], rows,
                       [40 * mm, 24 * mm, 44 * mm, CONTENT_W - 108 * mm]))
    return out


def _bis(d: _Doc, rec: dict, an: dict) -> list:
    product, standards, comp = an["product"], an["standards"], an["compliance"]
    out = d.section(6, "BIS standard evidence", "Standards come only from MetrIQ's verified BIS knowledge base, ranked "
                    "by deterministic retrieval. A standard match is retrieval evidence — not a certification or "
                    "conformity decision.")
    out.append(d.definitions([
        ("Product identification", f"{_t(product['status'])} · {_t(product['reason'])}"),
        ("Method", _t(product["method"])),
    ]))
    if product["status"] != "MATCHED" or not rec.get("standard_number"):
        out += [Spacer(1, 3 * mm), d.callout("No verified BIS standard was identified by the automated retrieval "
                                             "process.", "REVIEW")]
    for i, c in enumerate(standards):
        best = product["status"] == "MATCHED" and c["standard_number"] == product.get("standard_number")
        label = "Identified standard" if best else f"Candidate {i + 1} (not confirmed)"
        why = c.get("why") or {}
        block = [d.p(f"{_t(label)} · <font name='Mono'>{_t(c['standard_number'])}</font>", "h3"),  # kept with its block
                 d.definitions([
                     ("Title", _t(c["title"])),
                     ("Product / category", _t(c["product"])),
                     ("Retrieval strength", f"{_t(c['confidence'])} (score {c['score']:.1f}, match tier {_t(c['tier'])})"
                                            + (" · IS number printed on the label" if c["printed_on_label"] else "")),
                     ("Why this result", _t(why.get("summary") or "—")),
                     ("Evidence from the package", "<br/>".join(
                         f"{_t(e['clue']['kind'].replace('_', ' '))}: “{_t(e['clue']['text'])}” "
                         f"<font name='Mono' color='#8b8e94'>{_t(', '.join(e['clue']['source_regions']))} · "
                         f"matches “{_t(e['matched_phrase'])}”</font>" for e in c.get("evidence", []))
                         or "—"),
                     ("Source", d.source_block(c) if c.get("source_url") or c.get("document_name") else "—"),
                 ])]
        out.append(KeepTogether(block))
    cov = comp.get("coverage") or {}
    out += [Spacer(1, 4 * mm), d.definitions([
        ("BIS inspection coverage", _t(comp.get("coverage_status"))),
        ("Coverage explanation", _t(cov.get("explanation") or comp.get("reason"))),
    ])]
    return out


def _certification(d: _Doc, an: dict) -> list:
    """Milestone 16: the certification guidance stored with this inspection.

    Guidance about the ROUTE for a product type — never a statement that this
    item or its manufacturer is certified. Every sentence shown is a quote from
    a verified record stored in the record, with its official BIS source.
    """
    j = an.get("certification")
    if not j:
        return []
    out = d.section(0, "Certification guidance", "What published BIS information says about the certification "
                    "route for this product type. This is guidance, not the certification status of the "
                    "physical product: MetrIQ does not verify and does not state that this item, its "
                    "manufacturer or any licence is certified or registered.")
    scheme = j.get("scheme") or {}
    out.append(d.definitions([
        ("Product", _t(j.get("product") or (an.get("product") or {}).get("product") or "Not identified")),
        ("Standard", f"<font name='Mono'>{_t(j.get('standard_number') or '—')}</font>"
                     + (f" · {_t(j.get('standard_title'))}" if j.get("standard_title") else "")),
        ("Standard selection", _t(j.get("standard_selection"))),
        ("Verification status", _t(j.get("verification_status"))),
        ("Certification scheme", _t(scheme.get("name") or "Not established from a verified record")),
        ("Mark", _t(scheme.get("mark") or "—")),
    ]))
    if j.get("message"):
        out += [Spacer(1, 3 * mm), d.callout(_t(j["message"]), "REVIEW")]
    for line in scheme.get("basis") or []:
        out.append(d.p(f"Why this guidance appears: {_t(line)}", "soft"))
    if scheme.get("conflict"):
        out += [Spacer(1, 2 * mm), d.callout(_t(scheme["conflict"]), "REVIEW")]

    steps = j.get("steps") or []
    if steps:
        out += d.h3("Certification journey")
        rows = []
        for step in steps:
            evidence = step.get("evidence") or []
            quote = evidence[0].get("quote") if evidence else ""
            source = evidence[0] if evidence else {}
            cite = " ".join(x for x in [source.get("document_name"), source.get("source_url")] if x)
            rows.append([f"<font name='Mono'>{step.get('order')}</font>", _t(step.get("title")),
                         _t(quote) + (f"<br/><font size=7 color='#8b8e94'>{_t(cite)}</font>" if cite else "")])
        out.append(d.table(["#", "Step", "What the verified BIS source states"], rows,
                           [8 * mm, 46 * mm, CONTENT_W - 54 * mm]))

    for heading, key in (("Next steps", "next_steps"), ("Limitations", "limitations")):
        values = j.get(key) or []
        if values:
            out += d.h3(heading)
            out += [d.p(f"— {_t(v)}", "soft") for v in values]

    sources = j.get("sources") or []
    if sources:
        out += d.h3("Official sources for this guidance")
        out.append(d.table(["Record", "Document", "Source"],
                           [[_t(e.get("title")), _t(e.get("document_name") or "—"),
                             f"<font size=7>{_t(e.get('source_url') or '—')}</font>"] for e in sources],
                           [58 * mm, 52 * mm, CONTENT_W - 110 * mm]))
    out.append(d.p(_t(j.get("disclaimer") or ""), "faint"))
    return out


def _laboratories(d: _Doc, an: dict) -> list:
    """Milestone 18: laboratories BIS LIMS lists for this inspection's standard.

    Informational discovery, stored with the record. It is NOT a test result,
    NOT part of the compliance decision, and NOT a statement that any of these
    laboratories tested this item — the lead says so explicitly.
    """
    labs = an.get("laboratories") or []
    if not labs:
        return []
    out = d.section(0, "Relevant testing laboratories", "Laboratories that BIS's own LIMS listing "
                    "records against the Indian Standard identified for this package. This is "
                    "discovery information only: none of these laboratories tested this item, none of "
                    "this formed part of the compliance result, and MetrIQ does not establish any "
                    "laboratory's current accreditation, scope, availability or operational status.")
    rows = []
    for lab in labs:
        validity = _t(lab.get("validity_date") or "Not stated")
        if lab.get("validity_status") == "EXPIRED_AT_SNAPSHOT":
            validity += " <font color='#8a6200'>(had passed at snapshot)</font>"
        rows.append([
            _t(lab.get("lab_name")),
            _t(lab.get("city") or "Not stated in the record"),
            f"<font name='Mono'>{_t(lab.get('standard_as_listed'))}</font>",
            validity,
        ])
    out.append(d.table(["Laboratory", "City", "Listed for", "Recognition valid until"], rows,
                       [CONTENT_W - 96 * mm, 30 * mm, 32 * mm, 34 * mm]))
    first = labs[0]
    out.append(d.p(f"Source: {_t(first.get('document_name'))} · retrieved "
                   f"{_t(first.get('retrieved_on'))} · {_t(first.get('source_url'))}", "faint"))
    out.append(d.p("Listed alphabetically, not ranked. Confirm current scope, availability and "
                   "contact details with the laboratory before arranging testing.", "faint"))
    return out


def _legal_metrology(d: _Doc, an: dict) -> list:
    pl = an["package_label"]
    if pl.get("scope_status") == "NOT_APPLIED":
        return d.section(7, "Legal Metrology evidence") + [d.callout(_t(pl["reason"]))]
    out = d.section(7, "Legal Metrology evidence", f"Source authority: {_t(pl['source_authority'])}. These are "
                    "package-label requirements of the Legal Metrology (Packaged Commodities) Rules, 2011 as "
                    "amended — not BIS requirements — and are reported separately from BIS.")
    out.append(d.definitions([
        ("Applicability", _t(pl.get("scope")) or "—"),
        ("Scope status", _t(pl["scope_status"])),
        ("Legal Metrology result", d.badge(pl["overall_status"])),
        ("Reason", _t(pl["reason"])),
    ]))
    for f in pl.get("exclusions_found", []):
        out += [Spacer(1, 2 * mm), d.callout(f"Exclusion read on the label: {_t(f['description'])} "
                                             f"(read: {_t(f['observed'])})", "REVIEW")]
    header = [d.p(_t(h.upper()), "kicker") for h in ("Requirement", "Checkable", "Evidence", "Status")]
    data, style = [header], []
    widths = [72 * mm, 30 * mm, CONTENT_W - 136 * mm, 34 * mm]
    for c in pl["checks"]:
        checkable = c["result"] != "NOT_SUPPORTED"
        evidence = _t(c.get("observed_value")) if c.get("observed_value") else "—"
        regions = [r for e in c.get("evidence", []) for r in e["source_regions"]]
        if regions:
            evidence += f"<br/><font name='Mono' color='#8b8e94'>{_t(', '.join(regions))}</font>"
        src = c.get("source") or {}
        data.append([
            d.p(f"<font name='Mono'>{_t(c['reference'])}</font><br/>{_t(c['requirement'])}", "cell"),
            d.p("Checkable" if checkable else "<font color='#8a6200'>Not checkable from an image</font>", "cell"),
            d.p(evidence, "cell"),
            d.badge(c["result"] if c["result"] in RESULT_COLORS else None, CHECK_RESULT.get(c["result"], c["result"])),
        ])
        source = (f"<font color='#8b8e94'>SOURCE · {_t(AUTHORITY.get(src.get('source_authority'), 'Legal Metrology'))}"
                  f"</font>  {_t(src.get('title'))}<br/><font name='Mono' color='#585c63'>{_t(src.get('source_url'))}</font>"
                  if src else "<font color='#8b8e94'>SOURCE · none stored</font>")
        data.append([d.p(source, "cellsoft"), "", "", ""])
        row = len(data) - 1
        style += [("SPAN", (0, row), (-1, row)), ("NOSPLIT", (0, row - 1), (-1, row)),
                  ("LINEBELOW", (0, row), (-1, row), 0.5, LINE_STRONG),
                  ("TOPPADDING", (0, row), (-1, row), 0), ("LINEBELOW", (0, row - 1), (-1, row - 1), 0, colors.white)]
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm), ("TOPPADDING", (0, 0), (-1, -1), 2.6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2), ("BACKGROUND", (0, 0), (-1, 0), SURFACE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE_STRONG), ("BOX", (0, 0), (-1, -1), 0.5, LINE_STRONG), *style,
    ]))
    out += [Spacer(1, 3 * mm), table]
    if pl.get("assumptions"):
        out.append(KeepTogether([d.p("Applies on these assumptions (not visible on a label)", "h3"),
                                 *[d.p(f"· {_t(a)}", "small") for a in pl["assumptions"]]]))
    return out


def _hallmark_shown(an: dict) -> bool:
    h = an.get("hallmark")
    return bool(h) and bool(h.get("detected") or an.get("inspection_type") == "HALLMARK" or h.get("untrusted_claims"))


def _hallmark(d: _Doc, an: dict) -> list:
    """Hallmark evidence: what was OBSERVED, kept apart from VERIFICATION (never established)."""
    if not _hallmark_shown(an):
        return []
    h = an["hallmark"]
    huid, purity = h["huid"], h["purity"]
    out = d.section(0, "Hallmarking evidence", "Hallmark marks read from the photos by OCR. Observing a potential "
                    "HUID is not authenticating it: MetrIQ has no authoritative HUID verification.")
    sides = {r["id"]: r.get("side", "UNKNOWN") for r in an["ocr"]["regions"]}

    def where(obs: list) -> str:
        return _t(_where([r for o in obs for r in o["source_regions"]], sides))

    huid_text = {"DETECTED": "Potential HUID detected", "MULTIPLE": "Multiple potential HUID values detected",
                 "UNCERTAIN": "Potential HUID detected — uncertain", "NOT_DETECTED": "No potential HUID read"}
    conf = ", ".join(_pct(o["ocr_confidence"]) for o in huid.get("candidates", [])) or "—"
    observed = d.definitions([
        ("Potential HUID", f"{_t(huid_text.get(huid['status'], huid['status']))}"
         + (f": <font name='Mono'>{_t(huid['value'])}</font>" if huid.get("value") else "")),
        ("HUID OCR", "<br/>".join(f"“{_t(o['raw_text'])}” <font name='Mono' color='#8b8e94'>"
                                  f"{_t(o['source_regions'][0])} · {_pct(o['ocr_confidence'])}</font>"
                                  for o in huid.get("candidates", [])) or "—"),
        ("HUID confidence", _t(conf)),
        ("HUID source", where(huid.get("candidates", []))),
        ("Purity / fineness", _t(purity["reason"])),
        ("BIS text", "The letters 'BIS' were read (the BIS logo itself is a graphic OCR cannot establish)."
         if h.get("bis_text") else "Not read."),
    ])
    verification = d.definitions([
        ("Verification status", d.badge(None, _t(h["verification_status"]).replace("_", " "))),
        ("Reason", _t(h["verification_note"])),
    ])
    out += [d.p("OBSERVED FROM THE IMAGE", "kicker"), observed, Spacer(1, 3 * mm),
            d.p("VERIFICATION", "kicker"), verification]
    if h.get("untrusted_claims"):
        out += [Spacer(1, 3 * mm), d.callout(
            "Text printed on the item or package claims verification: "
            + "; ".join(f"“{_t(c['raw_text'])}” ({_t(c['source_regions'][0])})" for c in h["untrusted_claims"])
            + ". Printed text is untrusted OCR evidence and verifies nothing.", "REVIEW")]
    rows = []
    for c in h.get("checks", []):
        label = CHECK_RESULT.get(c["result"], c["result"])
        src = c.get("source") or {}
        rows.append([
            _t(c["requirement"]),
            d.badge(c["result"] if c["result"] in RESULT_COLORS else None, label),
            (_t(c["observed_value"]) if c.get("observed_value") else "—")
            + (f"<br/><font name='Mono' color='#8b8e94'>{_t(', '.join(c['source_regions']))}</font>"
               if c.get("source_regions") else ""),
            f"{_t(c['reason'])}<br/><font name='Mono' color='#8b8e94'>{_t(c['reason_code'])}"
            f"{' · ' + _t(src.get('title')) if src else ''}</font>",
        ])
    if rows:
        out += d.h3("Hallmark checks (deterministic, from the verified BIS Hallmarking FAQ)")
        out.append(d.table(["Check", "Result", "Observed", "Reason / source"], rows,
                           [48 * mm, 30 * mm, 30 * mm, CONTENT_W - 108 * mm]))
    out += [Spacer(1, 2 * mm), d.definitions([("Hallmarking result", d.badge(h["overall_status"])),
                                              ("Why", _t(h["reason"]))])]
    return out


def _vision(d: _Doc, an: dict) -> list:
    """Visual product observations — deliberately its own section, never under BIS evidence.

    These are AI observations about what a photo appears to show. They are not
    verified evidence, not declarations and not a compliance result, and the
    section says so in the words a reader will act on.
    """
    observations = an.get("vision") or []
    if not observations:
        return []

    usable = [o for o in observations if o.get("status") == "OK"]
    out = d.section(0, "Visual product observations",
                    "What the photographs APPEAR to show, produced by an AI vision model. This is an "
                    "unverified observation used only to help identify the product. It is not BIS "
                    "evidence, not a declaration and not a compliance result; no value below was read "
                    "from the label.")

    for o in observations:
        where = f"{_t(o.get('side') or 'UNKNOWN')} · {_t(o.get('image_id') or '')}"
        if o.get("status") != "OK":
            out.append(d.definitions([
                (where, f"Not available — {_t(o.get('reason') or 'the visual model did not answer.')}"),
            ]))
            continue
        rows = [
            ("Photo", where),
            ("Vision model", f"<font name='Mono'>{_t(o.get('model') or '')}</font>"),
            ("Appears to be", _t(o.get("product_label") or "not determined")),
            ("Apparent category", _t(o.get("product_category") or "not determined")),
            ("Model confidence", f"{float(o.get('confidence') or 0.0):.2f} — the model's own confidence, "
                                 "not retrieval confidence and not verification"),
            ("Status", "Unverified visual observation"),
        ]
        if o.get("visual_features"):
            rows.append(("Visible features", _t(", ".join(o["visual_features"]))))
        if o.get("packaging_type"):
            rows.append(("Packaging", _t(o["packaging_type"])))
        for line in o.get("visual_observations") or []:
            rows.append(("Observation", _t(line)))
        for line in o.get("limitations") or []:
            rows.append(("Limitation", _t(line)))
        if o.get("scrubbed"):
            rows.append(("Withheld", "The model wrote something resembling a declared or legal value. "
                                     "MetrIQ removed it: only OCR evidence may report such values."))
        out.append(d.definitions(rows))

    signals = (an.get("product") or {}).get("signals") or {}
    if usable:
        if signals.get("conflicts"):
            out.append(d.callout("The package text and the visual observation disagree. MetrIQ does not "
                                 "choose between them; the product is reported as needing review."))
        elif signals.get("agreement"):
            out.append(d.callout("The visual observation agrees with the product read from the label text. "
                                 "Agreement supports the identification but adds no verified evidence, and "
                                 "did not change any result."))
    return out


def _compliance(d: _Doc, an: dict) -> list:
    out = d.section(8, "Compliance results", "Each row is one deterministic rule applied to the stored OCR evidence "
                    "and a verified requirement. No language model produced or changed these results. UNSUPPORTED "
                    "means the requirement cannot be checked from a package image — it is never counted as PASS.")
    rows = []
    for source, ev in (("BIS", an["compliance"]), ("LEGAL_METROLOGY", an["package_label"])):
        for c in ev["checks"]:
            label = CHECK_RESULT.get(c["result"], c["result"])
            regions = [r for e in c.get("evidence", []) for r in e["source_regions"]]
            evidence = (_t(c["observed_value"]) if c.get("observed_value") else "<i>nothing read</i>") + (
                f"<br/><font name='Mono' color='#8b8e94'>{_t(', '.join(regions))}</font>" if regions else "")
            rows.append([
                f"{_t(c['requirement'])}<br/><font name='Mono' color='#8b8e94'>{_t(AUTHORITY[source])}"
                f"{' · ' + _t(c['reference']) if c.get('reference') else ''}</font>",
                d.badge(c["result"] if c["result"] in RESULT_COLORS else None, label),
                evidence,
                f"{_t(c['reason'])}<br/><font name='Mono' color='#8b8e94'>{_t(c['reason_code'])}</font>",
            ])
    if not rows:
        return out + [d.p("No deterministic checks are stored for this inspection.", "soft")]
    return out + [d.table(["Requirement", "Result", "Evidence", "Reason (from the rule)"], rows,
                          [50 * mm, 32 * mm, 33 * mm, CONTENT_W - 115 * mm])]


def _system_result(d: _Doc, rec: dict, an: dict) -> list:
    out = d.section(9, "Automated system result")
    out.append(d.definitions([
        ("System result", d.badge(rec["system_result"])),
        ("How it is combined", "FAIL if any applicable evidence system (BIS, Legal Metrology, hallmarking) is FAIL; "
                               "PASS only if all are PASS; otherwise REVIEW."),
        *[(f"{AUTHORITY[r['source']]} result",
           [d.badge(r["result"]), Spacer(1, 1 * mm), d.p(_t(r["reason"]), "cell"),
            d.p(_t(r["reason_code"]), "kicker")]) for r in rec["system_reasons"]],
        ("Escalation", "Officer review required — the system could not confidently resolve this inspection."
         if rec["escalation_required"] else "Not required — the system resolved this inspection."),
    ]))
    reasons = rec.get("escalation_reasons") or []
    if reasons:
        out += d.h3("Why the system could not resolve it" if rec["escalation_required"] else "Recorded observations")
        out.append(d.table(["Reason", "Source", "Detail", "Evidence"], [[
            _t(r["label"]), _t(REASON_SOURCE.get(r["source"], r["source"])), _t(r["message"]),
            f"<font name='Mono'>{_t(', '.join(r['source_regions'] + r['checks'])) or '—'}</font>",
        ] for r in reasons], [34 * mm, 22 * mm, CONTENT_W - 96 * mm, 40 * mm]))
    fields = an["declaration_stage"]["fields"]
    unresolved = [f["label"] for f in fields if f["status"] == "UNCERTAIN"]
    conflicts = [f["label"] for f in fields if f.get("consistency") == "CONFLICT"]
    unsupported = [(c.get("reference") or c["requirement"]).rstrip(".") for ev in (an["compliance"], an["package_label"])
                   for c in ev["checks"] if c["result"] == "NOT_SUPPORTED"]
    if _hallmark_shown(an):
        h = an["hallmark"]
        unresolved += [f"Hallmark {k}" for k in ("HUID", "purity") if h["huid" if k == "HUID" else "purity"]["status"]
                       in ("UNCERTAIN", "MULTIPLE")]
        conflicts += ["Hallmark purity"] if h["purity"]["status"] == "CONFLICT" else []
        unsupported += [c["requirement"].rstrip(".") for c in h["checks"] if c["result"] == "NOT_SUPPORTED"]
    out += [Spacer(1, 3 * mm), d.definitions([
        ("Uncertain declarations", _t(", ".join(unresolved)) or "None"),
        ("Conflicting declarations", _t(", ".join(conflicts)) or "None"),
        ("Unsupported checks", _t("; ".join(unsupported)) or "None"),
    ])]
    return out


def _officer(d: _Doc, rec: dict) -> list:
    out = d.section(10, "Officer review")
    status = rec["officer_status"]
    if status == "NOT_REQUIRED":
        return out + [d.callout("Officer review was not required: the system resolved this inspection and it was "
                                "never sent to the officer queue.")]
    rows = [("Status", _t(OFFICER_STATUS[status])),
            ("Review started", _t(_fmt_time(rec.get("review_started_at"))))]
    if status == "COMPLETED":
        rows += [("Officer decision", _t(DECISIONS[rec["officer_decision"]])),
                 ("Officer result", d.badge(rec["officer_result"]) if rec.get("officer_result") else "— (only an override records one)"),
                 ("Officer note", _t(rec.get("officer_note")) or "<font color='#8b8e94'>No note recorded</font>"),
                 ("Review completed", _t(_fmt_time(rec.get("review_completed_at"))))]
    out.append(d.definitions(rows))
    if status != "COMPLETED":
        out += [Spacer(1, 3 * mm), d.callout("Officer review has not yet been completed. No officer has approved, "
                                             "overridden or otherwise decided this inspection.", "REVIEW")]
    out += [Spacer(1, 2 * mm), d.p("MetrIQ has no officer accounts, so no officer identity is recorded or shown.",
                                   "faint")]
    return out


def _final(d: _Doc, rec: dict) -> list:
    out = d.section(11, "Final outcome", "The automated system result and the officer's decision are recorded "
                    "separately. The officer's decision never replaces the system result.")
    status = rec["officer_status"]
    rows = [("System result", d.badge(rec["system_result"]))]
    if status == "NOT_REQUIRED":
        rows += [("Officer final decision", "Not required"),
                 ("Final result", [d.badge(rec["system_result"]), d.p("The system result is final.", "small")])]
    elif status == "COMPLETED":
        rows.append(("Officer final decision", _t(DECISIONS[rec["officer_decision"]])))
        if rec["officer_decision"] == "OVERRIDE":
            rows.append(("Officer result", d.badge(rec["officer_result"])))
        rows.append(("Officer note", _t(rec.get("officer_note")) or "<font color='#8b8e94'>No note recorded</font>"))
        final = rec.get("final_result")
        rows.append(("Final result", d.badge(final) if final in RESULT_COLORS
                     else d.badge(None, "MANUAL REVIEW")))
    else:
        rows += [("Officer final decision", "<font color='#8a6200'>Pending — officer review "
                  f"{_t(OFFICER_STATUS[status].lower())}</font>"),
                 ("Final result", "<font color='#8a6200'>Not final until the officer review is completed</font>")]
    out.append(KeepTogether([d.definitions(rows)]))
    return out


def _sources(d: _Doc, rec: dict, an: dict) -> list:
    out = d.section(12, "Evidence and sources", "Only the sources stored with this inspection's evidence.")
    seen: set[tuple] = set()

    def collect(sources) -> list:
        items = []
        for s in sources:
            if not s:
                continue
            key = (s.get("title"), s.get("source_url"))
            if key in seen:
                continue
            seen.add(key)
            items.append(KeepTogether([*d.source_block(s), Spacer(1, 2.5 * mm)]))
        return items

    bis = [c for c in an["standards"] if c.get("source_url") or c.get("document_name")]
    bis_checks = [s for c in an["compliance"]["checks"] for s in [c.get("source"), *c.get("supporting_sources", [])]]
    lm = [an["package_label"].get("scope_source")] + [
        s for c in an["package_label"]["checks"] for s in [c.get("source"), *c.get("supporting_sources", [])]]
    hallmark_sources = an["hallmark"].get("sources", []) if _hallmark_shown(an) else []
    hallmark_sources = [{**s, "reference": None} for s in hallmark_sources]
    groups = [("BIS", collect(bis + bis_checks)), ("Legal Metrology", collect(lm))]
    if hallmark_sources:
        groups.append(("BIS Hallmarking", collect(hallmark_sources)))
    for title, items in groups:
        out += d.h3(title)
        out += items or [d.p("No source of this authority is stored for this inspection.", "soft")]
    out += d.h3("OCR / package evidence")
    out += [d.p(f"{_t(i['side'])} · image {i['index']} · {_t(i['filename'])} · <font name='Mono'>{_t(i['image_id'])}"
                "</font>", "cell") for i in rec["images"]] or [d.p("No photos stored.", "soft")]
    return out


# ------------------------------------------------------------------ entry point


def build_story(record: dict, images: dict[int, bytes], generated_at: datetime) -> list:
    """The report's flowables, in order. Separate from rendering so the content can be inspected."""
    _register_fonts()
    d = _Doc()
    an = record["analysis"]
    generated = _fmt_time(generated_at)

    status = OFFICER_STATUS[record["officer_status"]]
    story: list = [
        d.p("MetrIQ", "brand"),
        Spacer(1, 1 * mm),
        d.p("EVIDENCE-BACKED PRODUCT INSPECTION REPORT", "eyebrow"),
        Spacer(1, 2.5 * mm),
        d.p(f"Inspection <font name='Mono'>{_t(record['inspection_id'])}</font>", "title"),
        Spacer(1, 4 * mm),
        d.definitions([
            ("Inspection ID", f"<font name='Mono'>{_t(record['inspection_id'])}</font>"),
            ("Inspection saved", _t(_fmt_time(record["created_at"]))),
            ("Report generated", _t(generated)),
            ("Current status", f"System result {_t(record['system_result'])} · officer review: {_t(status)}"),
        ]),
        Spacer(1, 3 * mm),
        d.callout("This report is an audit trail of the persisted inspection record. It was generated from stored "
                  "data only: no result was recomputed, no language model was used, and nothing was changed. "
                  "It is not a BIS certification or a legal determination."),
    ]
    story += _summary(d, record, an)
    story += _photos(d, record, an, images)
    story += _ocr(d, an)
    story += _declarations(d, an)
    story += _bis(d, record, an)
    story += _certification(d, an)
    story += _laboratories(d, an)
    story += _legal_metrology(d, an)
    story += _hallmark(d, an)
    story += _vision(d, an)
    story += _compliance(d, an)
    story += _system_result(d, record, an)
    story += _officer(d, record)
    story += _final(d, record)
    story += _sources(d, record, an)
    return story


def render_report(record: dict, images: dict[int, bytes], generated_at: datetime) -> bytes:
    """PDF bytes for one persisted inspection. ``record`` is the stored ``InspectionRecordOut`` as JSON;
    ``images`` maps upload position -> stored photo bytes. Read-only: it only formats what it is given."""
    story = build_story(record, images, generated_at)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=16 * mm, bottomMargin=19 * mm,
        title=f"MetrIQ inspection report {record['inspection_id']}", author="MetrIQ",
        subject="Evidence-backed product inspection report",
    )
    doc.build(story, canvasmaker=_numbered_canvas(record["inspection_id"], _fmt_time(generated_at)))
    return buf.getvalue()
