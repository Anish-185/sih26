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

export interface OcrRegion {
  id: string;
  image_id: string; // the image this region was read from
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
  extraction_method: "deterministic";
  note: string;
  reason: string; // why UNCERTAIN / NOT_DETECTED
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

export interface PipelineStages {
  ocr: string;
  declaration_extraction: string;
  product_identification: string;
  standard_retrieval: string;
  legal_metrology: string;
  officer_review: string;
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

/** Instant OCR — raw OCR evidence plus the declarations read from it. */
export interface InstantOcr {
  status: "COMPLETED" | "NO_TEXT";
  created_at: string;
  image: InspectionImage;
  quality: ImageQuality;
  ocr: OcrResult;
  declaration_stage: DeclarationStage;
  notes: string[];
}

export interface InspectionAnalysis {
  inspection_id: string;
  created_at: string;
  image: InspectionImage;
  quality: ImageQuality;
  ocr: OcrResult;
  declaration_stage: DeclarationStage;
  product: ProductIdentification;
  standards: StandardCandidate[]; // ranked, verified knowledge-base records only
  retrieval_note: string;
  pipeline: PipelineStages;
  notes: string[];
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

  // Instant OCR: send the package image, get the raw OCR regions and the
  // declarations read from them back.
  instantOcr: (file: File) => {
    const form = new FormData();
    form.append("image", file);
    return request<InstantOcr>(
      "/inspection/ocr",
      { method: "POST", body: form },
      120_000,
    );
  },

  // Smart Inspection: OCR + declarations + product + verified standard.
  analyzeInspection: (file: File) => {
    const form = new FormData();
    form.append("image", file);
    return request<InspectionAnalysis>(
      "/inspection/analyze",
      { method: "POST", body: form },
      120_000,
    );
  },
};
