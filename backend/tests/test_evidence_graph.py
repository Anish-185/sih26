"""Checks for Milestone 22 — the evidence graph.

The MetrIQ evidence graph visualizes relationships already established by the
deterministic evidence pipeline. It does not independently infer standards,
compliance, authenticity, laboratory validity, or certification applicability.
These checks hold it to that.

NO OpenRouter or LM Studio request is made: the OCR engine is stubbed, the
copilot provider is a stub, and everything else is the real deterministic code.

What is locked in:

  projection    every node and edge comes from the analysis it was given; the
                analysis is byte-for-byte unchanged and no result moves
  chain         product -> OCR / declaration / vision, product -> standard,
                standard -> requirement (verified knowledge, never a check)
  no verdict    MetrIQ produces no automatic PASS/FAIL/REVIEW compliance
                verdict, so the graph has no RULE or SYSTEM_RESULT node and no
                CHECKED_BY/RESULTED_IN edge
  provenance    every node names the system that produced it, and a source node
                exists only for a record stored with the evidence or MetrIQ's
                own verified knowledge base
  honesty       coverage limits, hallmark boundaries and snapshot wording all
                survive
  trust         the request whitelist admits no client-created node or edge
  deep links    ?q= and ?standard= still work; old saved analyses still project

Run:  cd backend && ./.venv/bin/python tests/test_evidence_graph.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import warnings  # noqa: E402

warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

from app import evidence_graph as eg  # noqa: E402
from app import product_context as pc  # noqa: E402
from app.api import (  # noqa: E402
    get_certification_journey_service,
    get_lab_registry,
    get_product_finder,
)
from app.copilot import CAPABILITIES, FEATURE_CAPABILITIES, build_context, build_feature_context  # noqa: E402
from app.copilot_api import get_copilot  # noqa: E402
from app.escalation import assess  # noqa: E402
from app.main import app  # noqa: E402
from test_copilot import (  # noqa: E402
    HALLMARK_ANALYSIS,
    WATER_ANALYSIS,
    StubProvider,
    reply,
)

PASS = 0
FAIL = 0
CLIENT = TestClient(app)
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}{' — ' + detail if detail else ''}")


def query_context(product: str = "", standard_number: str = "") -> dict:
    return pc.context_out(pc.build_from_query(
        product,
        finder=get_product_finder(),
        journey_service=get_certification_journey_service(),
        registry=get_lab_registry(),
        standard_number=standard_number,
    )).model_dump(mode="json")


WATER_GRAPH = eg.build_from_analysis(WATER_ANALYSIS)
HALLMARK_GRAPH = eg.build_from_analysis(HALLMARK_ANALYSIS)
KETTLE_CONTEXT = query_context("electric kettle")
KETTLE_GRAPH = eg.build_from_context(KETTLE_CONTEXT)


def edges(graph, type_=None, source=None, target=None):
    return [e for e in graph.edges
            if (type_ is None or e.type == type_)
            and (source is None or e.source == source)
            and (target is None or e.target == target)]


def blob(graph) -> str:
    return json.dumps(eg.graph_out(graph).model_dump(mode="json"))


_QUOTED = {"text", "quote", "raw_text", "observed_value", "potential_value_observed", "visual_observations"}


def written(graph) -> str:
    """Only the text MetrIQ writes itself: labels, statuses and edge explanations.

    Package text read by OCR and quotes copied from verified records are evidence
    MetrIQ must reproduce verbatim (a label really can print "HUID VERIFIED"), and
    a limitation is a denial by construction — neither is MetrIQ making a claim.
    """
    parts = []
    for node in graph.nodes:
        parts += [node.label, node.status]
        parts += [f"{k}={v}" for k, v in node.detail.items() if k not in _QUOTED]
    parts += [e.explanation for e in graph.edges]
    return " | ".join(str(p) for p in parts)


# ------------------------------------------------------- H/I  generation


def test_graph_generation() -> None:
    print("\nH/I. a graph is generated from a product context and from an inspection")
    check("H: a product context projects to a graph", KETTLE_GRAPH.origin == "PRODUCT_CONTEXT")
    check("I: a finished inspection projects to a graph", WATER_GRAPH.origin == "INSPECTION"
          and WATER_GRAPH.inspection_id == WATER_ANALYSIS["inspection_id"])
    for name, graph in (("inspection", WATER_GRAPH), ("context", KETTLE_GRAPH), ("hallmark", HALLMARK_GRAPH)):
        ids = [n.id for n in graph.nodes]
        check(f"{name}: node ids are unique", len(ids) == len(set(ids)))
        check(f"{name}: every node type is a declared type",
              all(n.type in eg.NODE_TYPES for n in graph.nodes))
        check(f"{name}: every edge type is a declared type",
              all(e.type in eg.EDGE_TYPES for e in graph.edges))
        check(f"{name}: no edge dangles", all(e.source in ids and e.target in ids for e in graph.edges))
        check(f"{name}: no self-edge", all(e.source != e.target for e in graph.edges))
        check(f"{name}: every edge explains itself", all(e.explanation for e in graph.edges))
        check(f"{name}: the root node exists", graph.root_id in ids)
        check(f"{name}: the graph states it decides nothing",
              "does not independently infer" in eg.graph_out(graph).note)

    # A projection changes nothing.
    before = json.dumps(WATER_ANALYSIS, sort_keys=True)
    eg.build_from_analysis(WATER_ANALYSIS)
    check("building a graph leaves the analysis byte-for-byte unchanged",
          json.dumps(WATER_ANALYSIS, sort_keys=True) == before)
    check("the graph is deterministic: the same analysis gives the same graph",
          blob(eg.build_from_analysis(WATER_ANALYSIS)) == blob(WATER_GRAPH))
    check("only this case's evidence is included — not the knowledge base or every laboratory",
          len(WATER_GRAPH.nodes) < 120 and len(WATER_GRAPH.of_type(eg.LABORATORY)) <= eg.MAX_LABS,
          str(len(WATER_GRAPH.nodes)))


# ------------------------------------------------------ J/K/L/M/N  the chain


def test_relationships() -> None:
    print("\nJ-L. the chain: OCR -> product -> standard -> requirement (knowledge, never a check)")
    product = WATER_GRAPH.of_type(eg.PRODUCT)[0]
    check("J: the product is linked to the OCR / declaration evidence it was identified from",
          bool(edges(WATER_GRAPH, eg.IDENTIFIED_FROM, source=product.id)))
    ocr_targets = [e.target for e in edges(WATER_GRAPH, eg.IDENTIFIED_FROM, source=product.id)]
    check("J: at least one of those is a real OCR region or declaration node",
          any(WATER_GRAPH.node(t).type in (eg.OCR_EVIDENCE, eg.DECLARATION) for t in ocr_targets))
    decl = next(n for n in WATER_GRAPH.of_type(eg.DECLARATION) if n.source_regions)
    check("J: a declaration is linked to the OCR region it was read from",
          bool(edges(WATER_GRAPH, eg.OBSERVED_IN, source=decl.id)))

    matched = edges(WATER_GRAPH, eg.MATCHED_TO, source=product.id)
    check("K: the product is matched to the verified standard", bool(matched))
    standard = WATER_GRAPH.node(matched[0].target)
    check("K: the standard node is IS 14543:2016 and is marked identified",
          standard.label == "IS 14543:2016" and standard.status == "IDENTIFIED", standard.label)
    check("K: the edge quotes the existing deterministic why-this-result",
          "Retrieved as a candidate" in matched[0].explanation, matched[0].explanation)

    requires = edges(WATER_GRAPH, eg.REQUIRES, source=standard.id)
    check("L: the standard requires at least one verified requirement", bool(requires))
    requirement = WATER_GRAPH.node(requires[0].target)
    check("L: the requirement quotes a verified record and names its authority",
          requirement.detail.get("requirement") and requirement.detail.get("authority") in ("BIS", "LEGAL_METROLOGY"))
    check("L: the requirement is knowledge, never a check outcome — its status is never PASS/FAIL/REVIEW",
          requirement.status not in ("PASS", "FAIL", "REVIEW", "NOT_SUPPORTED"))
    sourced = edges(WATER_GRAPH, eg.SOURCED_FROM, source=requirement.id)
    check("L: the requirement is sourced from a verified record",
          bool(sourced) and WATER_GRAPH.node(sourced[0].target).type == eg.SOURCE)
    check("there is no RULE or SYSTEM_RESULT node, and no CHECKED_BY or RESULTED_IN edge in the vocabulary",
          not {"RULE", "SYSTEM_RESULT"} & set(eg.NODE_TYPES)
          and not {"CHECKED_BY", "RESULTED_IN"} & set(eg.EDGE_TYPES))

    layers = {n.type: n.layer for n in WATER_GRAPH.nodes}
    check("the chain is ordered by layer, so a narrow screen reads it top-down",
          layers[eg.OCR_EVIDENCE] < layers[eg.DECLARATION] < layers[eg.PRODUCT]
          < layers[eg.STANDARD] < layers[eg.REQUIREMENT])


# ---------------------------------------------------------- O  provenance


def test_provenance() -> None:
    print("\nO. provenance and sources")
    for graph, name in ((WATER_GRAPH, "inspection"), (KETTLE_GRAPH, "context")):
        check(f"{name}: every node names the system that produced it",
              all(n.provenance for n in graph.nodes if n.type != eg.SOURCE), )
    standard = WATER_GRAPH.of_type(eg.STANDARD)[0]
    check("a standard is produced by deterministic retrieval over the verified knowledge base",
          set(standard.provenance) == {eg.DETERMINISTIC_RETRIEVAL, eg.BIS_KNOWLEDGE_BASE})
    sourced = edges(WATER_GRAPH, eg.SOURCED_FROM, source=standard.id)
    check("and it is sourced from a verified BIS record with its official URL", bool(sourced)
          and (WATER_GRAPH.node(sourced[0].target).source_url or "").startswith("http"))

    from app.knowledge.loader import load_knowledge_base

    stored_urls = {s.get("source_url") for c in WATER_ANALYSIS["standards"] for s in [c] if c.get("source_url")}
    # Requirement source URLs are read live from MetrIQ's own verified knowledge
    # base (they are knowledge, never a stored check result) — still traceable
    # to a verified record, just not duplicated into the analysis JSON.
    stored_urls |= {item.source_url for item in load_knowledge_base().items if item.source_url}
    for s in (WATER_ANALYSIS.get("certification") or {}).get("sources") or []:
        if s.get("source_url"):
            stored_urls.add(s["source_url"])
    for lab in WATER_ANALYSIS.get("laboratories") or []:
        if lab.get("source_url"):
            stored_urls.add(lab["source_url"])
    graph_urls = {n.source_url for n in WATER_GRAPH.nodes if n.source_url}
    check("every URL in the graph is one stored with the evidence — none is invented",
          graph_urls <= stored_urls, str(graph_urls - stored_urls))
    check("an OCR node keeps the region id, confidence and box it was read with",
          all({"text", "confidence", "image_id"} <= set(n.detail) for n in WATER_GRAPH.of_type(eg.OCR_EVIDENCE)))
    check("OCR evidence is labelled read, never verified",
          all(n.status == "READ" and "not verified" in " ".join(n.limitations)
              for n in WATER_GRAPH.of_type(eg.OCR_EVIDENCE)))


# ------------------------------------------------------------ T  laboratory


def test_laboratory_graph() -> None:
    print("\nT. the laboratory graph keeps the snapshot semantics")
    labs = WATER_GRAPH.of_type(eg.LABORATORY)
    check("laboratories are attached to the standard, never to the product",
          bool(labs) and all(edges(WATER_GRAPH, eg.RELATED_TO,
                                   source=WATER_GRAPH.of_type(eg.STANDARD)[0].id, target=lab.id)
                             for lab in labs))
    check("validity is only ever as at the snapshot",
          all(lab.status in ("VALID_AT_SNAPSHOT", "EXPIRED_AT_SNAPSHOT", "NOT_STATED") for lab in labs),
          str([lab.status for lab in labs]))
    text = written(WATER_GRAPH)
    for forbidden in ("CURRENTLY_VALID", "currently valid", "currently recognised", "NABL",
                      "accredited", "recommended", "best laboratory", "nearest", "suitable"):
        check(f"the graph never claims '{forbidden}'", forbidden.lower() not in text.lower())
    check("a laboratory node states what being listed does NOT establish",
          all("does not establish accreditation" in " ".join(lab.limitations) for lab in labs))
    check("the edge says the relationship is a BIS LIMS listing on a date",
          all("BIS LIMS listed" in e.explanation
              for lab in labs for e in edges(WATER_GRAPH, eg.RELATED_TO, target=lab.id)))
    check("no laboratory node carries an address, phone or e-mail",
          not any(k in lab.detail for lab in labs for k in ("address", "phone", "email")))
    check("the Group-1 / Group-2 PDFs are still disclosed as un-ingested",
          any("Group-1" in line for line in KETTLE_GRAPH.limitations))


# --------------------------------------------------- U/V/W  hallmarking safety


def test_hallmark_graph() -> None:
    print("\nU/V/W. hallmarking: observation only, never authentication")
    obs = HALLMARK_GRAPH.of_type(eg.HALLMARK_OBSERVATION)
    check("U: a hallmark inspection has a hallmark observation node", len(obs) == 1)
    check("U: its status is the M19 verification status, which has no verified state",
          obs[0].status in ("NOT_VERIFIED", "NOT_DETECTED"), obs[0].status)
    huid = HALLMARK_GRAPH.of_type(eg.HUID_OBSERVATION)
    check("V: a HUID-like code is an OBSERVATION node, never a verification",
          len(huid) == 1 and huid[0].type == eg.HUID_OBSERVATION)
    check("V: the HUID node states authenticity is not established",
          "NOT_ESTABLISHED" in str(huid[0].detail.get("authenticity")))
    check("V: there is no node type or status that could authenticate an item",
          not any(s in eg.NODE_TYPES for s in ("VERIFICATION", "AUTHENTICATION")))
    text = written(HALLMARK_GRAPH)
    for forbidden in ("HUID verified", "HUID authentic", "hallmark authentic", "is authentic",
                      "jeweller is registered", "AHC verified", "registration verified", "genuine"):
        check(f"U: the hallmark graph never claims '{forbidden}'", forbidden.lower() not in text.lower())
    printed = [n for n in HALLMARK_GRAPH.of_type(eg.OCR_EVIDENCE)
               if "VERIFIED" in str(n.detail.get("text", "")).upper()]
    check("U: a package that PRINTS 'HUID VERIFIED' keeps it as untrusted OCR evidence",
          bool(printed) and all(n.status == "READ" for n in printed))
    check("U: and the hallmark node counts it as an untrusted printed claim",
          (obs[0].detail.get("untrusted_claims_printed") or 0) >= 1)
    check("V: no node anywhere carries a positive authentication status",
          not any(n.status in ("VERIFIED", "AUTHENTIC", "GENUINE") for n in HALLMARK_GRAPH.nodes))
    obs_checks = obs[0].detail.get("observation_checks") or []
    authenticity = [c for c in obs_checks if "AUTHENTICITY" in (c.get("rule_id") or "")]
    check("V: the HUID authenticity check is permanently NOT_SUPPORTED",
          bool(authenticity) and all(c.get("result") == "NOT_SUPPORTED" for c in authenticity))
    check("W: an uncertain purity stays uncertain and is never resolved",
          obs[0].detail.get("purity_status") in ("DETECTED", "UNCERTAIN", "CONFLICT", "MULTIPLE",
                                                "NOT_DETECTED"),
          str(obs[0].detail.get("purity_status")))
    check("W: the BIS logo can never be confirmed by OCR, and the node says so",
          any("logo is a graphic" in limit for limit in obs[0].limitations))
    check("a package inspection gets no hallmark node at all",
          not WATER_GRAPH.of_type(eg.HALLMARK_OBSERVATION))
    check("and jewellery gets no package-label requirement from the graph",
          all(n.detail.get("authority") != "LEGAL_METROLOGY"
              for n in HALLMARK_GRAPH.of_type(eg.REQUIREMENT)))


# ---------------------------------------------------- X  certification route


def test_certification_graph() -> None:
    print("\nX. a certification route is quoted or absent — never inferred")
    cert = WATER_GRAPH.of_type(eg.CERTIFICATION)
    check("a standard with verified guidance gets a certification node", len(cert) == 1)
    check("it is reached from the standard, not from the product",
          bool(edges(WATER_GRAPH, eg.RELATED_TO, source=WATER_GRAPH.of_type(eg.STANDARD)[0].id,
                     target=cert[0].id)))
    check("the scheme is the one the verified records state",
          "Scheme" in (cert[0].detail.get("scheme") or ""), str(cert[0].detail.get("scheme")))
    check("and it never claims the item is certified",
          any("never a statement that this item" in limit for limit in cert[0].limitations))

    # No verified guidance -> an explicit NOT_AVAILABLE node.
    stripped = copy.deepcopy(WATER_ANALYSIS)
    stripped["certification"] = None
    absent = eg.build_from_analysis(stripped).of_type(eg.CERTIFICATION)
    check("X: no verified route produces a NOT_AVAILABLE node, not a guess",
          len(absent) == 1 and absent[0].status == "NOT_AVAILABLE"
          and "holds no verified certification route" in str(absent[0].detail))
    check("X: and it says MetrIQ never infers a route",
          any("never infers a certification route" in limit for limit in absent[0].limitations))
    insufficient = copy.deepcopy(WATER_ANALYSIS)
    insufficient["certification"] = {"verification_status": "INSUFFICIENT",
                                     "message": "Verified certification information is not currently available."}
    node = eg.build_from_analysis(insufficient).of_type(eg.CERTIFICATION)[0]
    check("X: an INSUFFICIENT journey is reported as such, with its own message",
          node.status == "NOT_AVAILABLE" and "not currently available" in str(node.detail))


# ------------------------------------------------- Y  the query path's product


def test_query_path_uncertainty() -> None:
    print("\nY. the query path identifies no product, and the graph says so")
    product = KETTLE_GRAPH.of_type(eg.PRODUCT)[0]
    check("Y: the product node is NOT_IDENTIFIED on the query path",
          product.status == "NOT_IDENTIFIED", product.status)
    check("Y: it is provenanced to the description the user typed",
          product.provenance == (eg.USER_DESCRIPTION,))
    check("Y: and it says a typed description is not evidence about a physical item",
          any("not evidence about a physical item" in limit for limit in product.limitations))
    check("Y: the query path still shows the verified standard that was retrieved",
          any(n.label == "IS 367:1993" for n in KETTLE_GRAPH.of_type(eg.STANDARD)))
    check("Y: there is no OCR or declaration node on the query path",
          not (KETTLE_GRAPH.of_type(eg.OCR_EVIDENCE) or KETTLE_GRAPH.of_type(eg.DECLARATION)))

    unknown = eg.build_from_context(query_context("purple flying saucer"))
    check("an unknown product produces a graph with no standard invented",
          not unknown.of_type(eg.STANDARD) and unknown.of_type(eg.PRODUCT)[0].status == "NOT_IDENTIFIED")


# -------------------------------------------- Z/AA  trust boundary + rejection


def test_client_payload_whitelist() -> None:
    print("\nZ/AA. the client cannot create a node, an edge or a status")
    body = {"analysis": WATER_ANALYSIS}
    ok = CLIENT.post("/evidence-graph", json=body)
    check("Z: a whitelisted analysis is accepted", ok.status_code == 200, ok.text[:200])
    data = ok.json()
    check("Z: the response is the same projection the module produces",
          data["node_count"] == len(WATER_GRAPH.nodes) and data["edge_count"] == len(WATER_GRAPH.edges))

    for field in ("nodes", "edges", "node", "graph", "system_result", "status"):
        r = CLIENT.post("/evidence-graph", json={**body, field: "x"})
        check(f"AA: an unexpected top-level field ({field}) is rejected", r.status_code == 422,
              str(r.status_code))
    smuggled = copy.deepcopy(WATER_ANALYSIS)
    smuggled["nodes"] = [{"id": "evil", "type": "STANDARD", "label": "IS 99999:9999", "status": "IDENTIFIED"}]
    smuggled["edges"] = [{"source": "evil", "target": "product", "type": "MATCHED_TO"}]
    r = CLIENT.post("/evidence-graph", json={"analysis": smuggled})
    got = r.json()
    check("Z: a node smuggled inside the analysis never reaches the graph",
          r.status_code == 200 and "evil" not in json.dumps(got), r.text[:200])
    check("Z: and the projected standard is still the deterministic retrieval result",
          any(n["type"] == "STANDARD" and n["status"] == "IDENTIFIED"
              and n["label"] == WATER_ANALYSIS["product"]["standard_number"] for n in got["nodes"]))

    check("AA: no evidence source at all -> 422",
          CLIENT.post("/evidence-graph", json={}).status_code == 422)
    check("AA: two evidence sources -> 422",
          CLIENT.post("/evidence-graph",
                      json={"analysis": WATER_ANALYSIS, "inspection_id": "INS-20260920-ABCDEF"}
                      ).status_code == 422)
    check("AA: a malformed inspection id -> 422",
          CLIENT.post("/evidence-graph", json={"inspection_id": "nope"}).status_code == 422)
    check("AA: a malformed analysis -> 422",
          CLIENT.post("/evidence-graph", json={"analysis": {"inspection_id": 5}}).status_code == 422)
    check("AA: a malformed product context -> 422",
          CLIENT.post("/evidence-graph", json={"product_context": {"origin": "QUERY"}}).status_code == 422)
    check("AA: junk body -> 422",
          CLIENT.post("/evidence-graph", content=b"{not json",
                      headers={"content-type": "application/json"}).status_code == 422)

    ctx = CLIENT.post("/evidence-graph", json={"product_context": KETTLE_CONTEXT})
    check("Z: a whitelisted product context is accepted and projected",
          ctx.status_code == 200 and ctx.json()["origin"] == "PRODUCT_CONTEXT", ctx.text[:200])


# --------------------------------------------------------- AB  the copilot


def test_copilot_receives_graph_evidence_only() -> None:
    print("\nAB. the copilot explains the graph from the graph's own evidence")
    check("the capability exists", "EXPLAIN_EVIDENCE_GRAPH" in CAPABILITIES)
    ctx = build_context(WATER_ANALYSIS, "EXPLAIN_EVIDENCE_GRAPH")
    check("the context carries the graph", "evidence_graph" in ctx)
    graph_ctx = ctx["evidence_graph"]
    check("with its nodes and its relationships", graph_ctx["nodes"] and graph_ctx["relationships"])
    check("it states the graph infers nothing", "infers nothing" in graph_ctx["what_this_is"])
    check("the graph in the context matches the deterministic projection",
          graph_ctx["node_count"] == len(WATER_GRAPH.nodes))
    check("every node sent is a node of the real graph",
          {n["id"] for n in graph_ctx["nodes"]} <= {n.id for n in WATER_GRAPH.nodes})
    check("the escalation state in the context is still MetrIQ's own evidence",
          ctx["escalation"]["resolvable_by_system"] == (not WATER_ANALYSIS["escalation"]["required"]))
    check("the prompt forbids deriving anything from the graph",
          "derive anything new from an EVIDENCE GRAPH" in __import__("app.copilot", fromlist=["x"]).SYSTEM_PROMPT)

    feature = build_feature_context("PRODUCT", KETTLE_CONTEXT)
    check("the product context page also sends a graph", "evidence_graph" in feature)
    check("and the graph capability is allowed there",
          "EXPLAIN_EVIDENCE_GRAPH" in FEATURE_CAPABILITIES["PRODUCT"])

    provider = StubProvider(reply("MetrIQ read the product name from OCR region OCR-002, matched "
                                  "IS 14543:2016 from its verified records, and applied the "
                                  "deterministic rules."))
    app.dependency_overrides[get_copilot] = lambda: __import__(
        "app.copilot", fromlist=["InspectionCopilot"]).InspectionCopilot(provider)
    try:
        r = CLIENT.post("/copilot/explain", json={"analysis": WATER_ANALYSIS,
                                                 "capability": "EXPLAIN_EVIDENCE_GRAPH"})
    finally:
        app.dependency_overrides.pop(get_copilot, None)
    body = r.json()
    check("AB: the endpoint answers a graph question", r.status_code == 200, r.text[:200])
    check("AB: the answer is not withheld and escalation is read from the record",
          body["withheld"] is False
          and body["escalation_required"] == WATER_ANALYSIS["escalation"]["required"])
    # The guard is deliberately strict, but MetrIQ's own vocabulary for its
    # knowledge base ("the verified record") is not an authentication claim.
    check("AB: an answer that says 'the verified record' is not withheld",
          body["withheld"] is False, body.get("withheld_reason", ""))
    liar = StubProvider(reply("The HUID is verified and the item is authentic."))
    app.dependency_overrides[get_copilot] = lambda: __import__(
        "app.copilot", fromlist=["InspectionCopilot"]).InspectionCopilot(liar)
    try:
        lied = CLIENT.post("/copilot/explain", json={"analysis": HALLMARK_ANALYSIS,
                                                    "capability": "EXPLAIN_EVIDENCE_GRAPH"}).json()
    finally:
        app.dependency_overrides.pop(get_copilot, None)
    check("AB: but an authentication claim about the item is still withheld",
          lied["withheld"] is True and lied["withheld_reason"] == "AUTHENTICATION_CLAIM",
          str(lied.get("withheld_reason")))

    sent = provider.calls[0]["user"]
    check("AB: the model was sent the graph relationships", "--MATCHED_TO-->" in sent)
    check("AB: no API key of any kind is in the prompt",
          "sk-" not in sent and "OPENROUTER" not in sent)


# ------------------------------------------- AC/AD  deep links, old records


def test_deep_links_and_old_records() -> None:
    print("\nAC/AD. deep links and analyses saved before this milestone")
    standards = (FRONTEND / "features" / "StandardsView.tsx").read_text()
    labs = (FRONTEND / "features" / "LaboratoriesView.tsx").read_text()
    cert = (FRONTEND / "features" / "CertificationView.tsx").read_text()
    check('AC: ?q= still drives the Standards page', 'params.get("q")' in standards)
    check('AC: ?standard= still drives Laboratories', 'params.get("standard")' in labs)
    check('AC: ?standard= still drives Certification', 'params.get("standard")' in cert)
    check("AC: the graph added no route of its own",
          "evidence-graph" not in (FRONTEND / "main.tsx").read_text())

    # AD: an analysis saved before M15/M16/M18/M21/M22 has none of those keys.
    old = copy.deepcopy(WATER_ANALYSIS)
    for key in ("vision", "certification", "laboratories", "product_context", "hallmark", "escalation"):
        old.pop(key, None)
    old_graph = eg.build_from_analysis(old)
    check("AD: an old saved analysis still projects to a graph", bool(old_graph.of_type(eg.PRODUCT)))
    check("AD: the missing features simply produce no node",
          not (old_graph.of_type(eg.LABORATORY) or old_graph.of_type(eg.VISION_OBSERVATION)))
    check("AD: an empty analysis does not raise", eg.build_from_analysis({}).of_type(eg.PRODUCT))
    check("AD: an empty context does not raise", eg.build_from_context({}).of_type(eg.PRODUCT))


# --------------------------------------------------- AE/AF  report, M21 intact


def test_report_and_product_context_unchanged() -> None:
    print("\nAE/AF. the report and the M21 product context are untouched")
    report = (Path(__file__).resolve().parents[1] / "app" / "report.py").read_text()
    check("AE: the report has no review workflow",
          "officer" not in report.lower() and "Final outcome" not in report)
    check("AE: the graph was not added to the PDF report",
          "evidence_graph" not in report and "EvidenceGraph" not in report)
    check("AE: the report renders MetrIQ's own evidence-established status, never a compliance verdict",
          "What MetrIQ could establish from the evidence" in report
          and "no automatic PASS/FAIL/REVIEW compliance verdict" in report)

    context = pc.build_from_analysis(WATER_ANALYSIS)
    check("AF: the M21 product context still composes every feature",
          [s.feature for s in context.sections] == list(pc.FEATURES))
    check("AF: and the graph did not change it",
          pc.context_out(context).model_dump(mode="json")["availability"]
          == WATER_ANALYSIS["product_context"]["availability"])
    check("AF: nothing downstream reads the graph",
          not any("evidence_graph" in (Path(__file__).resolve().parents[1] / "app" / f).read_text()
                  for f in ("escalation.py", "requirements.py",
                            "product_identification.py", "declarations.py", "product_context.py",
                            "report.py", "hallmark.py")))
    check("the graph module itself imports no pipeline stage",
          not any(f"from app.{m} import" in (Path(__file__).resolve().parents[1] / "app" / "evidence_graph.py").read_text()
                  for m in ("compliance", "declarations", "ocr", "llm", "openrouter", "vision",
                            "pipeline", "retrieval")))


# ---------------------------------------------------------------- UI shape


def test_frontend_graph_view() -> None:
    print("\nthe graph view is read-only and uses the existing visual language")
    view = (FRONTEND / "components" / "EvidenceGraph.tsx").read_text()
    check("the graph view exists", bool(view))
    check("it is read-only: no editing affordance",
          not any(w in view for w in ("onDrag", "contentEditable", "addNode", "deleteNode", "<input")))
    check("it renders the note that the graph decides nothing", "graph.note" in view)
    check("it offers focus and expand/collapse",
          "Focus on the path" in view and "setShowLimits" in view)
    check("a node click can highlight its OCR evidence on the photograph", "onSelectRegions" in view)
    check("no neon, gradient, glassmorphism or 3D",
          not any(w in view.lower() for w in ("gradient", "backdrop-blur", "neon", "rotate3d",
                                              "shadow-2xl", "purple")))
    check("it uses the existing palette tokens only",
          "bg-accent-soft" in view and "border-line" in view)
    section = (FRONTEND / "components" / "EvidenceGraphSection.tsx").read_text()
    check("a failed graph request never removes a result from the page",
          "unaffected" in section)
    # Phase 11: a standard's graph moved from the Standards page to its Passport,
    # the one canonical destination for a standard.
    check("the graph appears in the inspection workspace and on the Standard Passport (not the search page)",
          "EvidenceGraphSection" in (FRONTEND / "features" / "inspection" / "InspectionView.tsx").read_text()
          and "EvidenceGraphSection" in (FRONTEND / "features" / "StandardPassportView.tsx").read_text()
          and "EvidenceGraphSection" not in (FRONTEND / "features" / "StandardsView.tsx").read_text())


def main() -> int:
    test_graph_generation()
    test_relationships()
    test_provenance()
    test_laboratory_graph()
    test_hallmark_graph()
    test_certification_graph()
    test_query_path_uncertainty()
    test_client_payload_whitelist()
    test_copilot_receives_graph_evidence_only()
    test_deep_links_and_old_records()
    test_report_and_product_context_unchanged()
    test_frontend_graph_view()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
