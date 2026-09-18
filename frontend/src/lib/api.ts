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
    /inspections             (saved inspections + officer review; backend computes every result)
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
}

export interface AskResponse {
  question: string;
  answer: string;
  grounded: boolean;
  source_count: number;
  sources: EvidenceSource[];
}

/* ---- inspection: IMAGE -> OCR (/inspection/ocr) -> pipeline (/analyze) --- */

/** Package sides a photo can show. UNKNOWN when the officer did not say. */
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
export interface ProductIdentification {
  status: "MATCHED" | "REVIEW";
  name: string | null; // BIS product description from the knowledge base
  knowledge_id: string | null;
  standard_number: string | null;
  confidence: string; // retrieval confidence: high | medium | low | none
  method: "deterministic" | "model_assisted";
  reason: string;
  evidence: ProductEvidence[];
  unverified_standard_numbers: string[];
  notes: string[];
}

/** A verified knowledge-base standard supported by the package evidence. */
export interface StandardCandidate extends ProductStandardResult {
  product: string;
  tier: "product" | "alias" | "category" | "standard_number";
  printed_on_label: boolean;
  evidence: ProductEvidence[];
}

/** Package evidence behind a compliance check: declaration -> OCR regions. */
export interface CheckEvidence {
  declaration_field: string;
  declaration_status: string;
  value: string | null;
  raw_text: string;
  source_regions: string[];
  image_id: string | null;
  ocr_confidence: number | null;
  bbox: [number, number, number, number] | null;
  source_images: string[];
  source_sides: PackageSide[];
}

/** The verified knowledge record a requirement quotes — BIS or Legal Metrology. */
export interface RequirementSource {
  knowledge_id: string;
  title: string;
  quote: string; // word for word from the verified record
  source_url: string | null;
  document_name: string | null;
  reference: string | null;
  verification_status: string;
  last_verified: string | null;
  source_authority: SourceAuthority;
  source_organization: string | null;
}

/** Which authority a requirement comes from. The two are never merged. */
export type SourceAuthority = "BIS" | "LEGAL_METROLOGY";

export type CheckResult = "PASS" | "FAIL" | "REVIEW" | "NOT_SUPPORTED" | "NOT_APPLICABLE";

export interface ComplianceCheck {
  rule_id: string;
  requirement: string;
  rule_type: string;
  standard_number: string | null; // null for Legal Metrology package-label requirements
  result: CheckResult;
  reason_code: string; // machine-readable
  reason: string; // deterministic, produced by the rule
  reason_category:
    | "REQUIREMENT_SATISFIED"
    | "REQUIREMENT_NOT_SATISFIED"
    | "EVIDENCE_NOT_DETECTED"
    | "EVIDENCE_NOT_DETERMINABLE"
    | "CONFLICTING_EVIDENCE"
    | "INSUFFICIENT_EVIDENCE"
    | "NOT_SUPPORTED"
    | "NOT_APPLICABLE";
  rule_condition: string; // the exact deterministic condition the rule applies
  observed_value: string | null;
  expected_condition: string;
  evidence_status: "SUFFICIENT" | "INSUFFICIENT" | "NOT_DETECTED" | "NOT_APPLICABLE";
  evidence: CheckEvidence[];
  source: RequirementSource | null;
  source_category: SourceAuthority;
  domain: string;
  reference: string; // rule / clause, e.g. "Rule 6(1)(e)"
  applicability: string;
  supporting_sources: RequirementSource[]; // amendments and related rules, quoted
}

/** An applicability exclusion read on the package (e.g. "not for retail sale"). */
export interface ExclusionFinding {
  id: string;
  description: string;
  observed: string;
  source_regions: string[];
  sources: RequirementSource[];
  evidence: CheckEvidence[];
}

/** Legal Metrology package-label requirements — separate from BIS compliance, never merged. */
export interface PackageLabelEvaluation {
  source_category: "LEGAL_METROLOGY";
  source_authority: string;
  overall_status: "PASS" | "FAIL" | "REVIEW";
  reason_code: string;
  reason: string;
  scope_status: "IN_SCOPE" | "OUT_OF_SCOPE" | "NO_REQUIREMENT_DATA";
  scope: string;
  scope_source: RequirementSource | null;
  exclusions_found: ExclusionFinding[];
  assumptions: string[]; // applicability a label cannot show
  assumption_sources: RequirementSource[];
  checks: ComplianceCheck[];
  supported_checks: number;
  passed: number;
  failed: number;
  review: number;
  not_supported: number;
  not_applicable: number;
  policy: string;
  summary: string[];
  notes: string[];
  unreadable_images: string[];
}

