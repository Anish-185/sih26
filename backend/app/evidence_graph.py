"""Milestone 22 — the evidence graph.

**The MetrIQ evidence graph visualizes relationships already established by the
deterministic evidence pipeline. It does not independently infer standards,
compliance, authenticity, laboratory validity, or certification applicability.**

It answers one question — *how did MetrIQ arrive at this result?* — by reading a
FINISHED analysis (or a finished product context) and turning the relationships
those systems already recorded into nodes and edges:

    OCR region / visual observation --OBSERVED_IN-->  declaration
    product            --IDENTIFIED_FROM-->           declaration / OCR / vision
    product            --MATCHED_TO-->                verified standard
    standard           --SOURCED_FROM-->              verified BIS record
    standard           --RELATED_TO-->                certification route · laboratory listing
    standard           --REQUIRES-->                  verified requirement (knowledge, not a verdict)
    requirement        --SOURCED_FROM-->              the verified record it is quoted from

MetrIQ produces no automatic PASS/FAIL/REVIEW compliance verdict, so the graph
has no RULE or SYSTEM_RESULT node and no CHECKED_BY/RESULTED_IN edge — a
REQUIREMENT node is BIS/Legal-Metrology knowledge ("the standard specifies
this"), never a check outcome.

This module is a PROJECTION, not a reasoning engine. It calls no model, runs no
retrieval, evaluates no rule and reaches no conclusion of its own: every node
label, status and quote is copied from the analysis it was given, and an edge
exists only where that analysis already links the two things. Nothing downstream
reads the graph — removing it changes no result.

Boundaries that are structural here, not wording:

* there is no node type or status that authenticates a physical item. A hallmark
  or HUID observation is an OBSERVATION; ``verified`` is never a node status;
* a laboratory node reports only what the BIS LIMS snapshot listed, with
  ``*_AT_SNAPSHOT`` validity — never "currently valid", never accreditation,
  contacts, scope or availability;
* a certification route that the verified records do not establish becomes a
  NOT_AVAILABLE node, never an inferred route;
* on the query path the product is UNCERTAIN, because typed text is not evidence
  about a physical item;
* only evidence belonging to the current context is included — never the whole
  knowledge base, laboratory snapshot or inspection history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from pydantic import BaseModel, Field

from app.requirements import load_requirements

# ------------------------------------------------------------------ vocabulary

PRODUCT = "PRODUCT"
OCR_EVIDENCE = "OCR_EVIDENCE"
DECLARATION = "DECLARATION"
VISION_OBSERVATION = "VISION_OBSERVATION"
STANDARD = "STANDARD"
CERTIFICATION = "CERTIFICATION"
REQUIREMENT = "REQUIREMENT"
LABORATORY = "LABORATORY"
HALLMARK_OBSERVATION = "HALLMARK_OBSERVATION"
HUID_OBSERVATION = "HUID_OBSERVATION"
SOURCE = "SOURCE"

NODE_TYPES: tuple[str, ...] = (
    PRODUCT, OCR_EVIDENCE, DECLARATION, VISION_OBSERVATION, STANDARD, CERTIFICATION,
    REQUIREMENT, LABORATORY, HALLMARK_OBSERVATION, HUID_OBSERVATION, SOURCE,
)

IDENTIFIED_FROM = "IDENTIFIED_FROM"
SUPPORTED_BY = "SUPPORTED_BY"
MATCHED_TO = "MATCHED_TO"
EXPLAINS = "EXPLAINS"
REQUIRES = "REQUIRES"
SOURCED_FROM = "SOURCED_FROM"
RELATED_TO = "RELATED_TO"
OBSERVED_IN = "OBSERVED_IN"

EDGE_TYPES: tuple[str, ...] = (
    IDENTIFIED_FROM, SUPPORTED_BY, MATCHED_TO, EXPLAINS, REQUIRES,
    SOURCED_FROM, RELATED_TO, OBSERVED_IN,
)

# Where the node's content came from — the same vocabulary the product context uses.
USER_DESCRIPTION = "USER_DESCRIPTION"
OCR_TEXT = "OCR_TEXT"
DECLARATION_EXTRACTION = "DECLARATION"
VISION = "VISION_OBSERVATION"
DETERMINISTIC_RETRIEVAL = "DETERMINISTIC_RETRIEVAL"
BIS_KNOWLEDGE_BASE = "BIS_KNOWLEDGE_BASE"
LEGAL_METROLOGY_KNOWLEDGE = "LEGAL_METROLOGY_KNOWLEDGE"
LABORATORY_SNAPSHOT = "LABORATORY_SNAPSHOT"
HALLMARK_OBSERVATION_SOURCE = "HALLMARK_OBSERVATION"

# A node's layer, so a view can lay the graph out without knowing the node types.
LAYERS = {
    OCR_EVIDENCE: 0, VISION_OBSERVATION: 0,
    DECLARATION: 1,
    PRODUCT: 2,
    STANDARD: 3,
    CERTIFICATION: 4, REQUIREMENT: 4, LABORATORY: 4, HALLMARK_OBSERVATION: 4, HUID_OBSERVATION: 4,
    SOURCE: 5,
}

NOTE = (
    "The MetrIQ evidence graph visualizes relationships already established by the deterministic "
    "evidence pipeline. It does not independently infer standards, compliance, authenticity, "
    "laboratory validity, or certification applicability."
)

# Contextual, not exhaustive: the graph only ever shows this case's evidence.
MAX_OCR = 40
MAX_DECLARATIONS = 16
MAX_STANDARDS = 3
MAX_REQUIREMENTS = 30
MAX_LABS = 6
MAX_SOURCES = 24
MAX_HALLMARK_CHECKS = 8


@dataclass(frozen=True)
class Node:
    id: str
    type: str
    label: str
    status: str = ""          # the status the producing system recorded, verbatim
    detail: dict = field(default_factory=dict)
    provenance: tuple[str, ...] = ()
    source_regions: tuple[str, ...] = ()
    source_url: str | None = None
    limitations: tuple[str, ...] = ()

    @property
    def layer(self) -> int:
        return LAYERS[self.type]


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    type: str
    explanation: str


class _Builder:
    """Collects nodes and edges, ignoring anything that would dangle."""

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self._source_ids: dict[tuple, str] = {}

    def add(self, node: Node) -> str:
        self.nodes.setdefault(node.id, node)
        return node.id

    def link(self, source: str, target: str, type_: str, explanation: str) -> None:
        if source in self.nodes and target in self.nodes and source != target:
            edge = Edge(source, target, type_, explanation)
            if edge not in self.edges:
                self.edges.append(edge)

    def source(self, src: dict | None, authority: str = "BIS") -> str | None:
        """One SOURCE node per verified record actually stored with the evidence."""
        if not src:
            return None
        title = src.get("title") or src.get("document_name")
        url = src.get("source_url")
        if not title and not url:
            return None
        key = (title, url)
        if key in self._source_ids:
            return self._source_ids[key]
        if len([n for n in self.nodes.values() if n.type == SOURCE]) >= MAX_SOURCES:
            return None
        node_id = f"src:{len(self._source_ids) + 1}"
        self._source_ids[key] = node_id
        detail = {k: v for k, v in (
            ("document_name", src.get("document_name")),
            ("reference", src.get("reference")),
            ("quote", src.get("quote")),
            ("verification_status", src.get("verification_status")),
            ("last_verified", src.get("last_verified")),
            ("authority", src.get("source_authority") or authority),
        ) if v}
        return self.add(Node(node_id, SOURCE, title or url, detail=detail,
                             provenance=(LEGAL_METROLOGY_KNOWLEDGE
                                         if (src.get("source_authority") == "LEGAL_METROLOGY")
                                         else BIS_KNOWLEDGE_BASE,),
                             source_url=url))


@dataclass(frozen=True)
class EvidenceGraph:
    origin: str  # "INSPECTION" | "PRODUCT_CONTEXT"
    root_id: str
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    inspection_id: str | None = None
    query: str = ""
    limitations: tuple[str, ...] = ()

    def node(self, node_id: str) -> Node | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def of_type(self, type_: str) -> tuple[Node, ...]:
        return tuple(n for n in self.nodes if n.type == type_)


# ------------------------------------------------------------------ inspection


def _region_nodes(b: _Builder, analysis: dict, wanted: set[str]) -> None:
    for region in (analysis.get("ocr") or {}).get("regions", []):
        if region.get("id") not in wanted or len(b.nodes) > MAX_OCR * 4:
            continue
        b.add(Node(
            f"ocr:{region['id']}", OCR_EVIDENCE, region["id"],
            status="READ",
            detail={"text": region.get("text"), "confidence": region.get("confidence"),
                    "image_id": region.get("image_id"), "side": region.get("side"),
                    "bbox": region.get("bbox")},
            provenance=(OCR_TEXT,), source_regions=(region["id"],),
            limitations=("OCR text is raw package evidence. It is read, not verified.",),
        ))


def _declaration_nodes(b: _Builder, analysis: dict) -> dict[str, str]:
    """One node per declaration the extraction recorded. NOT_DETECTED is kept as
    a status — it is a statement about the photographs, never a legal absence."""
    ids: dict[str, str] = {}
    for decl in (analysis.get("declaration_stage") or {}).get("fields", [])[:MAX_DECLARATIONS]:
        node_id = f"decl:{decl['field']}"
        ids[decl["field"]] = b.add(Node(
            node_id, DECLARATION, decl.get("label") or decl["field"],
            status=decl.get("status") or "",
            detail={k: v for k, v in (
                ("value", decl.get("value")), ("raw_text", decl.get("raw_text")),
                ("consistency", decl.get("consistency")), ("reason", decl.get("reason")),
                ("extraction_method", decl.get("extraction_method")),
                ("ocr_confidence", decl.get("ocr_confidence")),
                ("sides", decl.get("source_sides")),
            ) if v not in (None, "", [])},
            provenance=(DECLARATION_EXTRACTION, OCR_TEXT),
            source_regions=tuple(decl.get("source_regions") or []),
            limitations=(("NOT_DETECTED means the photographs did not show it — never that it is "
                          "legally missing.",) if decl.get("status") == "NOT_DETECTED" else ()),
        ))
        for region in (decl.get("source_regions") or []):
            b.link(node_id, f"ocr:{region}", OBSERVED_IN,
                   f"{decl.get('label') or decl['field']} was read from OCR region {region}.")
    return ids


def _vision_nodes(b: _Builder, analysis: dict) -> list[str]:
    out = []
    for i, obs in enumerate(analysis.get("vision") or [], 1):
        if obs.get("status") != "OK":
            continue
        node_id = f"vision:{i}"
        out.append(b.add(Node(
            node_id, VISION_OBSERVATION, obs.get("product_label") or "Visual observation",
            status="UNVERIFIED_OBSERVATION",
            detail={k: v for k, v in (
                ("image_id", obs.get("image_id")), ("side", obs.get("side")),
                ("model", obs.get("model")), ("confidence", obs.get("confidence")),
                ("visual_observations", (obs.get("visual_observations") or [])[:4]),
                ("scrubbed", obs.get("scrubbed")),
            ) if v not in (None, "", [])},
            provenance=(VISION,),
            limitations=("A visual observation is weaker than OCR text and is never verified "
                         "evidence. It cannot state a standard, a declared value or a result.",),
        )))
    return out


def _product_node(b: _Builder, analysis: dict, decl_ids: dict[str, str], vision_ids: list[str]) -> str:
    product = analysis.get("product") or {}
    signals = product.get("signals") or {}
    matched = product.get("status") == "MATCHED"
    node_id = b.add(Node(
        "product", PRODUCT, product.get("name") or "Product not identified",
        status=product.get("status") or "REVIEW",
        detail={k: v for k, v in (
            ("identification_confidence", product.get("confidence")),
            ("method", product.get("method")), ("reason", product.get("reason")),
            ("ocr_supported", signals.get("ocr_supported")),
            ("vision_supported", signals.get("vision_supported")),
            ("knowledge_supported", signals.get("knowledge_supported")),
            ("ocr_and_vision_agree", signals.get("agreement")),
            ("conflicts", signals.get("conflicts")),
            ("visual_observation_status", product.get("vision_status")),
        ) if v not in (None, "", [])},
        provenance=(OCR_TEXT, DECLARATION_EXTRACTION) + ((VISION,) if signals.get("vision_supported") else ()),
        limitations=() if matched else
        ("Product identification is not settled, so nothing below is stated as applying to this item.",),
    ))
    for ev in (product.get("evidence") or [])[:8]:
        clue = ev.get("clue") or {}
        field_name = clue.get("declaration_field")
        if field_name and field_name in decl_ids:
            b.link(node_id, decl_ids[field_name], IDENTIFIED_FROM,
                   f"The product was identified from the declared {field_name} "
                   f"(“{clue.get('text')}”).")
        for region in (clue.get("source_regions") or []):
            b.link(node_id, f"ocr:{region}", IDENTIFIED_FROM,
                   f"OCR region {region} carries the product wording “{clue.get('text')}”.")
    for vid in vision_ids:
        b.link(node_id, vid, SUPPORTED_BY,
               "A visual observation of the photograph, weaker than OCR and never verified.")
    return node_id


def _standard_nodes(b: _Builder, analysis: dict, product_id: str) -> tuple[str | None, list[str]]:
    identified = (analysis.get("product") or {}).get("standard_number")
    ids: list[str] = []
    for cand in (analysis.get("standards") or [])[:MAX_STANDARDS]:
        number = cand.get("standard_number")
        if not number:
            continue
        is_identified = number == identified and (analysis.get("product") or {}).get("status") == "MATCHED"
        node_id = b.add(Node(
            f"std:{number}", STANDARD, number,
            status="IDENTIFIED" if is_identified else "CANDIDATE",
            detail={k: v for k, v in (
                ("title", cand.get("title")), ("retrieval_confidence", cand.get("confidence")),
                ("why_retrieved", (cand.get("why") or {}).get("summary")),
                ("printed_on_label", cand.get("printed_on_label")),
                ("verification_status", cand.get("verification_status")),
                ("document_name", cand.get("document_name")),
            ) if v not in (None, "", [])},
            provenance=(DETERMINISTIC_RETRIEVAL, BIS_KNOWLEDGE_BASE),
            source_url=cand.get("source_url"),
            limitations=("Retrieval confidence is the strength of a text match against verified BIS "
                         "records. It is not a legal determination that the standard applies.",),
        ))
        ids.append(node_id)
        b.link(product_id, node_id, MATCHED_TO,
               (cand.get("why") or {}).get("summary")
               or f"{number} was retrieved from the verified knowledge base for this product.")
        src = b.source({"title": f"{number} — {cand.get('title') or ''}".strip(" —"),
                        "source_url": cand.get("source_url"),
                        "document_name": cand.get("document_name"),
                        "verification_status": cand.get("verification_status"),
                        "last_verified": cand.get("last_verified")})
        if src:
            b.link(node_id, src, SOURCED_FROM, "The verified BIS record this standard was read from.")
    return (f"std:{identified}" if identified and f"std:{identified}" in b.nodes else None), ids


def _certification_node(b: _Builder, journey: dict | None, standard_id: str | None,
                        standard_number: str | None) -> str | None:
    if standard_id is None:
        return None
    scheme = (journey or {}).get("scheme") or {}
    verification = (journey or {}).get("verification_status")
    if not journey or verification == "INSUFFICIENT":
        node_id = b.add(Node(
            "cert", CERTIFICATION, "Certification route not available",
            status="NOT_AVAILABLE",
            detail={"reason": (journey or {}).get("message")
                    or f"MetrIQ holds no verified certification route information for {standard_number}.",
                    "verification_status": verification or "NOT_AVAILABLE"},
            provenance=(BIS_KNOWLEDGE_BASE,),
            limitations=("MetrIQ never infers a certification route. A route is shown only when "
                         "verified BIS records state it.",),
        ))
    else:
        node_id = b.add(Node(
            "cert", CERTIFICATION, scheme.get("name") or "Certification route",
            status=verification or "PARTIAL",
            detail={k: v for k, v in (
                ("scheme", scheme.get("name")), ("mark", scheme.get("mark")),
                ("conflict", scheme.get("conflict")),
                ("standard_selection", journey.get("standard_selection")),
                ("steps", [s.get("title") for s in (journey.get("steps") or [])]),
                ("next_steps", (journey.get("next_steps") or [])[:6]),
            ) if v not in (None, "", [])},
            provenance=(BIS_KNOWLEDGE_BASE,),
            limitations=tuple(journey.get("limitations") or ())
            + ("Certification guidance describes a published route for a product type. It is never a "
               "statement that this item, its manufacturer or any licence is certified.",),
        ))
        for src in (journey.get("sources") or [])[:6]:
            sid = b.source(src)
            if sid:
                b.link(node_id, sid, SOURCED_FROM, "The verified BIS record this guidance quotes.")
    b.link(standard_id, node_id, RELATED_TO,
           f"The certification route MetrIQ's verified records state for {standard_number}.")
    return node_id


def _requirement_nodes(b: _Builder, analysis: dict, standard_id: str | None,
                       product_id: str | None, requirements_and_items) -> None:
    """Standard -> verified requirement, straight from ``app.requirements`` knowledge.

    Pure knowledge, never a check outcome: MetrIQ produces no automatic
    PASS/FAIL/REVIEW verdict, so a requirement here only states that the
    standard (or, for a packaged commodity, the Legal Metrology rules) specifies
    it — never whether this item was found to satisfy it.
    """
    try:
        requirements, items_by_id = requirements_and_items()
    except Exception:  # noqa: BLE001 — knowledge lookup is best-effort here
        return

    standard_number = (analysis.get("product") or {}).get("standard_number")
    modelled_product_id = (analysis.get("product") or {}).get("modelled_product_id")

    def _requirement_node(req, authority: str) -> str:
        node_id = b.add(Node(
            f"req:{req.id}", REQUIREMENT, req.reference or req.description[:80],
            status="SPECIFIED",
            detail={k: v for k, v in (
                ("requirement", req.description), ("reference", req.reference),
                ("authority", authority), ("domain", req.domain),
                ("applies_to", req.applicability),
            ) if v},
            provenance=(LEGAL_METROLOGY_KNOWLEDGE if authority == "LEGAL_METROLOGY"
                        else BIS_KNOWLEDGE_BASE,),
        ))
        item = items_by_id.get(req.source_knowledge_id)
        if item is not None:
            src = b.source({"title": item.title, "source_url": item.source_url,
                            "document_name": item.document_name,
                            "verification_status": item.verification_status,
                            "last_verified": str(item.last_verified) if item.last_verified else None,
                            "source_authority": authority}, authority)
            if src:
                b.link(node_id, src, SOURCED_FROM, "The verified record this requirement is quoted from.")
        return node_id

    if standard_id and standard_number:
        for req in requirements.for_product(standard_number, modelled_product_id)[:MAX_REQUIREMENTS]:
            req_id = _requirement_node(req, req.source_category)
            b.link(standard_id, req_id, REQUIRES,
                   f"{standard_number} states this requirement, quoted from a verified record.")

    if product_id and analysis.get("inspection_type", "PACKAGE") != "HALLMARK":
        for req in requirements.for_package()[:MAX_REQUIREMENTS]:
            req_id = _requirement_node(req, req.source_category)
            b.link(product_id, req_id, REQUIRES,
                   "The Legal Metrology packaged-commodity rules apply to this package.")


def _laboratory_nodes(b: _Builder, labs: list[dict], standard_id: str | None,
                      standard_number: str | None) -> None:
    if standard_id is None:
        return
    for i, lab in enumerate(labs[:MAX_LABS], 1):
        node_id = b.add(Node(
            f"lab:{i}", LABORATORY, lab.get("lab_name") or "Laboratory",
            status=lab.get("validity_status") or "NOT_STATED",
            detail={k: v for k, v in (
                ("city", lab.get("city")), ("osl_code", lab.get("osl_code")),
                ("standard_as_listed", lab.get("standard_as_listed")),
                ("recognition_validity_as_at_snapshot", lab.get("validity_status")),
                ("validity_date_as_listed", lab.get("validity_date")),
                ("snapshot_retrieved_on", lab.get("retrieved_on")),
                ("why_listed", (lab.get("why") or {}).get("code") if isinstance(lab.get("why"), dict)
                 else lab.get("why")),
            ) if v},
            provenance=(LABORATORY_SNAPSHOT,), source_url=lab.get("source_url"),
            limitations=("Being listed in the BIS LIMS snapshot is the only relationship established. "
                         "MetrIQ does not establish accreditation, NABL status, current scope, current "
                         "validity, availability or contact details, and does not rank laboratories.",),
        ))
        b.link(standard_id, node_id, RELATED_TO,
               f"BIS LIMS listed this laboratory against {lab.get('standard_as_listed') or standard_number} "
               f"in the snapshot retrieved on {lab.get('retrieved_on') or 'the recorded date'}.")
        src = b.source({"title": lab.get("document_name"), "source_url": lab.get("source_url"),
                        "document_name": lab.get("document_name")})
        if src:
            b.link(node_id, src, SOURCED_FROM, "The BIS LIMS listing this record was ingested from.")


def _hallmark_nodes(b: _Builder, hallmark: dict) -> None:
    """Observations only. No node here can carry an authenticated state.

    Each hallmarking check (HALLMARK_HUID_OBSERVED, HALLMARK_PURITY_GRADE, …) is
    an OBSERVATION about the photograph, never a PASS/FAIL/REVIEW verdict, so it
    is folded straight into the observation node's own detail and sources —
    there is no separate RULE node or RESULTED_IN edge to a system result.
    """
    huid = hallmark.get("huid") or {}
    purity = hallmark.get("purity") or {}

    observation_checks = []
    check_sources: list[tuple[str, str, str]] = []
    for check in (hallmark.get("checks") or [])[:MAX_HALLMARK_CHECKS]:
        entry = {k: v for k, v in (
            ("rule_id", check.get("rule_id")), ("requirement", check.get("requirement")),
            ("result", check.get("result")), ("reason", check.get("reason")),
        ) if v}
        if entry:
            observation_checks.append(entry)
        src = b.source(check.get("source"))
        if src:
            check_sources.append((src, check.get("requirement") or "", check.get("reason") or ""))

    obs_id = b.add(Node(
        "hallmark", HALLMARK_OBSERVATION, "Hallmark evidence in the photograph",
        status=hallmark.get("verification_status") or "NOT_DETECTED",
        detail={k: v for k, v in (
            ("detected", hallmark.get("detected")),
            ("overall_status", hallmark.get("overall_status")),
            ("purity_status", purity.get("status")), ("metal", purity.get("metal")),
            ("caratage", purity.get("caratage")), ("fineness", purity.get("fineness")),
            ("components_observed", [{"component": c.get("label"), "status": c.get("status")}
                                     for c in (hallmark.get("components") or [])]),
            ("observation_checks", observation_checks),
            ("untrusted_claims_printed", len(hallmark.get("untrusted_claims") or [])),
            ("official_verification_required", hallmark.get("official_verification_required")),
        ) if v not in (None, "", [])},
        provenance=(HALLMARK_OBSERVATION_SOURCE, OCR_TEXT),
        limitations=("MetrIQ does not authenticate a hallmark, a HUID, a jeweller registration or an "
                     "Assaying and Hallmarking Centre. Official verification is required.",
                     "The BIS logo is a graphic; OCR reads text, so the logo can never be confirmed.",),
    ))
    for src, requirement, reason in check_sources:
        b.link(obs_id, src, SOURCED_FROM, f"{requirement or 'A verified hallmarking check'}"
               + (f": {reason}" if reason else "."))
    if huid.get("status") != "NOT_DETECTED":
        huid_id = b.add(Node(
            "huid", HUID_OBSERVATION, huid.get("value") or "HUID-like code observed",
            status=huid.get("status") or "UNCERTAIN",
            detail={k: v for k, v in (
                ("potential_value_observed", huid.get("value")), ("reason", huid.get("reason")),
                ("authenticity", "NOT_ESTABLISHED — external authoritative verification required"),
                ("user_provided_comparison", (hallmark.get("user_huid") or {}).get("status")),
            ) if v},
            provenance=(HALLMARK_OBSERVATION_SOURCE, OCR_TEXT),
            source_regions=tuple(r for c in (huid.get("candidates") or [])
                                 for r in (c.get("source_regions") or [])),
            limitations=("A HUID read from an image is an observation. MetrIQ never establishes that it "
                         "is genuine or that it belongs to this article.",
                         "A user-supplied HUID is compared as text only; agreement establishes nothing "
                         "about the article.",),
        ))
        b.link(obs_id, huid_id, OBSERVED_IN, "A HUID-like code was read in the hallmark evidence.")
        for region in (b.nodes[huid_id].source_regions or ()):
            b.link(huid_id, f"ocr:{region}", OBSERVED_IN, f"Read from OCR region {region}.")
    for src in (hallmark.get("sources") or [])[:4]:
        sid = b.source(src)
        if sid:
            b.link(obs_id, sid, SOURCED_FROM, "A verified BIS Hallmarking record.")


@lru_cache(maxsize=1)
def _requirements_and_items():
    """The verified requirement knowledge, loaded once. Pure knowledge lookup —
    no model, no retrieval, no rule execution."""
    from app.api import get_product_finder  # shared, already-loaded knowledge base

    items = get_product_finder().search_engine.items
    return load_requirements(items), {item.id: item for item in items}


def build_from_analysis(analysis: dict) -> EvidenceGraph:
    """Project a FINISHED analysis onto the graph. Nothing is recomputed."""
    b = _Builder()

    wanted: set[str] = set()
    for decl in (analysis.get("declaration_stage") or {}).get("fields", []):
        wanted.update(decl.get("source_regions") or [])
    for ev in ((analysis.get("product") or {}).get("evidence") or []):
        wanted.update((ev.get("clue") or {}).get("source_regions") or [])
    hallmark = analysis.get("hallmark") or {}
    for group in ("candidates",):
        for obs in ((hallmark.get("huid") or {}).get(group) or []) + \
                   ((hallmark.get("purity") or {}).get(group) or []):
            wanted.update(obs.get("source_regions") or [])
    for reason in ((analysis.get("escalation") or {}).get("reasons") or []):
        wanted.update(reason.get("source_regions") or [])

    _region_nodes(b, analysis, set(list(wanted)[:MAX_OCR]))
    decl_ids = _declaration_nodes(b, analysis)
    vision_ids = _vision_nodes(b, analysis)
    product_id = _product_node(b, analysis, decl_ids, vision_ids)
    standard_id, _ = _standard_nodes(b, analysis, product_id)
    standard_number = (analysis.get("product") or {}).get("standard_number")
    _certification_node(b, analysis.get("certification"), standard_id, standard_number)
    _requirement_nodes(b, analysis, standard_id, product_id, _requirements_and_items)
    _laboratory_nodes(b, analysis.get("laboratories") or [], standard_id, standard_number)
    if hallmark and (hallmark.get("detected") or analysis.get("inspection_type") == "HALLMARK"):
        _hallmark_nodes(b, hallmark)

    return EvidenceGraph(
        origin="INSPECTION", root_id=product_id, nodes=tuple(b.nodes.values()), edges=tuple(b.edges),
        inspection_id=analysis.get("inspection_id"),
        limitations=_graph_limitations(b),
    )


# ------------------------------------------------------- from a product context


_CONTEXT_NODE = {
    "PRODUCT": PRODUCT, "STANDARD": STANDARD, "CERTIFICATION": CERTIFICATION,
    "LABORATORY": LABORATORY, "HALLMARKING": HALLMARK_OBSERVATION,
}


def build_from_context(context: dict) -> EvidenceGraph:
    """Project a finished product context (the query path) onto the graph.

    The query path identifies no product: PRODUCT stays UNCERTAIN, because typed
    text is not evidence about a physical item. Only the sections the context
    itself carries become nodes.
    """
    b = _Builder()
    sections = {s.get("feature"): s for s in (context.get("sections") or [])}
    query = context.get("query") or ""

    product = sections.get("PRODUCT") or {}
    product_id = b.add(Node(
        "product", PRODUCT, context.get("product_name") or query or "Product not identified",
        status=context.get("product_status") or "NOT_IDENTIFIED",
        detail={k: v for k, v in (("described_as", query),
                                  ("availability", product.get("status")),
                                  ("headline", product.get("headline"))) if v},
        provenance=(USER_DESCRIPTION,),
        limitations=tuple(product.get("limitations") or ()),
    ))

    standard = sections.get("STANDARD") or {}
    standard_detail = standard.get("detail") or {}
    number = standard_detail.get("standard_number")
    standard_id = None
    if number:
        standard_id = b.add(Node(
            f"std:{number}", STANDARD, number, status="IDENTIFIED" if standard.get("status") == "AVAILABLE"
            else "CANDIDATE",
            detail={k: v for k, v in (("title", standard_detail.get("title")),
                                      ("retrieval_confidence", standard_detail.get("retrieval_confidence")),
                                      ("why_retrieved", standard_detail.get("why_retrieved"))) if v},
            provenance=(DETERMINISTIC_RETRIEVAL, BIS_KNOWLEDGE_BASE),
            source_url=(standard.get("sources") or [{}])[0].get("source_url"),
            limitations=tuple(standard.get("limitations") or ()),
        ))
        b.link(product_id, standard_id, MATCHED_TO,
               standard_detail.get("why_retrieved")
               or f"{number} was retrieved for the description you supplied.")
    else:
        for i, cand in enumerate((standard_detail.get("candidates") or [])[:MAX_STANDARDS], 1):
            cid = b.add(Node(
                f"std:{cand.get('standard_number') or i}", STANDARD, cand.get("standard_number") or "candidate",
                status="CANDIDATE",
                detail={k: v for k, v in (("title", cand.get("title")),
                                          ("retrieval_confidence", cand.get("confidence")),
                                          ("why_retrieved", cand.get("why_retrieved"))) if v},
                provenance=(DETERMINISTIC_RETRIEVAL, BIS_KNOWLEDGE_BASE),
                source_url=cand.get("source_url"),
                limitations=tuple(standard.get("limitations") or ()),
            ))
            b.link(product_id, cid, MATCHED_TO,
                   cand.get("why_retrieved") or "Retrieved as a candidate; none was established.")

    for feature, node_id, label in (("CERTIFICATION", "cert", "Certification route"),
                                    ("HALLMARKING", "hallmark", "Hallmark evidence")):
        section = sections.get(feature)
        if not section or section.get("status") == NOT_APPLICABLE_STATUS:
            continue
        created = b.add(Node(
            node_id, _CONTEXT_NODE[feature],
            (section.get("detail") or {}).get("scheme") or label,
            status=section.get("status") or "",
            detail={"headline": section.get("headline"), **(section.get("detail") or {})},
            provenance=tuple(section.get("provenance") or ()) or (BIS_KNOWLEDGE_BASE,),
            limitations=tuple(section.get("limitations") or ()),
        ))
        if standard_id:
            b.link(standard_id, created, RELATED_TO, section.get("headline") or "")
        else:
            b.link(product_id, created, RELATED_TO, section.get("headline") or "")
        for src in (section.get("sources") or [])[:6]:
            sid = b.source(src)
            if sid:
                b.link(created, sid, SOURCED_FROM, "A verified record this guidance quotes.")

    labs = ((sections.get("LABORATORY") or {}).get("detail") or {}).get("laboratories") or []
    lab_section = sections.get("LABORATORY") or {}
    for i, lab in enumerate(labs[:MAX_LABS], 1):
        lid = b.add(Node(
            f"lab:{i}", LABORATORY, lab.get("lab_name") or "Laboratory",
            status=lab.get("recognition_validity_as_at_snapshot") or "NOT_STATED",
            detail={k: v for k, v in lab.items() if v},
            provenance=(LABORATORY_SNAPSHOT,),
            limitations=tuple(lab_section.get("limitations") or ()),
        ))
        b.link(standard_id or product_id, lid, RELATED_TO,
               f"BIS LIMS listed this laboratory against {number or 'the standard'} in the snapshot.")

    return EvidenceGraph(
        origin="PRODUCT_CONTEXT", root_id=product_id, nodes=tuple(b.nodes.values()),
        edges=tuple(b.edges), query=query, inspection_id=context.get("inspection_id"),
        limitations=_graph_limitations(b),
    )


NOT_APPLICABLE_STATUS = "NOT_APPLICABLE"


def _graph_limitations(b: _Builder) -> tuple[str, ...]:
    out = [NOTE]
    for node in b.nodes.values():
        for item in node.limitations:
            if item not in out:
                out.append(item)
    return tuple(out)


# ------------------------------------------------------------------- output


class GraphNodeOut(BaseModel):
    id: str
    type: str = Field(description=" | ".join(NODE_TYPES))
    label: str
    status: str = Field(default="", description="The status the producing system recorded, verbatim.")
    layer: int = Field(description="0 evidence · 1 declarations · 2 product · 3 standard · "
                                   "4 certification/requirement/laboratory/hallmark · 5 source")
    detail: dict = Field(default_factory=dict, description="Only keys that exist. Never a placeholder.")
    provenance: list[str] = Field(default_factory=list, description="Which MetrIQ system produced this.")
    source_regions: list[str] = Field(default_factory=list)
    source_url: str | None = None
    limitations: list[str] = Field(default_factory=list)


class GraphEdgeOut(BaseModel):
    source: str
    target: str
    type: str = Field(description=" | ".join(EDGE_TYPES))
    explanation: str = Field(description="Why this relationship exists, from the evidence itself.")


class EvidenceGraphOut(BaseModel):
    """A read-only projection of relationships the deterministic pipeline recorded."""

    origin: str = Field(description='"INSPECTION" | "PRODUCT_CONTEXT"')
    inspection_id: str | None = None
    query: str = ""
    root_id: str
    node_count: int
    edge_count: int
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]
    limitations: list[str] = Field(default_factory=list)
    note: str = NOTE


def graph_out(graph: EvidenceGraph) -> EvidenceGraphOut:
    return EvidenceGraphOut(
        origin=graph.origin,
        inspection_id=graph.inspection_id,
        query=graph.query,
        root_id=graph.root_id,
        node_count=len(graph.nodes),
        edge_count=len(graph.edges),
        nodes=[GraphNodeOut(id=n.id, type=n.type, label=n.label, status=n.status, layer=n.layer,
                            detail=n.detail, provenance=list(n.provenance),
                            source_regions=list(n.source_regions), source_url=n.source_url,
                            limitations=list(n.limitations)) for n in graph.nodes],
        edges=[GraphEdgeOut(source=e.source, target=e.target, type=e.type, explanation=e.explanation)
               for e in graph.edges],
        limitations=list(graph.limitations),
    )
