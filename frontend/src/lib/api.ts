/*
  Typed client for the MetrIQ FastAPI backend.

  The backend is the source of truth. The frontend never re-implements retrieval,
  ranking, grounding or abstention logic — it renders exactly what the API
  returns, including when the API says an answer is unsupported.

  Contracts mirror backend/app/api.py:
    GET  /health
    POST /product-standard   (+ deterministic "why this result" per candidate)
    POST /certification-guidance
    POST /laboratory-search
    POST /ask                (grounded BIS Q&A — used by the Hallmarking view)
    POST /inspection/ocr     (Instant OCR — raw evidence only)
    POST /inspection/analyze (Smart Inspection — OCR + downstream pipeline)
    /inspections             (saved inspections; the backend computes every result)
    /evidence-graph          (relationships the deterministic pipeline already established)
    /copilot/status          (is the grounded explanation layer configured? — never a key)
    /copilot/explain         (an explanation of one finished inspection; it never changes a result)

  The OpenRouter API key lives ONLY on the backend. The browser talks to MetrIQ,
  MetrIQ talks to OpenRouter. There is deliberately no VITE_ variable for it.
*/

const API_BASE = (import.meta.env.VITE_API_BASE ?? "/api").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail || `Request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }

  /** True when the local language model was unreachable (backend returns 503). */
  get isModelUnavailable(): boolean {
    return this.status === 503;
  }
}

async function request<T>(
  path: string,
  init?: RequestInit,
  timeoutMs = 45_000,
): Promise<T> {
  let response: Response;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  // JSON by default; for FormData let the browser set the multipart boundary.
  const isForm = init?.body instanceof FormData;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: isForm ? undefined : { "content-type": "application/json" },
      signal: controller.signal,
      ...init,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError(408, "The request timed out. Please try again.");
    }
    throw new ApiError(0, "Cannot reach the MetrIQ backend. Is the API running?");
  } finally {
    clearTimeout(timer);
  }

  const text = await response.text();
  const body = text ? safeParse(text) : null;

  if (!response.ok) {
    const detail =
      (body && typeof body === "object" && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : null) ?? `Request failed (${response.status})`;
    throw new ApiError(response.status, detail);
  }

  return body as T;
}

function safeParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

/* ------------------------------------------------------------------ types --- */

export type Confidence = "high" | "medium" | "low" | "none";

export interface Reason {
  field: string;
  term: string;
  weight: number;
  detail: string;
}

export interface EvidenceSource {
  id: string;
  title: string;
  category: string;
  standard_number: string | null;
  score: number;
  confidence: string;
  matched_terms: string[];
  source_organization: string;
  source_url: string | null;
  document_name: string | null;
  reference: string | null;
  verification_status: string;
  last_verified: string | null;
}

export interface Health {
  status: string;
  service: string;
  version: string;
}

export interface WhyThisResult {
  standard_number: string;
  strength: string;
  signals: string[];
  summary: string;
  /** Phase 8: "CLAUSE" = MetrIQ holds OCR'd clause text; "IDENTITY" = number, title, listing only. */
  text_level?: "CLAUSE" | "IDENTITY";
  text_note?: string;
  /** The scope clause(s), verbatim. Absent on records saved before Phase 8. */
  scope?: ClauseEvidence[];
}

/** Phase 8: one clause, OCR text from the Public.Resource.Org / Internet Archive mirror. */
export interface ClauseEvidence {
  id: string;
  standard_number: string;
  clause: string;
  heading: string;
  text: string;
  note: string;
  /** As stored, e.g. "Clause 9, page 12 (PDF page 14)". */
  reference: string;
  source_url: string;
  pdf_page: number | null;
  /** MetrIQ's fixed label — shown wherever the text is. */
  ocr_label: string;
}

export interface ProductStandardResult {
  id: string;
  title: string;
  standard_number: string;
  score: number;
  confidence: string;
  matched_terms: string[];
  reasons: Reason[];
  why: WhyThisResult;
  /** Phase 4 — the real catalogue title and where its text came from. */
  catalogue: CatalogueIdentity | null;
  /** Phase 5 — absent on records saved before it. */
  currency?: EditionCurrency | null;
  qco?: QcoStatus | null;
  listing_orders?: ListingOrders | null;
  source_organization: string;
  source_url: string | null;
  document_name: string | null;
  reference: string | null;
  verification_status: string;
  last_verified: string | null;
}

export interface ProductStandardResponse {
  product: string;
  results: ProductStandardResult[];
  grounded: boolean;
  confidence: Confidence;
  note: string;
  /** Present only when MetrIQ abstained — see CoverageBoundary. */
  boundary: CoverageBoundary | null;
}

/**
 * Phase 4 — the standard's real catalogue identity and the route its text came
 * from. BIS SELLS these standards, so a title taken from the Public.Resource.Org
 * mirror is always labelled as such and never shown as a bis.gov.in publication.
 */
export interface CatalogueIdentity {
  title: string;
  source_route: "bis" | "archive";
  source_label: string;
  official: boolean;
  /** The source returned damaged text; it is shown as recorded, never repaired. */
  title_suspect: boolean;
}

/**
 * Phase 9 — Quality Control Order evidence for one standard, from quoted rows of
 * a BIS table only. UPCOMING never becomes "in force" by the passage of time;
 * every sentence is MetrIQ's own (app/qco.py) and is about the order, never the
 * user's item.
 */
export interface QcoRow {
  sr_no: string;
  ministry: string;
  product: string;
  standard_as_printed: string;
  enforcement_date: string;
  listed_products: string[];
  link: string | null;
  table: string;
  source_url: string;
  read_on: string | null;
}

/**
 * Phase 9.1 — the orders BIS's compulsory-certification listing NAMES for a
 * product (its Notification column). Evidence only: it never sets a status, and a
 * cell that also records a rescission / withdrawal / suspension / supersession is
 * quoted, not interpreted. Every sentence comes from the backend.
 */
export interface ListingOrder {
  number: string | null;
  date: string | null;
  text: string;
  url: string | null;
}

export interface ListingGroup {
  scheme: "I" | "II";
  products: string[];
  notification: string;
  orders: ListingOrder[];
  flags: ("RESCISSION" | "WITHDRAWAL" | "SUSPENSION" | "SUPERSESSION")[];
  source_url: string;
}

export interface ListingOrders {
  statements: string[];
  groups: ListingGroup[];
  read_on: string | null;
}

export interface QcoStatus {
  status: "IN_FORCE" | "UPCOMING" | "NOT_ESTABLISHED";
  label: string;
  statements: string[];
  rows: QcoRow[];
}

/**
 * Phase 5 — whether the edition MetrIQ cites is the newest one ITS EVIDENCE
 * shows. A statement about MetrIQ's evidence, never about BIS's catalogue.
 */
export interface EditionCurrency {
  status: "ACTIVE" | "REAFFIRMED" | "SUPERSEDED_BY" | "NOT_ESTABLISHED";
  label: string;
  statement: string;
  cited_edition: string | null;
  later_edition: string | null;
  reaffirmed_year: number | null;
  reaffirmation_quote: string | null;
  editions: string[];
  evidence: "BIS_CATALOGUE" | "ARCHIVE_MIRROR" | "ARCHIVE_DOCUMENT" | "NONE";
  official: boolean;
  source_label: string;
  source_url: string | null;
  checked_on: string | null;
  boundary: string;
}

/** Milestone 16 — one verified knowledge record, quoted word for word. */
export interface CertificationEvidence {
  knowledge_id: string;
  title: string;
  quote: string;
  source_organization: string;
  source_url: string | null;
  document_name: string | null;
  last_verified: string | null;
}

export interface CertificationStep {
  order: number;
  title: string;
  evidence: CertificationEvidence[];
}

export interface CertificationScheme {
  scheme: string;
  name: string;
  mark: string;
  basis: string[];
  evidence: CertificationEvidence[];
  conflict: string;
}

export interface CertificationCandidate {
  standard_number: string | null;
  title: string;
  knowledge_id: string;
  confidence: Confidence;
  score: number;
  source_url: string | null;
  why: WhyThisResult;
  currency?: EditionCurrency | null;
  qco?: QcoStatus | null;
  listing_orders?: ListingOrders | null;
}

/** The deterministic certification journey. Guidance about the route for a
 *  product type — never a statement that an item or manufacturer is certified. */
export interface CertificationJourney {
  query: string;
  product: string | null;
  standard_selection: "CONFIRMED" | "MULTIPLE_CANDIDATES" | "NOT_IDENTIFIED";
  standard_number: string | null;
  standard_title: string | null;
  currency?: EditionCurrency | null;
  qco?: QcoStatus | null;
  listing_orders?: ListingOrders | null;
  candidates: CertificationCandidate[];
  scheme: CertificationScheme | null;
  verification_status: "VERIFIED" | "PARTIAL" | "INSUFFICIENT";
  steps: CertificationStep[];
  next_steps: string[];
  why: string[];
  limitations: string[];
  sources: CertificationEvidence[];
  grounded: boolean;
  message: string;
  disclaimer: string;
}

export interface CertificationGuidanceResponse {
  question: string;
  product_context: string | null;
  answer: string;
  grounded: boolean;
  confidence: Confidence;
  source_count: number;
  sources: EvidenceSource[];
  note: string;
  journey: CertificationJourney | null;
  language: AnswerLanguage;
}

/** Milestone 18 — deterministic "Why this laboratory?" Never a quality claim. */
export interface LabWhy {
  signals: ("STANDARD_LISTED" | "PRODUCT_LISTED" | "NAME_MATCH" | "CITY_MATCH")[];
  summary: string;
}

/** One laboratory as BIS LIMS listed it. A null field is genuinely absent from
 *  the verified record and must be shown as unavailable, never filled in. */
export interface LaboratoryRecord {
  lab_name: string;
  osl_code: string | null;
  city: string | null;
  standard_as_listed: string;
  product_as_listed: string | null;
  grade_or_type: string | null;
  /** Recognition validity as at the snapshot — never "currently valid". */
  validity_date: string | null;
  validity_status: "VALID_AT_SNAPSHOT" | "EXPIRED_AT_SNAPSHOT" | "NOT_STATED";
  remark: string | null;
  source_url: string;
  source_organization: string;
  document_name: string;
  retrieved_on: string;
  why: LabWhy;
}

export interface LaboratoryCoverage {
  records: number;
  laboratories: number;
  standards: number;
  retrieved_on: string | null;
  note: string;
}

export interface LaboratorySearchResponse {
  query: string;
  standard_context: string | null;
  answer: string;
  grounded: boolean;
  confidence: Confidence;
  source_count: number;
  sources: EvidenceSource[];
  note: string;
  language: AnswerLanguage;
  laboratories: LaboratoryRecord[];
  laboratory_count: number;
  laboratory_standard: string | null;
  /** How the standard was established: given, named in the query, or via
   *  product -> standard retrieval. Null when no standard was established. */
  laboratory_standard_source: "standard" | "query" | "product" | "text" | null;
  other_editions: string[];
  coverage: LaboratoryCoverage | null;
  no_match_note: string | null;
}

/** One laboratory BIS LIMS lists for an inspection's standard (a dated snapshot). */
export interface InspectionLaboratory {
  lab_name: string;
  osl_code: string | null;
  city: string | null;
  standard_as_listed: string;
  validity_date: string | null;
  validity_status: string;
  source_url: string;
  document_name: string;
  retrieved_on: string;
  why: string;
}

/* ------------------------------------- Milestone 21: product context --- */

/**
 * MetrIQ's canonical product context: the evidence its deterministic features
 * already produced, connected. It creates no evidence and verifies nothing
 * externally. `origin: "QUERY"` is server-derived from a typed description;
 * `origin: "INSPECTION"` is composed from a finished analysis.
 */
export type ContextAvailability = "AVAILABLE" | "NOT_AVAILABLE" | "NOT_APPLICABLE" | "UNCERTAIN";

export type ContextFeature =
  | "PRODUCT"
  | "STANDARD"
  | "CERTIFICATION"
  | "INSPECTION"
  | "LABORATORY"
  | "HALLMARKING";

export interface ContextSection {
  feature: ContextFeature;
  status: ContextAvailability;
  headline: string;
  reason_code: string;
  detail: Record<string, unknown>;
  provenance: string[]; // which MetrIQ system produced it
  sources: {
    title: string | null;
    source_url: string | null;
    document_name: string | null;
    authority: string;
    reference: string | null;
  }[];
  limitations: string[];
}

export interface ProductContext {
  origin: "QUERY" | "INSPECTION";
  query: string;
  inspection_id: string | null;
  product_name: string | null;
  product_status: string;
  availability: Record<string, ContextAvailability>;
  sections: ContextSection[];
  conflicts: string[]; // recorded disagreements and agreements — never resolved here
  summary: string[]; // deterministic, written from structured data only
  limitations: string[];
  note: string;
}

/** Milestone 17 — assistant languages. "auto" detects from the query text. */
export type AnswerLanguage = "en" | "hi" | "te";
export type LanguageChoice = "auto" | AnswerLanguage;

/* ------------------------------------------- coverage boundary (Phase 3) --- */

/** A record reached by a partial word match only — evidence, never an answer. */
export interface WeakMatch {
  standard_number: string | null;
  title: string;
  confidence: string;
  matched_terms: string[];
  source_url: string | null;
}

/**
 * MetrIQ's own explanation of why it did not answer, written by backend code in
 * the user's language. It never claims that no Indian Standard exists for the
 * product — only that MetrIQ's verified data did not match one.
 */
export interface CoverageBoundary {
  language: string;
  heading: string;
  lines: string[];
  next_step: string;
  next_step_url: string;
  weak_heading: string;
  weak_note: string;
  weak_matches: WeakMatch[];
}

export interface AskResponse {
  question: string;
  answer: string;
  grounded: boolean;
  source_count: number;
  sources: EvidenceSource[];
  /** The language the answer is written in — never "auto". */
  language: AnswerLanguage;
  /** Canonical English terms the query's non-English wording mapped to. */
  matched_concepts: string[];
  /**
   * False when the explanation provider was unreachable and the answer is the
   * retrieved records rendered by MetrIQ's own code. The evidence and
   * the sources are unchanged; only the prose differs.
   */
  explained: boolean;
  /** Present only when MetrIQ abstained. */
  boundary: CoverageBoundary | null;
  /** Phase 6: what this answer resolved; null on abstention or no confident product. */
  context: ConversationContext | null;
  /** Phase 6: the product this question inherited from the previous one. */
  inherited: string | null;
  /** Phase 8: clause text attached to a confident answer; empty otherwise. */
  clauses: ClauseEvidence[];
  /** Phase 8: which path produced `answer` — MODEL, ABSTAINED, PROVIDER_ERROR, GUARD:<rule> … */
  fallback_reason: string;
}

/** Phase 6: entities an /ask answer resolved, derived by MetrIQ — never a model. */
export interface ConversationContext {
  product: string;
  /** Exactly as stored, edition year included. Several are never narrowed to one. */
  standard_numbers: string[];
  category: string;
}

/* ---- inspection: IMAGE -> OCR (/inspection/ocr) -> pipeline (/analyze) --- */

/** Package sides a photo can show. UNKNOWN when the user did not say. */
export const PACKAGE_SIDES = ["FRONT", "BACK", "LEFT", "RIGHT", "TOP", "BOTTOM", "UNKNOWN"] as const;
export type PackageSide = (typeof PACKAGE_SIDES)[number];

/** One photo to upload for a package inspection. */
export interface PackageUploadInput {
  file: File;
  side: PackageSide;
}

export interface OcrRegion {
  id: string; // unique within one inspection (OCR-001, or I2-OCR-001 for image 2)
  image_id: string; // the image this region was read from
  side: PackageSide; // the package side of that image
  text: string;
  confidence: number; // 0–1
  bbox: [number, number, number, number]; // [x1,y1,x2,y2] in source pixels
  polygon: number[][]; // [[x,y] x4]
}

/**
 * One declaration field read off the label, with its OCR evidence.
 * NOT_DETECTED only means the OCR text did not contain it — never "legally missing".
 */
export type DeclarationStatus = "DETECTED" | "UNCERTAIN" | "NOT_DETECTED";

export interface Declaration {
  field: string;
  label: string;
  status: DeclarationStatus;
  value: string | null;
  unit: string | null;
  numeric_value: number | null;
  raw_text: string; // OCR text of the source regions, verbatim
  source_regions: string[]; // OCR region ids
  source_region_id: string | null; // first source region
  bbox: [number, number, number, number] | null; // union of the source boxes
  image_id: string | null;
  ocr_confidence: number | null; // how sure OCR was reading the text — not correctness
  method: "regex" | "keyword" | "heuristic";
  extraction_method: "deterministic" | "deterministic_normalization"; // normalized = recovered from corrupted OCR; raw_text keeps the original
  note: string;
  reason: string; // why UNCERTAIN / NOT_DETECTED
  source_images: string[]; // every image the value was read from
  source_sides: PackageSide[]; // package sides of those images
  consistency: "SINGLE" | "DUPLICATE" | "CONFLICT" | ""; // "" when not detected
  observations: DeclarationObservation[]; // every reading, when read more than once
}

/** One reading of a declaration field on the package. */
export interface DeclarationObservation {
  value: string | null;
  source_regions: string[];
  source_images: string[];
  source_sides: PackageSide[];
  ocr_confidence: number;
}

export interface DeclarationStage {
  status: "COMPLETED" | "PARTIAL" | "REVIEW" | "NO_RELIABLE_TEXT";
  fields: Declaration[]; // every searched field exactly once
  principal_display_panel: boolean;
  notes: string[];
}

/** One piece of package text used to identify the product. */
export interface ProductClue {
  kind:
    | "product_name"
    | "product_description"
    | "brand"
    | "standard_number"
    | "ocr_text"
    | "model_hint";
  text: string; // exactly as OCR / declarations read it
  search_text: string; // what was searched when OCR ran words together ("" if same)
  declaration_field: string | null;
  declaration_status: string | null;
  source_regions: string[]; // OCR region ids
  image_id: string | null;
  ocr_confidence: number | null;
}

/** Why one package clue supports one knowledge-base standard. */
export interface ProductEvidence {
  clue: ProductClue;
  match: "product" | "alias" | "category" | "standard_number";
  matched_phrase: string;
  retrieval_confidence: string;
  retrieval_score: number;
}

/** Product identification — retrieval over the verified BIS knowledge base, not compliance. */
/**
 * What a photo APPEARS to show, from an AI vision model. Deliberately weaker than
 * OCR: it never carries a declared or legal value (the backend deletes any the
 * model writes), never names a standard and never decides compliance.
 */
export interface VisionObservation {
  image_id: string;
  side: PackageSide;
  status: "OK" | "UNAVAILABLE";
  model: string;
  evidence_type: string; // AI_VISUAL_OBSERVATION
  product_candidate: string;
  product_label: string;
  product_category: string;
  confidence: number; // the model's own confidence — not retrieval confidence
  visual_features: string[];
  packaging_type: string;
  visual_observations: string[];
  limitations: string[];
  scrubbed: boolean; // the model wrote a legal value; MetrIQ removed it
  reason_code: string;
  reason: string; // why it is UNAVAILABLE
}

/** Which evidence sources supported the identified product (deterministic). */
export interface FusionSignals {
  ocr_supported: boolean;
  vision_supported: boolean;
  knowledge_supported: boolean;
  agreement: boolean;
  conflicts: string[];
}

export interface ProductIdentification {
  status: "MATCHED" | "REVIEW";
  name: string | null; // BIS product description from the knowledge base
  knowledge_id: string | null;
  standard_number: string | null;
  confidence: string; // retrieval confidence: high | medium | low | none
  method: "deterministic" | "model_assisted" | "vision_assisted";
  reason: string;
  evidence: ProductEvidence[];
  signals: FusionSignals;
  vision_status: "OK" | "UNAVAILABLE" | "NOT_RUN";
  unverified_standard_numbers: string[];
  /** Which of MetrIQ's modelled requirement-data products this package is, under the
   *  identified standard — a pure requirements-lookup, never a rule verdict. */
  product_applicability:
    | "PRODUCT_CONFIRMED"
    | "PRODUCT_NOT_MODELLED"
    | "PRODUCT_NOT_CONFIRMED"
    | "PRODUCT_AMBIGUOUS"
    | null;
  modelled_product_id: string | null;
  modelled_product_category: string | null;
  notes: string[];
}

/** A verified knowledge-base standard supported by the package evidence. */
export interface StandardCandidate extends ProductStandardResult {
  product: string;
  tier: "product" | "alias" | "category" | "standard_number";
  printed_on_label: boolean;
  evidence: ProductEvidence[];
}

/** Declaration completeness: what the photos show — never "legally missing". */
export interface CompletenessItem {
  field: string;
  label: string;
  status: "DETECTED" | "UNCERTAIN" | "NOT_DETECTED"; // OCR evidence only
  conflict: boolean;
  value: string | null;
  statement: string;
  requirement_coverage: "VERIFIED_REQUIREMENT" | "NOT_ESTABLISHED";
  requirement_ids: string[];
  source_sides: PackageSide[];
  source_images: string[];
  source_regions: string[];
  raw_text: string;
  ocr_confidence: number | null;
}

export interface DeclarationCompleteness {
  standard_number: string | null;
  items: CompletenessItem[];
  detected: number;
  uncertain: number;
  not_detected: number;
  conflicts: number;
  with_verified_requirement: number;
  unreadable_images: string[];
  note: string;
}

export interface PipelineStages {
  ocr: string;
  declaration_extraction: string;
  product_identification: string;
  standard_retrieval: string;
  hallmark: string;
}

export interface InspectionImage {
  image_id: string; // content hash — same image, same id
  filename: string;
  format: string;
  width: number;
  height: number;
  bytes: number;
}

export interface ImageQuality {
  blur_score: number;
  brightness: number;
  contrast: number;
  is_low_quality: boolean;
  notes: string[];
}

export interface OcrResult {
  engine: string;
  text: string;
  region_count: number;
  mean_confidence: number;
  duration_ms: number;
  regions: OcrRegion[];
}

/** One photo of the package and its own OCR evidence. */
export interface PackageImage {
  image_id: string;
  index: number; // 1-based upload order
  side: PackageSide;
  filename: string;
  status: "COMPLETED" | "NO_RELIABLE_TEXT" | "NO_TEXT" | "FAILED";
  error: string | null;
  format: string | null;
  width: number | null;
  height: number | null;
  bytes: number;
  quality: ImageQuality | null;
  ocr: OcrResult | null; // null when OCR failed
  notes: string[];
}

/** What the photos cover. Not uploaded / failed / no text are different states. */
export interface PackageCoverage {
  image_count: number;
  usable_images: number;
  sides_uploaded: PackageSide[];
  sides_not_uploaded: PackageSide[];
  images_failed: string[];
  images_no_text: string[];
  images_no_reliable_text: string[];
}

/** Instant OCR — raw OCR evidence plus the declarations read from it. */
export interface InstantOcr {
  status: "COMPLETED" | "NO_TEXT";
  inspection_id: string;
  created_at: string;
  image: InspectionImage; // first readable image
  quality: ImageQuality; // of the first readable image
  ocr: OcrResult; // every image's regions combined
  images: PackageImage[];
  package: PackageCoverage;
  declaration_stage: DeclarationStage;
  notes: string[];
}

/* ---------------------------------------------- hallmark evidence --- */

/** Hallmark evidence read by OCR — untrusted text, linked to its region. Never an authentication. */
export interface HallmarkObservation {
  kind: "HUID" | "PURITY" | "BIS_TEXT" | "HALLMARK_TEXT" | "UNTRUSTED_CLAIM";
  value: string | null;
  raw_text: string;
  source_regions: string[];
  image_id: string | null;
  side: PackageSide | null;
  bbox: [number, number, number, number] | null;
  ocr_confidence: number;
  method: string;
  status: "DETECTED" | "UNCERTAIN";
  note: string;
}

export interface HallmarkSource {
  knowledge_id: string;
  title: string;
  quote: string;
  source_url: string | null;
  document_name: string | null;
  last_verified: string | null;
}

export interface HallmarkCheck {
  rule_id: string;
  requirement: string;
  result: "PASS" | "REVIEW" | "NOT_SUPPORTED"; // never FAIL, never "verified"
  reason_code: string;
  reason: string;
  observed_value: string | null;
  source_regions: string[];
  source: HallmarkSource | null;
}

/** One of the three marks BIS says a hallmark consists of, as OBSERVED in the
 *  photograph. NOT_DETECTED means this photo did not show it — never that the
 *  article lacks it. */
export interface HallmarkComponent {
  component: "BIS_MARK" | "PURITY" | "HUID";
  label: string;
  status: "DETECTED" | "NOT_DETECTED" | "UNCERTAIN" | "NOT_SUPPORTED";
  observed_value: string | null;
  why: string;
  source_regions: string[];
  source: HallmarkSource | null;
}

/** The existing Milestone 15 visual observation, reused. It can only say whether
 *  the photo looks like a precious-metal article — never read a mark. */
export interface HallmarkVisionSupport {
  status: "SUPPORTS" | "DOES_NOT_SUPPORT" | "INCONCLUSIVE" | "UNAVAILABLE" | "NOT_RUN";
  labels: string[];
  model: string;
  /** Set when OCR and vision disagree. MetrIQ picks neither. */
  conflict: string;
  note: string;
}

/** A HUID the user typed. Compared as text; never verified. */
export interface UserHuid {
  value: string;
  normalized: string;
  status:
    | "MATCHES_OCR_TEXT"
    | "DIFFERS_FROM_OCR_TEXT"
    | "NO_OCR_VALUE_TO_COMPARE"
    | "MALFORMED";
  compared_with: string | null;
  note: string;
  provenance: "USER_PROVIDED";
}

export interface OfficialVerification {
  available: boolean;
  /** Always false. */
  performed_by_metriq: boolean;
  guidance: string;
  sources: HallmarkSource[];
}

export interface HallmarkEvidence {
  detected: boolean;
  verification_status: "NOT_VERIFIED" | "NOT_DETECTED"; // there is no VERIFIED state
  verification_note: string;
  /** Always "REVIEW": authenticity cannot be established from an image. Never FAIL. */
  overall_status: "REVIEW";
  reason_code: string;
  reason: string;
  huid: {
    status: "DETECTED" | "UNCERTAIN" | "MULTIPLE" | "NOT_DETECTED";
    value: string | null; // the potential HUID as read, only when exactly one clear candidate exists
    candidates: HallmarkObservation[];
    reason: string;
  };
  purity: {
    status: "DETECTED" | "UNCERTAIN" | "CONFLICT" | "NOT_DETECTED";
    metal: "GOLD" | "SILVER" | null;
    caratage: string | null;
    fineness: string | null;
    permitted_grade: boolean | null;
    candidates: HallmarkObservation[];
    reason: string;
  };
  bis_text: HallmarkObservation[];
  hallmark_text: HallmarkObservation[];
  untrusted_claims: HallmarkObservation[];
  checks: HallmarkCheck[];
  /* ---- Milestone 19: observation only, never verification ---- */
  /** What the observation pass found. There is deliberately no AUTHENTIC state. */
  outcome: "OBSERVATIONS_FOUND" | "NO_OBSERVATIONS" | "UNCERTAIN";
  /** Always true — MetrIQ has no authoritative verification channel. */
  official_verification_required: boolean;
  components: HallmarkComponent[];
  vision: HallmarkVisionSupport | null;
  user_huid: UserHuid | null;
  official_verification: OfficialVerification | null;
  /** Deterministic reasons. Never model-written. */
  why: string[];
  sources: HallmarkSource[];
}

export type InspectionType = "PACKAGE" | "HALLMARK";

/** One reason the automated system could not resolve an inspection by itself. */
export interface EscalationReason {
  code: string; // e.g. PRODUCT_NOT_IDENTIFIED, CONFLICTING_DECLARATIONS
  label: string;
  source: "OCR" | "PRODUCT" | "HALLMARKING" | "PIPELINE";
  message: string;
  source_regions: string[];
  checks: string[];
}

/** Could MetrIQ establish this inspection's evidence chain from the photos?
 *  Deterministic; never a legal or compliance judgment, and it decides nothing else. */
export interface Escalation {
  required: boolean; // true -> MetrIQ could not establish everything from the photos
  reasons: EscalationReason[];
}

export interface InspectionAnalysis {
  inspection_id: string;
  created_at: string;
  /** Visual observations of the photos — AI observations, never verified evidence. */
  vision?: VisionObservation[];
  image: InspectionImage;
  quality: ImageQuality;
  ocr: OcrResult;
  images: PackageImage[];
  package: PackageCoverage;
  declaration_stage: DeclarationStage;
  product: ProductIdentification;
  standards: StandardCandidate[]; // ranked, verified knowledge-base records only
  retrieval_note: string;
  completeness: DeclarationCompleteness;
  pipeline: PipelineStages;
  notes: string[];
  escalation: Escalation | null; // null only for inspections saved before escalation existed
  inspection_type: InspectionType;
  hallmark: HallmarkEvidence | null; // observed hallmark / HUID evidence — never an authentication
  /** Milestone 16 — certification route for the identified standard. Guidance
   *  only: never a statement that this item or its manufacturer is certified. */
  certification?: CertificationJourney | null;
  /** Milestone 18 — laboratories BIS LIMS lists for the identified standard.
      INFORMATIONAL: it never affected the result, and no listed laboratory
      tested this item. Absent on inspections saved before that milestone. */
  laboratories?: InspectionLaboratory[];
  /** Milestone 21 — the canonical product context composed from this analysis.
      Absent on inspections saved before that milestone. */
  product_context?: ProductContext | null;
}

/* ------------------------------------------------ saved inspections --- */

/** One saved inspection in a list. `escalation_required` is fixed when the inspection is saved. */
export interface InspectionSummary {
  inspection_id: string;
  created_at: string;
  product_status: string;
  product_name: string | null;
  product_category: string | null;
  standard_number: string | null;
  escalation_required: boolean;
  escalation_reasons: EscalationReason[];
  image_count: number;
  sides: PackageSide[];
}

export interface InspectionRecord extends InspectionSummary {
  images: { index: number; image_id: string; side: PackageSide; filename: string; content_type: string; url: string }[];
  analysis: InspectionAnalysis; // the saved deterministic analysis and its evidence
}

export interface InspectionStats {
  total: number;
  escalated: number; // the deterministic system could not establish the evidence chain from the photos
  resolved: number; // the deterministic system fully established the evidence chain from the photos
}



/* ------------------------------------------------ evidence graph (M22) --- */

/**
 * Milestone 22. A READ-ONLY projection of relationships MetrIQ's deterministic
 * pipeline already established. The graph infers nothing: a node or an edge
 * exists only because a MetrIQ system recorded it.
 */
export type GraphNodeType =
  | "PRODUCT"
  | "OCR_EVIDENCE"
  | "DECLARATION"
  | "VISION_OBSERVATION"
  | "STANDARD"
  | "CERTIFICATION"
  | "REQUIREMENT"
  | "LABORATORY"
  | "HALLMARK_OBSERVATION"
  | "HUID_OBSERVATION"
  | "SOURCE";

export type GraphEdgeType =
  | "IDENTIFIED_FROM"
  | "SUPPORTED_BY"
  | "MATCHED_TO"
  | "EXPLAINS"
  | "REQUIRES"
  | "SOURCED_FROM"
  | "RELATED_TO"
  | "OBSERVED_IN";

export interface GraphNode {
  id: string;
  type: GraphNodeType;
  label: string;
  status: string; // the status the producing system recorded, verbatim
  layer: number; // 0 evidence → 5 source
  detail: Record<string, unknown>;
  provenance: string[];
  source_regions: string[];
  source_url: string | null;
  limitations: string[];
}

export interface GraphEdge {
  source: string;
  target: string;
  type: GraphEdgeType;
  explanation: string;
}

export interface EvidenceGraph {
  origin: "INSPECTION" | "PRODUCT_CONTEXT";
  inspection_id: string | null;
  query: string;
  root_id: string;
  node_count: number;
  edge_count: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
  limitations: string[];
  note: string;
}

/** Exactly one evidence source — the request carries no node, edge or status. */
export type EvidenceGraphInput =
  | { inspection_id: string }
  | { analysis: InspectionAnalysis }
  | { product_context: ProductContext };

/* ------------------------------------------- inspection coverage (read-only) --- */

/**
 * What MetrIQ can do with a standard, derived from the verified data:
 *   INSPECTION_SUPPORTED — it also has image-checkable requirements and rules
 *   STANDARD_ONLY        — identified and explained from official evidence, no image rule
 *   UNSUPPORTED          — outside package-label inspection (e.g. jewellery hallmarking)
 * Retrieval and explanation work for all three; only the inspection engine differs.
 */
export type CoverageStatus = "INSPECTION_SUPPORTED" | "STANDARD_ONLY" | "UNSUPPORTED";

export interface StandardCoverage {
  standard_number: string;
  title: string;
  coverage_status: CoverageStatus;
  reason: string;
  certification_route: string | null;
  verified_requirements: number;
  deterministic_rules: number;
}

export interface CoverageMatrix {
  standards: StandardCoverage[];
  errors: string[];
}

/* ------------------------------------------------- MetrIQ Copilot (grounded) --- */

/**
 * The optional explanation layer. It reads a finished inspection and puts it into
 * words; it cannot retrieve, decide or change anything. MetrIQ produces no
 * automatic compliance verdict, so there is none for the model to report —
 * `escalation_required` below is always MetrIQ's own evidence, never the model's.
 */
export type CopilotCapability =
  | "EXPLAIN_INSPECTION"
  | "SUMMARIZE"
  | "EXPLAIN_ESCALATION"
  | "EXPLAIN_EVIDENCE"
  | "EXPLAIN_UNCERTAINTY"
  | "EXPLAIN_HALLMARK"
  | "EXPLAIN_CERTIFICATION"
  | "EXPLAIN_RESULT"
  | "WHAT_IS_MISSING"
  | "EXPLAIN_STANDARD"
  | "EXPLAIN_LABORATORY"
  | "EXPLAIN_PRODUCT_CONTEXT"
  | "EXPLAIN_EVIDENCE_GRAPH"
  | "MANUAL_VERIFICATION"
  | "QUESTION";

/**
 * Milestone 20 — the copilot can also explain a feature page's own deterministic
 * result. The page sends back the response it received; the backend whitelists
 * the fields that reach the model. There is no system result in these contexts.
 */
export type CopilotFeatureContext =
  | { feature: "STANDARD"; standard: ProductStandardResponse }
  | { feature: "CERTIFICATION"; certification: CertificationGuidanceResponse }
  | { feature: "LABORATORY"; laboratory: LaboratorySearchResponse }
  | { feature: "PRODUCT"; product: ProductContext };

export interface CopilotStatus {
  configured: boolean; // the server has a key; the key itself is never sent here
  provider: string;
  model: string;
  daily_limit: number;
  daily_used: number;
  daily_remaining: number;
  minute_limit: number;
  minute_remaining: number;
  capabilities: { code: CopilotCapability; label: string; question: string }[];
  note: string;
}

export interface CopilotSource {
  title: string;
  authority: string;
  reference: string | null;
  quote: string | null;
  document_name: string | null;
  source_url: string | null;
}

export interface CopilotAnswer {
  capability: CopilotCapability;
  question: string;
  evidence_scope: "SAVED_RECORD" | "LIVE_ANALYSIS" | "FEATURE_CONTEXT";
  context_type: string; // INSPECTION, or the feature explained
  language: AnswerLanguage; // the language the answer is written in
  confidence: "GROUNDED" | "UNSTRUCTURED" | "WITHHELD"; // deterministic, not the model's opinion
  inspection_id: string | null;
  escalation_required: boolean | null; // deterministic, read from the record; null for a feature context
  answer: string;
  evidence: { claim: string; source: string }[];
  limitations: string[];
  sources: CopilotSource[];
  grounded: boolean;
  withheld: boolean; // MetrIQ rejected the generated text
  withheld_reason: string;
  structured: boolean;
  model: string;
  usage: Record<string, unknown>;
}

export interface CopilotInput {
  capability: CopilotCapability;
  question?: string;
  inspection_id?: string; // a saved inspection …
  analysis?: InspectionAnalysis; // … the one currently on screen …
  context?: CopilotFeatureContext; // … or a feature page's own result
  rule_id?: string;
  language?: LanguageChoice;
}

/** The evidence-backed PDF report of a saved inspection — generated on request from the stored record (read-only). */
export const inspectionReportUrl = (id: string) => `${API_BASE}/inspections/${encodeURIComponent(id)}/report.pdf`;

/** Absolute URL of a stored package photo (the API returns a path). */
export const inspectionImageUrl = (path: string) => `${API_BASE}${path}`;

function packageForm(
  uploads: PackageUploadInput[],
  inspectionType: InspectionType = "PACKAGE",
  huidReference = "",
): FormData {
  const form = new FormData();
  if (inspectionType !== "PACKAGE") form.append("inspection_type", inspectionType);
  // Milestone 19: recorded server-side as USER-PROVIDED so it reaches the
  // evidence and the report — it never verifies anything.
  if (huidReference.trim()) form.append("huid_reference", huidReference.trim());
  for (const u of uploads) {
    form.append("images", u.file);
    form.append("sides", u.side);
  }
  return form;
}

/* --------------------------------------------------------------- endpoints --- */

export const api = {
  health: () => request<Health>("/health"),

  productStandard: (product: string, limit = 6, language: LanguageChoice = "auto") =>
    request<ProductStandardResponse>("/product-standard", {
      method: "POST",
      body: JSON.stringify({ product, limit, language }),
    }),

  certificationGuidance: (
    question: string,
    product = "",
    standardNumber = "",
    explain = true,
    language: LanguageChoice = "auto",
  ) =>
    request<CertificationGuidanceResponse>(
      "/certification-guidance",
      {
        method: "POST",
        body: JSON.stringify({
          question,
          product,
          standard_number: standardNumber,
          explain,
          language,
        }),
      },
      // Without the model this is pure retrieval, so it must not wait 90s.
      explain ? 90_000 : 20_000,
    ),

  laboratorySearch: (
    query: string,
    standard = "",
    explain = false,
    language: LanguageChoice = "auto",
    standardNumber = "",
  ) =>
    request<LaboratorySearchResponse>(
      "/laboratory-search",
      {
        method: "POST",
        body: JSON.stringify({
          query,
          standard,
          explain,
          language,
          standard_number: standardNumber,
        }),
      },
      explain ? 90_000 : 20_000,
    ),

  // Grounded BIS Q&A (Phase 4). Used for the Hallmarking / HUID information view.
  // Phase 6: `context` is the previous answer's context, echoed back so a
  // follow-up ("is it mandatory?") can refer to its product. Optional.
  ask: (question: string, language: LanguageChoice = "auto", context: ConversationContext | null = null) =>
    request<AskResponse>(
      "/ask",
      { method: "POST", body: JSON.stringify({ question, language, context }) },
      120_000,
    ),

  // Instant OCR: send every photo of one package, get each image's OCR regions
  // and the declarations read from all of them back.
  instantOcr: (uploads: PackageUploadInput[]) =>
    request<InstantOcr>(
      "/inspection/ocr",
      { method: "POST", body: packageForm(uploads) },
      60_000 + 60_000 * uploads.length,
    ),

  // Smart Inspection: OCR + declarations + product identification + standards.
  analyzeInspection: (
    uploads: PackageUploadInput[],
    inspectionType: InspectionType = "PACKAGE",
    huidReference = "",
  ) =>
    request<InspectionAnalysis>(
      "/inspection/analyze",
      { method: "POST", body: packageForm(uploads, inspectionType, huidReference) },
      60_000 + 60_000 * uploads.length,
    ),

  // Save: the backend re-runs the analysis on these photos and stores it with its evidence.
  saveInspection: (
    uploads: PackageUploadInput[],
    inspectionType: InspectionType = "PACKAGE",
    huidReference = "",
  ) =>
    request<InspectionRecord>(
      "/inspections",
      { method: "POST", body: packageForm(uploads, inspectionType, huidReference) },
      60_000 + 60_000 * uploads.length,
    ),

  listInspections: (limit = 100) =>
    request<{ items: InspectionSummary[]; total: number }>(`/inspections?limit=${limit}`),

  inspectionStats: () => request<InspectionStats>("/inspections/stats"),

  getInspection: (id: string) => request<InspectionRecord>(`/inspections/${encodeURIComponent(id)}`),

  // What MetrIQ can do with each verified standard (data-derived, no model).
  inspectionCoverage: () => request<CoverageMatrix>("/inspection/coverage", undefined, 20_000),

  // Milestone 21: the canonical product context for a product that has not been
  // inspected. Server-derived — the request carries only text.
  productContext: (product: string, standardNumber = "") =>
    request<ProductContext>(
      "/product-context",
      { method: "POST", body: JSON.stringify({ product, standard_number: standardNumber }) },
      30_000,
    ),

  // Milestone 22: project existing evidence onto the graph. Read-only, no model.
  evidenceGraph: (body: EvidenceGraphInput) =>
    request<EvidenceGraph>("/evidence-graph", { method: "POST", body: JSON.stringify(body) }, 30_000),

  // Copilot: is an explanation service configured, and how much free budget is left?
  copilotStatus: () => request<CopilotStatus>("/copilot/status", undefined, 10_000),

  // Copilot: ONE explanation for ONE user action. Never called automatically.
  copilotExplain: (body: CopilotInput) =>
    request<CopilotAnswer>("/copilot/explain", { method: "POST", body: JSON.stringify(body) }, 90_000),

};
