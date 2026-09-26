"""Quality Control Order evidence for a standard MetrIQ has ALREADY retrieved (Phase 9).

QCO records (category ``quality_control_orders``) are rows of BIS's table "Upcoming
QCOs – notified and due for implementation", transcribed verbatim by
``scripts/fetch_qco.py``. Like clause records (Phase 7) they are citation-only:
excluded from the main search index (see ``SearchEngine.__init__``) and reached here by
standard number, after retrieval has chosen the standard.

    qco_for(number)          the rows whose IS number, as printed, is exactly that
                             standard after normalising whitespace and a missing "IS "
    status_for(number, …)    IN_FORCE | UPCOMING | NOT_ESTABLISHED, with MetrIQ's own
                             sentences (en / hi / te) and the quoted rows
    match_report(kb_numbers) every row: ATTACHED, or MISMATCH with its reason

Hard rules, each enforced here rather than hoped for:

* A status comes only from a quoted official row. No row -> NOT_ESTABLISHED.
* Status follows the TABLE the row came from, never today's date. The upcoming table
  lists orders due for implementation, so its rows are UPCOMING — even after the
  printed date has passed, because dates are often deferred and MetrIQ cannot know.
  IN_FORCE needs a BIS table that states an order is in force; Phase 9 found none
  (the compulsory-certification listing pages carry notification links but never say
  "in force", and mix in rescind and suspension orders), so nothing here yields it.
* Being on a "Products under Compulsory Certification" page is not a QCO and is never
  read as one: this module reads only ``quality_control_orders`` records.
* Every sentence is about the ORDER and the TABLE, never about the user's item.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from app import language as lang
from app.knowledge.loader import load_knowledge_base
from app.knowledge.schema import KnowledgeItem
from app.retrieval.text import STOPWORDS, normalize

IN_FORCE = "IN_FORCE"
UPCOMING = "UPCOMING"
NOT_ESTABLISHED = "NOT_ESTABLISHED"
STATUSES = (IN_FORCE, UPCOMING, NOT_ESTABLISHED)

# The table each record came from decides its status. A table that states orders are
# in force would map to IN_FORCE; BIS publishes none as HTML (Phase 9, Step 1).
UPCOMING_TABLE = "https://www.bis.gov.in/upcoming-qcos-notified-and-due-for-implementation/?lang=en"
STATUS_BY_TABLE = {UPCOMING_TABLE: UPCOMING}

# Mismatch reasons (match_report). A row is never corrected to make it attach.
NUMBER_NOT_IN_KB = "NUMBER_NOT_IN_KB"
PART_SECTION_DIFFERS = "PART_SECTION_DIFFERS"
DIFFERENT_YEAR = "DIFFERENT_YEAR"
KB_RECORD_HAS_NO_YEAR = "KB_RECORD_HAS_NO_YEAR"


# ------------------------------------------------------------------ records


def normalise(number: str) -> str:
    """Whitespace and a missing "IS " prefix — nothing else. "4003 (Part 1):1978" and
    "IS 4003 (Part 1): 1978" both become "IS4003(Part1):1978"."""
    compact = re.sub(r"\s+", "", number or "")
    return compact if compact.upper().startswith("IS") else "IS" + compact


@lru_cache(maxsize=1)
def _records() -> tuple[KnowledgeItem, ...]:
    return tuple(i for i in load_knowledge_base().items if i.category == "quality_control_orders")


def qco_for(standard_number: str | None) -> list[KnowledgeItem]:
    """The QCO rows naming exactly this standard (same number, part/section and year)."""
    if not standard_number:
        return []
    key = normalise(standard_number)
    return [r for r in _records() if normalise(r.standard_number or "") == key]


_FIELD = re.compile(r"^(Sr\. No\.|Ministry/Department|Product|Indian Standard|Enforcement date|"
                    r"Products listed under this row|Link given for this row): (.*)$", re.M)


def fields(item: KnowledgeItem) -> dict[str, str]:
    """The row's cells, read back out of the record exactly as transcribed."""
    return dict(_FIELD.findall(item.content))