/** What MetrIQ can inspect for this package: product -> standard -> requirements -> rules. */
export interface InspectionCoverage {
  supported_checks: number;
  passed: number;
  failed: number;
  review: number;
  not_supported: number;
  product_applicability:
    | "PRODUCT_CONFIRMED"
    | "PRODUCT_NOT_MODELLED"
    | "PRODUCT_NOT_CONFIRMED"
    | "PRODUCT_AMBIGUOUS"
    | "NO_STANDARD";
  product_id: string | null;
  product_name: string | null; // modelled inspection product, when confirmed
  product_category: string | null;
  applicability_source: RequirementSource | null; // verified record linking product -> standard
  verified_requirements: number;
  deterministic_rules: number;
  unsupported_requirements: number;
  not_applied_requirements: string[];
  explanation: string; // deterministic: why coverage is what it is
}

/** Deterministic compliance evaluation — never decided by a model. */
export interface ComplianceEvaluation {
  overall_status: "PASS" | "FAIL" | "REVIEW";
  coverage_status: "INSPECTION_SUPPORTED" | "STANDARD_ONLY" | "UNSUPPORTED" | "NO_STANDARD";
  reason_code: string;
  reason: string;
  product_name: string | null;
  standard_number: string | null;
  knowledge_id: string | null;
  coverage: InspectionCoverage;
  checks: ComplianceCheck[];
  policy: string;
  notes: string[];
  summary: string[]; // deterministic overall explanation, one fact per line
  unreadable_images: string[];
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
  compliance: string;
  officer_review: string;
  package_label: string;
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

export interface HallmarkEvidence {
  detected: boolean;
  verification_status: "NOT_VERIFIED" | "NOT_DETECTED"; // there is no VERIFIED state
  verification_note: string;
  overall_status: "PASS" | "FAIL" | "REVIEW";
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
  sources: HallmarkSource[];
}

export type InspectionType = "PACKAGE" | "HALLMARK";

/** One reason the automated system could not resolve an inspection by itself. */
export interface EscalationReason {
  code: string; // e.g. PRODUCT_NOT_IDENTIFIED, CONFLICTING_DECLARATIONS
  label: string;
  source: "OCR" | "PRODUCT" | "BIS" | "LEGAL_METROLOGY" | "HALLMARKING" | "PIPELINE";
  message: string;
  source_regions: string[];
  checks: string[];
}

/** Can the system confidently resolve this inspection? Deterministic; changes no result. */
export interface Escalation {
  required: boolean; // true -> officer review queue; false -> the system result is final
  system_result: "PASS" | "FAIL" | "REVIEW";
  reasons: EscalationReason[];
}

export interface InspectionAnalysis {
  inspection_id: string;
  created_at: string;
  image: InspectionImage;
  quality: ImageQuality;
  ocr: OcrResult;
  images: PackageImage[];
  package: PackageCoverage;
  declaration_stage: DeclarationStage;
  product: ProductIdentification;
  standards: StandardCandidate[]; // ranked, verified knowledge-base records only
  retrieval_note: string;
  compliance: ComplianceEvaluation; // BIS
  package_label: PackageLabelEvaluation; // Legal Metrology
  completeness: DeclarationCompleteness;
  pipeline: PipelineStages;
  notes: string[];
  escalation: Escalation | null; // null only for inspections saved before escalation existed
  inspection_type: InspectionType;
  hallmark: HallmarkEvidence | null; // observed hallmark / HUID evidence — never an authentication
}

/* ------------------------------------------------ saved inspections --- */

export type SystemResult = "PASS" | "FAIL" | "REVIEW";
/** NOT_REQUIRED: resolved by the system, never queued. PENDING: waiting in the officer queue. */
export type OfficerStatus = "NOT_REQUIRED" | "PENDING" | "IN_REVIEW" | "COMPLETED";
export type OfficerDecision = "ACCEPT_SYSTEM_RESULT" | "OVERRIDE" | "MANUAL_REVIEW";

/** One saved inspection in a list. `system_result` is fixed when saved; the officer fields come later. */
export interface InspectionSummary {
  inspection_id: string;
  created_at: string;
  product_status: string;
  product_name: string | null;
  product_category: string | null;
  standard_number: string | null;
  bis_result: SystemResult;
  legal_metrology_result: SystemResult;
  system_result: SystemResult; // never changed by a review
  escalation_required: boolean;
  escalation_reasons: EscalationReason[];
  officer_status: OfficerStatus;
  officer_decision: OfficerDecision | null;
  officer_result: SystemResult | null; // only for an OVERRIDE
  final_result: SystemResult | "MANUAL_REVIEW" | null; // system result if not escalated; null until a review completes
  review_started_at: string | null;
  review_completed_at: string | null;
  image_count: number;
  sides: PackageSide[];
}

export interface InspectionRecord extends InspectionSummary {
  system_reasons: { source: SourceAuthority | "HALLMARKING"; result: SystemResult; reason_code: string; reason: string }[];
  officer_note: string | null;
  images: { index: number; image_id: string; side: PackageSide; filename: string; content_type: string; url: string }[];
  analysis: InspectionAnalysis; // the saved deterministic analysis and its evidence
}

export interface InspectionStats {
  total: number;
  system: Record<SystemResult, number>;
  bis: Record<SystemResult, number>;
  legal_metrology: Record<SystemResult, number>;
  escalated: number; // sent to the officer queue
  officer: Record<OfficerStatus, number>;
  decisions: Record<OfficerDecision, number>;
}


/* ------------------------------------------------- MetrIQ Copilot (grounded) --- */

/**
 * The optional explanation layer. It reads a finished inspection and puts it into
 * words; it cannot retrieve, decide or change anything. `system_result` below is
 * always the deterministic result read from the record — never the model's.
 */
export type CopilotCapability =
  | "EXPLAIN_INSPECTION"
  | "SUMMARIZE"
  | "EXPLAIN_ESCALATION"
  | "EXPLAIN_CHECKS"
  | "EXPLAIN_EVIDENCE"
  | "EXPLAIN_UNCERTAINTY"
  | "EXPLAIN_HALLMARK"
  | "MANUAL_VERIFICATION"
  | "QUESTION";

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
  evidence_scope: "SAVED_RECORD" | "LIVE_ANALYSIS";
  inspection_id: string | null;
  system_result: SystemResult | null; // deterministic, read from the record
  escalation_required: boolean | null;
  officer_status: OfficerStatus | null;
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
  analysis?: InspectionAnalysis; // … or the one currently on screen
  rule_id?: string;
}