def _date(printed: str) -> dt.date | None:
    """"01 October, 2026" -> date. None when BIS printed something else — then MetrIQ
    quotes it and makes no statement about whether it has passed."""
    try:
        return dt.datetime.strptime(re.sub(r"\s+", " ", printed.replace(",", "")).strip(),
                                    "%d %B %Y").date()
    except ValueError:
        return None


# ------------------------------------------------------------------ status


class QcoRowOut(BaseModel):
    """One row of a BIS QCO table, verbatim."""

    sr_no: str
    ministry: str
    product: str
    standard_as_printed: str
    enforcement_date: str = Field(description="Exactly as BIS printed it.")
    listed_products: list[str] = Field(default_factory=list)
    link: str | None = Field(default=None, description="A link the row gives; recorded, never fetched.")
    table: str
    source_url: str
    read_on: str | None = None


class QcoOut(BaseModel):
    """Quality Control Order evidence for one standard. Never about the user's item."""

    status: str = Field(description='"IN_FORCE" | "UPCOMING" | "NOT_ESTABLISHED"')
    label: str = Field(description="Short badge text, written by MetrIQ.")
    statements: list[str] = Field(description="MetrIQ's own sentences, in the requested language.")
    rows: list[QcoRowOut] = Field(default_factory=list)


def row_out(item: KnowledgeItem) -> QcoRowOut:
    f = fields(item)
    link = f.get("Link given for this row", "none")
    listed = f.get("Products listed under this row", "")
    return QcoRowOut(
        sr_no=f.get("Sr. No.", ""), ministry=f.get("Ministry/Department", ""),
        product=f.get("Product", ""), standard_as_printed=item.standard_number or "",
        enforcement_date=f.get("Enforcement date", ""),
        listed_products=[p for p in listed.split("; ") if p],
        link=None if link == "none" else link,
        table=item.document_name or "", source_url=item.source_url or "",
        read_on=item.last_verified.isoformat() if item.last_verified else None,
    )


def _row_sentences(item: KnowledgeItem, text: dict, today: dt.date) -> list[str]:
    row = row_out(item)
    out = [text["upcoming"].format(ministry=row.ministry, product=row.product,
                                   number=row.standard_as_printed, date=row.enforcement_date,
                                   read_on=row.read_on)]
    printed = _date(row.enforcement_date)
    if printed is not None and printed < today:
        out.append(text["passed"].format(read_on=row.read_on, date=row.enforcement_date))
    else:
        out.append(text["not_in_force"])
    return out


def status_for(standard_number: str | None, language: str = lang.EN,
               today: dt.date | None = None, later_edition: str | None = None) -> QcoOut:
    """The QCO status of one knowledge-base standard, from quoted rows only.

    ``today`` decides one thing only: whether to SAY that a printed date has passed.
    It never changes the status. ``later_edition`` (Phase 5 SUPERSEDED_BY) adds the
    edition fact beside the row; MetrIQ never says which edition an order requires.
    """
    text = lang.qco(language)
    rows = qco_for(standard_number)
    if not rows:
        return QcoOut(status=NOT_ESTABLISHED, label=text["label"][NOT_ESTABLISHED],
                      statements=[text["not_established"]])
    status = STATUS_BY_TABLE[rows[0].source_url]      # KeyError = a table with no status rule
    statements = [s for r in rows for s in _row_sentences(r, text, today or dt.date.today())]
    if later_edition:
        statements.append(text["edition"].format(later=later_edition,
                                                 number=rows[0].standard_number))
    return QcoOut(status=status, label=text["label"][status], statements=statements,
                  rows=[row_out(r) for r in rows])


def for_standard(standard_number: str | None, language: str = lang.EN) -> QcoOut:
    """``status_for`` with the Phase 5 edition fact beside it: when MetrIQ's edition
    evidence shows a later edition (SUPERSEDED_BY), both facts are shown side by side."""
    from app.standard_currency import SUPERSEDED_BY, currency_for
    currency = currency_for(standard_number)
    later = currency.later_edition if currency and currency.status == SUPERSEDED_BY else None
    return status_for(standard_number, language, later_edition=later)