export type ReviewInput =
  | { action: "START" }
  | { action: "COMPLETE"; decision: OfficerDecision; officer_result?: SystemResult; note?: string };

/** The evidence-backed PDF report of a saved inspection — generated on request from the stored record (read-only). */
export const inspectionReportUrl = (id: string) => `${API_BASE}/inspections/${encodeURIComponent(id)}/report.pdf`;

/** Absolute URL of a stored package photo (the API returns a path). */
export const inspectionImageUrl = (path: string) => `${API_BASE}${path}`;

function packageForm(uploads: PackageUploadInput[], inspectionType: InspectionType = "PACKAGE"): FormData {
  const form = new FormData();
  if (inspectionType !== "PACKAGE") form.append("inspection_type", inspectionType);
  for (const u of uploads) {
    form.append("images", u.file);
    form.append("sides", u.side);
  }
  return form;
}

/* --------------------------------------------------------------- endpoints --- */

export const api = {
  health: () => request<Health>("/health"),

  productStandard: (product: string, limit = 6) =>
    request<ProductStandardResponse>("/product-standard", {
      method: "POST",
      body: JSON.stringify({ product, limit }),
    }),

  certificationGuidance: (question: string, product = "") =>
    request<CertificationGuidanceResponse>(
      "/certification-guidance",
      { method: "POST", body: JSON.stringify({ question, product }) },
      90_000,
    ),

  laboratorySearch: (query: string, standard = "", explain = false) =>
    request<LaboratorySearchResponse>(
      "/laboratory-search",
      { method: "POST", body: JSON.stringify({ query, standard, explain }) },
      explain ? 90_000 : 20_000,
    ),

  // Grounded BIS Q&A (Phase 4). Used for the Hallmarking / HUID information view.
  ask: (question: string) =>
    request<AskResponse>(
      "/ask",
      { method: "POST", body: JSON.stringify({ question }) },
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

  // Smart Inspection: OCR + declarations + product + standards + compliance.
  analyzeInspection: (uploads: PackageUploadInput[], inspectionType: InspectionType = "PACKAGE") =>
    request<InspectionAnalysis>(
      "/inspection/analyze",
      { method: "POST", body: packageForm(uploads, inspectionType) },
      60_000 + 60_000 * uploads.length,
    ),

  // Save: the backend re-runs the analysis on these photos and stores it for officer review.
  saveInspection: (uploads: PackageUploadInput[], inspectionType: InspectionType = "PACKAGE") =>
    request<InspectionRecord>(
      "/inspections",
      { method: "POST", body: packageForm(uploads, inspectionType) },
      60_000 + 60_000 * uploads.length,
    ),

  listInspections: (officerStatuses: OfficerStatus[] = [], limit = 100) => {
    const q = new URLSearchParams({ limit: String(limit) });
    officerStatuses.forEach((st) => q.append("officer_status", st));
    return request<{ items: InspectionSummary[]; total: number }>(`/inspections?${q}`);
  },

  inspectionStats: () => request<InspectionStats>("/inspections/stats"),

  getInspection: (id: string) => request<InspectionRecord>(`/inspections/${encodeURIComponent(id)}`),

  // Copilot: is an explanation service configured, and how much free budget is left?
  copilotStatus: () => request<CopilotStatus>("/copilot/status", undefined, 10_000),

  // Copilot: ONE explanation for ONE user action. Never called automatically.
  copilotExplain: (body: CopilotInput) =>
    request<CopilotAnswer>("/copilot/explain", { method: "POST", body: JSON.stringify(body) }, 90_000),

  reviewInspection: (id: string, body: ReviewInput) =>
    request<InspectionRecord>(`/inspections/${encodeURIComponent(id)}/review`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