# ------------------------------------------------------------------ listing orders
#
# Phase 9.1: the orders BIS's compulsory-certification listing NAMES for a product —
# its Notification column, snapshotted by
# ``scripts/fetch_compulsory_certification.py --notifications`` into
# data/listing_notifications.json and joined to the record transcribed from that row
# by exact number and product wording. This is EVIDENCE, never a status: nothing
# here reads or sets ``status``, so IN_FORCE cannot come from a listing.

LISTING_PATH = Path(__file__).resolve().parents[2] / "data" / "listing_notifications.json"


@lru_cache(maxsize=1)
def _listing() -> dict:
    return json.loads(LISTING_PATH.read_text(encoding="utf-8"))


def orders_named_by_listing(standard_number: str | None) -> list[dict]:
    """The listing rows joined to exactly this knowledge-base standard (the number as
    stored). Rows that did not join a record are never returned."""
    if not standard_number:
        return []
    return [r for r in _listing()["rows"] if r["kb_standard_number"] == standard_number]


class ListingOrderOut(BaseModel):
    number: str | None = Field(default=None, description='"S.O. 191(E)" — parsed; null when none printed.')
    date: str | None = Field(default=None, description="As printed; null when none printed.")
    text: str = Field(description="The link text or the cell text, verbatim.")
    url: str | None = Field(default=None, description="The Gazette link the cell gives; recorded, never fetched.")


class ListingGroupOut(BaseModel):
    scheme: str
    products: list[str]
    notification: str = Field(description="The Notification cell, verbatim.")
    orders: list[ListingOrderOut]
    flags: list[str] = Field(default_factory=list,
                             description="RESCISSION | WITHDRAWAL | SUSPENSION | SUPERSESSION — quoted, not interpreted.")
    source_url: str


class ListingOrdersOut(BaseModel):
    """What BIS's listing names. Never a status, never about the user's item."""

    statements: list[str]
    groups: list[ListingGroupOut]
    read_on: str | None = None


def _group(rows: list[dict]) -> list[ListingGroupOut]:
    """Rows sharing one Notification cell (e.g. 43 IS/IEC 62368 products) become one group."""
    groups: dict[tuple, ListingGroupOut] = {}
    for row in rows:
        key = (row["scheme"], row["notification"])
        if key not in groups:
            groups[key] = ListingGroupOut(
                scheme=row["scheme"], products=[], notification=row["notification"] or "",
                orders=[ListingOrderOut(**o) for o in row["orders"]], flags=row["flags"],
                source_url=row["source_url"])
        groups[key].products.append(row["product"])
    return list(groups.values())


def listing_orders_for(standard_number: str | None, language: str = lang.EN) -> ListingOrdersOut | None:
    """MetrIQ's sentences about the orders the listing names, or None when it names none."""
    rows = [r for r in orders_named_by_listing(standard_number) if r["notification"]]
    if not rows:
        return None
    text = lang.listing(language)
    statements = []
    groups = _group(rows)
    for g in groups:
        products = (text["products_one"].format(product=g.products[0]) if len(g.products) == 1
                    else text["products_many"].format(count=len(g.products)))
        scheme = text["scheme"][g.scheme]
        named = [text["dated"].format(number=o.number, date=o.date) if o.date else o.number
                 for o in g.orders if o.number]
        named = list(dict.fromkeys(named))
        if named:
            key = "names_one" if len(named) == 1 else "names_many"
            statements.append(text[key].format(scheme=scheme, products=products, orders="; ".join(named)))
        else:
            statements.append(text["cell_only"].format(scheme=scheme, products=products, cell=g.notification))
        if g.flags:
            statements.append(text["flag"].format(
                what=text["and"].join(text["flags"][f] for f in g.flags)))
    statements.append(text["boundary"])
    return ListingOrdersOut(statements=statements, groups=groups, read_on=_listing().get("read_on"))


# An order number an answer cites ("S.O. 191(E)", "SO 516 (E)", "G.S.R. 759(E)").
_ORDER_NO = re.compile(r"\b(S\.?\s*O|G\.?\s*S\.?\s*R)\.?\s*(?:No\.?\s*)?(\d+)\s*\(\s*E\s*\)", re.I)


def _order_keys(text: str) -> set[str]:
    return {("SO" if m.group(1).upper().replace(".", "").replace(" ", "") == "SO" else "GSR") + m.group(2)
            for m in _ORDER_NO.finditer(text or "")}


def unsupported_order_numbers(answer: str, context: str) -> set[str]:
    """S.O. / G.S.R. numbers the answer cites that appear nowhere in the supplied context."""
    return _order_keys(answer) - _order_keys(context)


# ------------------------------------------------------------------ matching


_PARTS = re.compile(r"^IS(?:/[A-Z]+)?(\d+)(.*?)(?::((?:19|20)\d{2}))?$", re.IGNORECASE)


def _split(number: str) -> tuple[str, str, str]:
    """(number, part/section text, year) of a normalised identifier."""
    m = _PARTS.match(normalise(number))
    return (m.group(1), m.group(2), m.group(3) or "") if m else (normalise(number), "", "")


def match_report(kb_numbers: list[str]) -> list[dict]:
    """Every QCO row: ATTACHED to the KB standard it names exactly, or a MISMATCH with
    its reason. A mismatch is reported as it is and never corrected into a match."""
    exact = {normalise(n): n for n in kb_numbers}
    report = []
    for item in _records():
        printed = item.standard_number or ""
        entry = {"sr_no": fields(item).get("Sr. No.", ""), "printed": printed,
                 "product": fields(item).get("Product", "")}
        if normalise(printed) in exact:
            report.append({**entry, "result": "ATTACHED", "kb": exact[normalise(printed)]})
            continue
        number, part, year = _split(printed)
        same_number = [n for n in kb_numbers if _split(n)[0] == number]
        same_part = [n for n in same_number if _split(n)[1] == part]
        if not same_number:
            reason = NUMBER_NOT_IN_KB
        elif not same_part:
            reason = PART_SECTION_DIFFERS
        elif all(not _split(n)[2] for n in same_part):
            reason = KB_RECORD_HAS_NO_YEAR
        else:
            reason = DIFFERENT_YEAR
        report.append({**entry, "result": "MISMATCH", "reason": reason,
                       "kb_candidates": same_part or same_number})
    return report


# ------------------------------------------------------------------ boundary


def _tokens(text: str) -> list[str]:
    # The product-identification phrase rule (app/product_identification._tokens):
    # normalised words, a trailing plural "s" dropped.
    from app.product_identification import _tokens as phrase_tokens
    return phrase_tokens(text)


def boundary_rows(product_phrase: str) -> list[tuple[KnowledgeItem, str]]:
    """Rows whose product wording contains the user's WHOLE product phrase, as a
    contiguous run of words, when that phrase has at least two words. A single word
    ("dishwashers") never matches anything — the multi-word rule product
    identification uses. Returns (row, the wording that matched)."""
    phrase = tuple(_tokens(product_phrase))
    if len(phrase) < 2:
        return []
    found = []
    for item in _records():
        f = fields(item)
        wordings = [f.get("Product", ""), *row_out(item).listed_products]
        for wording in wordings:
            words = _tokens(wording)
            if any(tuple(words[i:i + len(phrase)]) == phrase for i in range(len(words) - len(phrase) + 1)):
                found.append((item, wording))
                break
    return found


def boundary_sentences(product_phrase: str, language: str = lang.EN) -> list[str]:
    """MetrIQ's words for an abstention whose product phrase matches a QCO row."""
    text = lang.qco(language)
    out = []
    for item, wording in boundary_rows(product_phrase):
        row = row_out(item)
        out.append(text["boundary"].format(wording=wording, ministry=row.ministry,
                                           number=row.standard_as_printed,
                                           date=row.enforcement_date, read_on=row.read_on))
    return out


def phrase_of(question: str) -> str:
    """The product phrase of a question: its words minus stopwords, FILLER and the BIS
    process words — the same lists the Phase 6 follow-up rule uses."""
    return " ".join(w for w in normalize(question).split()
                    if w not in lang.FILLER and w not in lang.FOLLOW_UP_WORDS
                    and w not in STOPWORDS)

