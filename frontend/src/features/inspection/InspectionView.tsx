import { type ReactNode, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowUpRight, RotateCcw, Save, ScanSearch, X } from "lucide-react";
import {
  ApiError,
  api,
  type Declaration,
  type DeclarationCompleteness,
  type DeclarationStage,
  type InspectionAnalysis,
  type InstantOcr,
  type OcrRegion,
  PACKAGE_SIDES,
  type PackageImage,
  type PackageSide,
  type ProductEvidence,
  type ProductIdentification,
  type StandardCandidate,
  type VisionObservation,
} from "@/lib/api";
import { passportPath, standardTitle } from "@/lib/format";
import { useAsyncTask } from "@/lib/hooks";
import { cn } from "@/lib/cn";
import {
  Button,
  Callout,
  CollapsiblePanel,
  ConfidenceMeter,
  DefinitionRow,
  InlineLoading,
  Mono,
  PageHeader,
  Panel,
  PanelHeader,
  SectionHeading,
} from "@/components/ui";
import { Dropzone } from "@/components/Dropzone";
import {
  Annotation,
  BlueprintField,
  Bracket,
  Motif,
  PhotoFragment,
  Ticks,
} from "@/components/decor";
import { PackageImages, RegionSides, regionSides, useWhere } from "./PackageImages";
import { ResolutionPanel } from "../records";
import { CertificationJourney } from "@/components/CertificationJourney";
import { CopilotPanel } from "../CopilotPanel";
import { ProductIntelligence } from "@/components/ProductIntelligence";
import { EvidenceGraphSection } from "@/components/EvidenceGraphSection";
import { EditionCurrency } from "@/components/EditionCurrency";
import { HallmarkEvidencePanel, showHallmark } from "../HallmarkEvidence";

// upload (stage photos) -> ocr (Instant OCR running) -> evidence (raw OCR shown)
//        -> workspace (after the user runs Smart Inspection)
type Phase = "upload" | "ocr" | "evidence" | "workspace" | "error";

/** A photo of the package waiting to be inspected. */
interface Staged {
  key: string;
  file: File;
  url: string;
  side: PackageSide;
}

const MAX_IMAGES = 8;

export function InspectionView() {
  const [phase, setPhase] = useState<Phase>("upload");
  const [staged, setStaged] = useState<Staged[]>([]);
  const stagedRef = useRef<Staged[]>([]);
  stagedRef.current = staged;
  const [activeImageId, setActiveImageId] = useState<string | null>(null);
  // Selected OCR regions. One id when a region is picked; every source region
  // when a declaration is picked, so all of its boxes light up.
  const [selection, setSelection] = useState<string[]>([]);
  const selectedRegion = selection[0] ?? null;

  const ocrTask = useAsyncTask(api.instantOcr);
  const task = useAsyncTask(api.analyzeInspection);
  const saveTask = useAsyncTask(api.saveInspection);
  const navigate = useNavigate();

  useEffect(() => {
    return () => stagedRef.current.forEach((s) => URL.revokeObjectURL(s.url));
  }, []);

  const images = (task.data ?? ocrTask.data)?.images ?? [];
  const urls = staged.map((s) => s.url);

  // Selecting evidence switches to the photo its first region came from.
  function selectRegions(ids: string[]) {
    setSelection(ids);
    const img = images.find((i) => i.ocr?.regions.some((r) => r.id === ids[0]));
    if (img) setActiveImageId(img.image_id);
  }
  const setSelectedRegion = (id: string | null) => selectRegions(id ? [id] : []);

  function addFiles(files: File[]) {
    setStaged((prev) =>
      [
        ...prev,
        ...files.map((file) => ({
          key: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
          file,
          url: URL.createObjectURL(file),
          side: "UNKNOWN" as PackageSide,
        })),
      ].slice(0, MAX_IMAGES),
    );
  }

  function removeStaged(key: string) {
    setStaged((prev) => {
      prev.filter((s) => s.key === key).forEach((s) => URL.revokeObjectURL(s.url));
      return prev.filter((s) => s.key !== key);
    });
  }

  function setSide(key: string, side: PackageSide) {
    setStaged((prev) => prev.map((s) => (s.key === key ? { ...s, side } : s)));
  }

  const uploads = () => staged.map((s) => ({ file: s.file, side: s.side }));

  function runOcr() {
    if (!staged.length) return;
    setSelection([]);
    task.reset();
    setPhase("ocr");
    ocrTask
      .run(uploads())
      .then((res) => {
        setActiveImageId((res.images.find((i) => i.ocr) ?? res.images[0]).image_id);
        setPhase("evidence");
      })
      .catch(() => setPhase("error"));
  }

  // Smart Inspection is a separate, explicit step. The OCR evidence stays on
  // screen while it runs, and stays there if it fails.
  function runSmartInspection() {
    if (!staged.length) return;
    task
      .run(uploads())
      .then(() => setPhase("workspace"))
      .catch(() => {});
  }

  function reset() {
    staged.forEach((s) => URL.revokeObjectURL(s.url));
    setStaged([]);
    setActiveImageId(null);
    setSelection([]);
    ocrTask.reset();
    task.reset();
    saveTask.reset();
    setPhase("upload");
  }

  // Saving sends the same photos again: the backend runs its own analysis and
  // stores that, so a saved result can never come from the browser.
  function saveForReview() {
    if (!staged.length) return;
    saveTask
      .run(uploads())
      .then((record) => navigate(`/history/${record.inspection_id}`))
      .catch(() => {});
  }

  /* ------------------------------------------------------------- upload --- */

  if (phase === "upload") {
    return (
      <div className="space-y-12">
        <PageHeader
          eyebrow="Inspection"
          title="Start an inspection"
          lead="Add one or more photos of the same package — front, back, sides — and mark each side if you know it. MetrIQ runs local PaddleOCR on every photo and shows what it read, with boxes and confidence. Smart Inspection — declarations, product identification and a verified Indian Standard — is a separate next step."
          annotation={<Annotation lead="right">Capture → OCR → Inspect</Annotation>}
        />

        <ol className="grid grid-cols-2 gap-px border border-line bg-line sm:grid-cols-4">
          {[
            ["01", "Capture", "Package & declaration panel"],
            ["02", "Instant OCR", "PaddleOCR text, boxes + declarations"],
            ["03", "Smart Inspection", "Declarations → product → Indian Standard"],
            ["04", "Evidence", "Evidence graph, report & copilot"],
          ].map(([n, t, d], i) => (
            <li key={n} className="relative bg-raised p-5">
              <div className="flex items-center gap-2">
                <Mono className="text-[11px] text-accent">{n}</Mono>
                {i < 3 && (
                  <span className="hidden h-px flex-1 bg-line sm:block" aria-hidden />
                )}
              </div>
              <div className="mt-3 text-[13px] font-semibold">{t}</div>
              <div className="mt-1 text-[12px] leading-snug text-ink-faint">{d}</div>
            </li>
          ))}
        </ol>

        <div className="relative">
          <Annotation className="absolute -top-6 left-0 hidden sm:inline-flex">
            Place evidence
          </Annotation>
          <div className="relative overflow-hidden border border-line-strong bg-surface">
            <BlueprintField fade="radial" variant="dots" />
            <Motif
              name="fingerprint"
              className="absolute left-1/2 top-1/2 h-[130%] w-auto max-w-none -translate-x-1/2 -translate-y-1/2 opacity-[0.08]"
            />
            <PhotoFragment
              src="/blue-botanical.png"
              className="absolute inset-y-0 left-0 hidden w-12 object-cover object-[8%_45%] opacity-30 md:block lg:w-16"
            />
            <PhotoFragment
              src="/blue-botanical.png"
              className="absolute inset-y-0 right-0 hidden w-12 scale-x-[-1] object-cover object-[8%_45%] opacity-30 md:block lg:w-16"
            />
            <Ticks edge="top" count={13} className="opacity-60" />
            <Ticks edge="bottom" count={13} className="opacity-60" />
            <div className="relative [&>div]:!border-0 [&>div]:!bg-transparent">
              <Dropzone onFiles={addFiles} disabled={staged.length >= MAX_IMAGES} />
            </div>
          </div>
          <Bracket tone="accent" className="-inset-2" />
          <Annotation className="absolute -bottom-6 right-0">
            PNG · JPG · WEBP
          </Annotation>
        </div>

        {staged.length > 0 && (
          <Panel flush>
            <PanelHeader
              title="Package images"
              meta={`${staged.length} of ${MAX_IMAGES} · one physical package`}
            />
            <ul className="grid gap-px bg-line sm:grid-cols-2 lg:grid-cols-4">
              {staged.map((s, i) => (
                <li key={s.key} className="bg-raised p-3">
                  <div className="relative">
                    <img src={s.url} alt={`Package photo ${i + 1}`} className="block h-32 w-full object-cover" />
                    <button
                      type="button"
                      onClick={() => removeStaged(s.key)}
                      aria-label={`Remove ${s.file.name}`}
                      className="absolute right-1.5 top-1.5 border border-line bg-raised p-1 text-ink-soft hover:text-fail"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <Mono muted className="mt-2 block truncate text-[10px]">
                    {String(i + 1).padStart(2, "0")} · {s.file.name}
                  </Mono>
                  <label className="mt-2 flex items-center gap-2">
                    <span className="kicker">Side</span>
                    <select
                      value={s.side}
                      onChange={(e) => setSide(s.key, e.target.value as PackageSide)}
                      className="min-w-0 flex-1 border border-line bg-surface px-2 py-1 font-mono text-[11px] text-ink"
                    >
                      {PACKAGE_SIDES.map((side) => (
                        <option key={side} value={side}>
                          {side === "UNKNOWN" ? "Not sure" : side}
                        </option>
                      ))}
                    </select>
                  </label>
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3">
              <p className="text-[11px] text-ink-faint">
                Photos of different packages must be inspected separately. Sides you
                do not photograph are reported as not uploaded — never as a finding about the package.
              </p>
              <Button size="sm" onClick={runOcr}>
                <ScanSearch className="h-3.5 w-3.5" />
                Run OCR on {staged.length} {staged.length === 1 ? "image" : "images"}
              </Button>
            </div>
          </Panel>
        )}
      </div>
    );
  }

  /* ---------------------------------------------------- instant OCR run --- */

  if (phase === "ocr") {
    return (
      <div className="mx-auto max-w-lg space-y-8 py-16">
        <div className="flex items-center gap-3">
          <span className="eyebrow">Reading package</span>
          <span className="h-px w-8 bg-accent/40" aria-hidden />
        </div>
        <div className="relative grid grid-cols-2 gap-px border border-line bg-line">
          {staged.map((s) => (
            <div key={s.key} className="bg-raised">
              <img
                src={s.url}
                alt="Uploaded package"
                className="block h-40 w-full object-contain opacity-80"
              />
              <Mono muted className="block px-2 py-1 text-[10px] uppercase tracking-[0.1em]">
                {s.side === "UNKNOWN" ? "Side not set" : s.side}
              </Mono>
            </div>
          ))}
          <Bracket tone="accent" />
        </div>
        <div className="flex items-center gap-3 text-[13px] text-ink-soft">
          <InlineLoading label={`Running local PaddleOCR on ${staged.length} ${staged.length === 1 ? "image" : "images"}`} />
          <span>· first run loads the model, this can take a few seconds</span>
        </div>
      </div>
    );
  }

  /* -------------------------------------------------------------- error --- */

  if (phase === "error") {
    const err = ocrTask.error;
    const apiErr = err instanceof ApiError ? err : null;
    const msg =
      apiErr?.detail ??
      (err instanceof Error ? err.message : "Something went wrong during analysis.");
    return (
      <div className="mx-auto max-w-lg space-y-6 py-16">
        <div className="flex items-center gap-3">
          <span className="eyebrow">Inspection</span>
          <span className="h-px w-8 bg-accent/40" aria-hidden />
        </div>
        <Callout tone="abstain" title="OCR could not read this image">
          {msg}
        </Callout>
        <p className="text-[12px] leading-relaxed text-ink-faint">
          No OCR result is shown — MetrIQ never substitutes placeholder data
          for a failed read. Try a sharper, straight-on photo of the
          declaration panel, or a different image.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" size="sm" onClick={() => setPhase("upload")}>
            Back to the images
          </Button>
          <Button variant="secondary" size="sm" onClick={reset}>
            <RotateCcw className="h-3.5 w-3.5" />
            Start over
          </Button>
        </div>
      </div>
    );
  }

  /* ----------------------------------------------------------- evidence --- */

  if (phase === "evidence") {
    const evidence = ocrTask.data;
    if (!evidence || !staged.length) {
      return (
        <div className="py-16">
          <Button variant="secondary" size="sm" onClick={reset}>
            Restart
          </Button>
        </div>
      );
    }
    return (
      <OcrEvidence
        evidence={evidence}
        urls={urls}
        activeImageId={activeImageId ?? evidence.images[0].image_id}
        setActiveImageId={setActiveImageId}
        selectedRegion={selectedRegion}
        setSelectedRegion={setSelectedRegion}
        linkedRegions={selection}
        selectRegions={selectRegions}
        onReset={reset}
        onSmartInspection={runSmartInspection}
        smartLoading={task.loading}
        smartError={task.error}
      />
    );
  }

  /* ---------------------------------------------------------- workspace --- */

  const result = task.data;
  if (!result || !staged.length) {
    // Defensive — should not happen; recover to upload.
    return (
      <div className="py-16">
        <Button variant="secondary" size="sm" onClick={reset}>
          Restart
        </Button>
      </div>
    );
  }

  return (
    <Workspace
      result={result}
      urls={urls}
      activeImageId={activeImageId ?? result.images[0].image_id}
      setActiveImageId={setActiveImageId}
      selectedRegion={selectedRegion}
      setSelectedRegion={setSelectedRegion}
      linkedRegions={selection}
      selectRegions={selectRegions}
      actions={
        <div className="flex flex-col items-end gap-1.5">
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={saveForReview} disabled={saveTask.loading}>
              <Save className="h-3.5 w-3.5" />
              {saveTask.loading ? "Saving…" : "Save inspection"}
            </Button>
            <Button variant="secondary" size="sm" onClick={reset}>
              <RotateCcw className="h-3.5 w-3.5" />
              New inspection
            </Button>
          </div>
          {saveTask.error != null && (
            <span className="text-[12px] text-review">
              {saveTask.error instanceof ApiError ? saveTask.error.detail : "The inspection could not be saved."}
            </span>
          )}
        </div>
      }
    />
  );
}

/* ------------------------------------------------------------- workspace --- */

/** The inspection result with its evidence. Also used, read-only, for saved inspections. */
export function Workspace({
  result,
  urls,
  activeImageId,
  setActiveImageId,
  selectedRegion,
  setSelectedRegion,
  linkedRegions,
  selectRegions,
  actions,
  intro,
  hideResolution,
  hideCopilot,
  savedInspectionId,
}: {
  result: InspectionAnalysis;
  urls: string[];
  activeImageId: string;
  setActiveImageId: (id: string) => void;
  selectedRegion: string | null;
  setSelectedRegion: (id: string | null) => void;
  linkedRegions: string[];
  selectRegions: (ids: string[]) => void;
  actions?: ReactNode;
  intro?: ReactNode; // replaces the live-pipeline callout, e.g. for a saved inspection
  hideResolution?: boolean; // a saved inspection shows its stored resolution instead
  hideCopilot?: boolean; // the saved-record page places the copilot once, higher up
  savedInspectionId?: string; // a saved record: the graph is projected server-side from the stored analysis
}) {
  const { image, quality, ocr, declaration_stage, product, standards, images } = result;
  const activeImage = images.find((i) => i.image_id === activeImageId);
  const region = ocr.regions.find((r) => r.id === selectedRegion) ?? null;
  const declForRegion = declarationFor(declaration_stage, selectedRegion);
  const matched = product.status === "MATCHED";

  return (
    <RegionSides.Provider value={regionSides(images)}>
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SectionHeading
          kicker={`Inspection · ${result.inspection_id}`}
          title={images.length > 1 ? `${images.length} package images` : image.filename}
          className="[&_h1]:text-2xl [&_h1]:break-all"
        />
        {actions}
      </div>

      {intro ?? <Callout>
        <span className="font-medium">Live pipeline.</span> Local OCR, then
        deterministic declaration extraction, then product identification and
        standard candidates retrieved from the verified BIS knowledge base. Every
        value traces back to the OCR region — and the photo — it came from. A
        standard match is retrieval, not a compliance, certification or legal
        decision, and unresolved stages read “review”, never a guess.
      </Callout>}

      {result.escalation && !hideResolution && (
        <ResolutionPanel
          required={result.escalation.required}
          reasons={result.escalation.reasons}
          selected={linkedRegions}
          onSelect={selectRegions}
        />
      )}

      {result.notes.length > 0 && (
        <Callout tone="abstain" title={images.length > 1 ? "Notes on the images" : "Notes on this image"}>
          <ul className="list-disc space-y-1 pl-4">
            {result.notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </Callout>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,440px)_1fr]">
        {/* LEFT — image + summary */}
        <div className="space-y-4 lg:sticky lg:top-20 lg:self-start">
          <PackageImages
            images={images}
            urls={urls}
            coverage={result.package}
            activeImageId={activeImageId}
            onActivate={setActiveImageId}
            selectedId={selectedRegion}
            linkedIds={linkedRegions}
            onSelect={setSelectedRegion}
          />
          <Panel flush>
            <dl className="px-5 py-2">
              <DefinitionRow label="OCR engine">
                <Mono muted className="text-[11px]">
                  {ocr.engine}
                </Mono>
              </DefinitionRow>
              <DefinitionRow label="Regions">
                <Mono>{String(ocr.region_count).padStart(2, "0")}</Mono>
              </DefinitionRow>
              <DefinitionRow label="Mean confidence">
                <Mono>
                  {ocr.region_count
                    ? `${Math.round(ocr.mean_confidence * 100)}%`
                    : "—"}
                </Mono>
              </DefinitionRow>
              <DefinitionRow label="OCR time">
                <Mono muted>{ocr.duration_ms} ms</Mono>
              </DefinitionRow>
              <DefinitionRow label="Product">
                <span className={matched ? "text-ink" : "text-review"}>
                  {matched ? product.name : "Needs review"}
                </span>
              </DefinitionRow>
              <DefinitionRow label="Best-supported standard">
                <span className={matched ? "text-ink" : "text-review"}>
                  {matched ? product.standard_number : "Needs review"}
                </span>
                {matched && (
                  <EditionCurrency
                    compact
                    className="ml-2"
                    currency={standards.find((c) => c.standard_number === product.standard_number)?.currency}
                  />
                )}
              </DefinitionRow>
            </dl>
          </Panel>
        </div>

        {/* RIGHT — what MetrIQ concluded first, then the evidence behind it.
            Everything below "Supporting evidence" is folded away by default:
            it is how the conclusions were reached, not the conclusions. */}
        <div className="space-y-6">
          <ProductPanel
            vision={result.vision}
            product={product}
            selected={linkedRegions}
            onSelect={selectRegions}
          />
          <StandardCandidatesPanel
            standards={standards}
            product={product}
            note={result.retrieval_note}
            selected={linkedRegions}
            onSelect={selectRegions}
          />
          {result.certification && (
            <CertificationJourney journey={result.certification} />
          )}
          {showHallmark(result.hallmark, result.inspection_type) && (
            <HallmarkEvidencePanel hallmark={result.hallmark} selected={linkedRegions} onSelect={selectRegions} />
          )}

          <div className="space-y-3 pt-2">
            <div className="flex items-center gap-3">
              <span className="eyebrow">Supporting evidence</span>
              <span className="h-px flex-1 bg-line" aria-hidden />
            </div>
            <p className="max-w-prose text-[12px] leading-relaxed text-ink-faint">
              What the conclusions above were read from. Open a section to see it.
            </p>

            <DeclarationsPanel
              stage={declaration_stage}
              selected={linkedRegions}
              onSelect={selectRegions}
            />
            <CompletenessPanel
              completeness={result.completeness}
              selected={linkedRegions}
              onSelect={selectRegions}
            />
            <RegionsPanel
              regions={ocr.regions}
              selected={selectedRegion}
              onSelect={setSelectedRegion}
            />
            {/* Only present once a region is selected, so it stays expanded. */}
            {region && (
              <RegionDetail region={region} declaration={declForRegion} images={images} />
            )}
            <RawTextPanel text={ocr.text} />
            <QualityPanel
              quality={activeImage?.quality ?? quality}
              side={images.length > 1 ? activeImage?.side : undefined}
            />
            <DownstreamPanel result={result} />
          </div>
        </div>
      </div>

      <EvidenceGraphSection
        source={savedInspectionId ? { inspection_id: savedInspectionId } : { analysis: result }}
        onSelectRegions={selectRegions}
      />

      {result.product_context && <ProductIntelligence context={result.product_context} />}

      {!hideCopilot && result.escalation && (
        <CopilotPanel
          analysis={result}
          hasHallmark={Boolean(result.hallmark?.detected)}
        />
      )}
    </div>
    </RegionSides.Provider>
  );
}

/* ---------------------------------------------------------- OCR evidence --- */

/** Regions below this OCR confidence are flagged for a closer look. */
const LOW_CONFIDENCE = 0.8;

function OcrEvidence({
  evidence,
  urls,
  activeImageId,
  setActiveImageId,
  selectedRegion,
  setSelectedRegion,
  linkedRegions,
  selectRegions,
  onReset,
  onSmartInspection,
  smartLoading,
  smartError,
}: {
  evidence: InstantOcr;
  urls: string[];
  activeImageId: string;
  setActiveImageId: (id: string) => void;
  selectedRegion: string | null;
  setSelectedRegion: (id: string | null) => void;
  linkedRegions: string[];
  selectRegions: (ids: string[]) => void;
  onReset: () => void;
  onSmartInspection: () => void;
  smartLoading: boolean;
  smartError: unknown;
}) {
  const { image, quality, ocr, declaration_stage, images } = evidence;
  const activeImage = images.find((i) => i.image_id === activeImageId);
  const region = ocr.regions.find((r) => r.id === selectedRegion) ?? null;
  const declForRegion = declarationFor(declaration_stage, selectedRegion);
  const hasText = ocr.region_count > 0;
  const smartMsg = smartError
    ? smartError instanceof ApiError
      ? smartError.detail
      : smartError instanceof Error
        ? smartError.message
        : "Smart Inspection failed."
    : null;

  return (
    <RegionSides.Provider value={regionSides(images)}>
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SectionHeading
          kicker={`Instant OCR · ${images.length > 1 ? evidence.inspection_id : image.image_id}`}
          title={images.length > 1 ? `${images.length} package images` : image.filename}
          className="[&_h1]:text-2xl [&_h1]:break-all"
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            onClick={onSmartInspection}
            disabled={!hasText || smartLoading}
          >
            <ScanSearch className="h-3.5 w-3.5" />
            {smartLoading ? "Running Smart Inspection…" : "Run Smart Inspection"}
          </Button>
          <Button variant="secondary" size="sm" onClick={onReset}>
            <RotateCcw className="h-3.5 w-3.5" />
            New inspection
          </Button>
        </div>
      </div>

      <Callout>
        <span className="font-medium">OCR evidence.</span> The text is exactly
        what local PaddleOCR read from the image; the declarations are parsed from
        that text by fixed rules, and each links back to the boxes it came from.
        Nothing here identifies the product yet — Run Smart Inspection for the
        product and a verified Indian Standard.
      </Callout>

      {smartLoading && (
        <div className="text-[13px] text-ink-soft">
          <InlineLoading label="Extracting declarations, classifying the product and looking up the standard" />
        </div>
      )}
      {smartMsg && (
        <Callout tone="abstain" title="Smart Inspection could not finish">
          {smartMsg} The OCR evidence below is unaffected.
        </Callout>
      )}

      {evidence.notes.length > 0 && (
        <Callout tone="abstain" title={images.length > 1 ? "Notes on the images" : "Notes on this image"}>
          <ul className="list-disc space-y-1 pl-4">
            {evidence.notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </Callout>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,440px)_1fr]">
        {/* LEFT — image with OCR boxes */}
        <div className="space-y-4 lg:sticky lg:top-20 lg:self-start">
          <PackageImages
            images={images}
            urls={urls}
            coverage={evidence.package}
            activeImageId={activeImageId}
            onActivate={setActiveImageId}
            selectedId={selectedRegion}
            linkedIds={linkedRegions}
            onSelect={setSelectedRegion}
          />
          <Panel flush>
            <dl className="px-5 py-2">
              <DefinitionRow label="OCR engine">
                <Mono muted className="text-[11px]">
                  {ocr.engine}
                </Mono>
              </DefinitionRow>
              <DefinitionRow label={images.length > 1 ? "Images" : "Image"}>
                <Mono muted className="text-[11px]">
                  {images.length > 1
                    ? `${evidence.package.usable_images} of ${images.length} readable · ${ocr.region_count} regions`
                    : `${image.format} · ${image.width}×${image.height} · ${Math.max(1, Math.round(image.bytes / 1024))} KB`}
                </Mono>
              </DefinitionRow>
              <DefinitionRow label="OCR time">
                <Mono muted>{ocr.duration_ms} ms</Mono>
              </DefinitionRow>
            </dl>
          </Panel>
        </div>

        {/* RIGHT — OCR results */}
        <div className="space-y-6">
          <OcrSummaryPanel ocr={ocr} />
          <DeclarationsPanel
            stage={declaration_stage}
            selected={linkedRegions}
            onSelect={selectRegions}
            open
          />
          <RawTextPanel text={ocr.text} title="Detected text" open />
          <RegionsPanel
            regions={ocr.regions}
            selected={selectedRegion}
            onSelect={setSelectedRegion}
            open
          />
          {region && (
            <RegionDetail region={region} declaration={declForRegion} images={images} />
          )}
          <QualityPanel
            quality={activeImage?.quality ?? quality}
            side={images.length > 1 ? activeImage?.side : undefined}
          />
        </div>
      </div>
    </div>
    </RegionSides.Provider>
  );
}

function OcrSummaryPanel({ ocr }: { ocr: InstantOcr["ocr"] }) {
  const low = ocr.regions.filter((r) => r.confidence < LOW_CONFIDENCE).length;
  const hasText = ocr.region_count > 0;
  return (
    <Panel flush>
      <PanelHeader
        title="OCR results"
        meta={
          <span className={hasText ? "text-accent" : "text-review"}>
            {hasText ? "COMPLETED" : "NO TEXT"}
          </span>
        }
      />
      <dl className="grid grid-cols-3 gap-px border-b border-line bg-line">
        {[
          ["Regions", String(ocr.region_count)],
          [
            "Average confidence",
            hasText ? `${Math.round(ocr.mean_confidence * 100)}%` : "—",
          ],
          [`Below ${Math.round(LOW_CONFIDENCE * 100)}%`, hasText ? String(low) : "—"],
        ].map(([k, v]) => (
          <div key={k} className="bg-raised px-3 py-3 text-center">
            <div className="font-mono text-xl font-semibold tabular-nums">{v}</div>
            <div className="kicker mt-1">{k}</div>
          </div>
        ))}
      </dl>
      <p className="px-5 py-3 text-[12px] text-ink-faint">
        {hasText
          ? low > 0
            ? `${low} ${low === 1 ? "region was" : "regions were"} read with lower confidence — check ${low === 1 ? "it" : "them"} against the image.`
            : "Every region was read with high confidence."
          : "OCR found no legible text. Try a sharper, straight-on photo of the declaration panel."}
      </p>
    </Panel>
  );
}

/* -- panels ------------------------------------------------------------- */

function QualityPanel({
  quality,
  side,
}: {
  quality: InspectionAnalysis["quality"];
  side?: string;
}) {
  return (
    <CollapsiblePanel
      title={
        side
          ? `How readable the photo was · ${side === "UNKNOWN" ? "selected photo" : side}`
          : "How readable the photo was"
      }
      meta={quality.is_low_quality ? "flagged" : "ok"}
      defaultOpen={quality.is_low_quality}
    >
      <dl className="grid grid-cols-3 gap-px border-b border-line bg-line">
        {[
          ["Sharpness", quality.blur_score.toFixed(0)],
          ["Brightness", quality.brightness.toFixed(0)],
          ["Contrast", quality.contrast.toFixed(0)],
        ].map(([k, v]) => (
          <div key={k} className="bg-raised px-3 py-3 text-center">
            <div className="font-mono text-xl font-semibold tabular-nums">{v}</div>
            <div className="kicker mt-1">{k}</div>
          </div>
        ))}
      </dl>
      {quality.notes.length > 0 ? (
        <ul className="space-y-1 px-5 py-3 text-[12px] text-review">
          {quality.notes.map((n, i) => (
            <li key={i}>· {n}</li>
          ))}
        </ul>
      ) : (
        <p className="px-5 py-3 text-[12px] text-ink-faint">
          No quality issues detected.
        </p>
      )}
    </CollapsiblePanel>
  );
}

function RegionsPanel({
  regions,
  selected,
  onSelect,
  open,
}: {
  regions: OcrRegion[];
  selected: string | null;
  onSelect: (id: string | null) => void;
  open?: boolean;
}) {
  return (
    <CollapsiblePanel
      defaultOpen={open}
      title="Text detected on the package"
      meta={`${regions.length} ${regions.length === 1 ? "region" : "regions"}`}
    >
      {regions.length === 0 ? (
        <p className="px-5 py-4 text-[13px] text-ink-soft">
          OCR found no legible text in this image.
        </p>
      ) : (
        <ul>
          {regions.map((r, i) => {
            const active = r.id === selected;
            return (
              <li key={r.id}>
                <button
                  type="button"
                  onMouseEnter={() => onSelect(r.id)}
                  onFocus={() => onSelect(r.id)}
                  // hover already selects, so a toggle here would undo it
                  onClick={() => onSelect(r.id)}
                  className={cn(
                    "flex w-full items-start justify-between gap-4 px-5 py-3 text-left transition-colors",
                    i > 0 && "border-t border-line",
                    active ? "bg-accent-soft" : "hover:bg-surface",
                  )}
                >
                  <div className="min-w-0">
                    <div className="text-[13px] font-medium text-ink">
                      {r.text}
                    </div>
                    <Mono muted className="mt-0.5 block text-[10px]">
                      {r.side !== "UNKNOWN" ? `${r.side} · ` : ""}
                      {r.id} · box [{r.bbox.join(", ")}]
                    </Mono>
                  </div>
                  <Mono
                    className={cn(
                      "shrink-0 text-[11px]",
                      r.confidence < LOW_CONFIDENCE ? "text-review" : "text-ink-faint",
                    )}
                  >
                    {Math.round(r.confidence * 100)}%
                  </Mono>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </CollapsiblePanel>
  );
}

function RegionDetail({
  region,
  declaration,
  images,
}: {
  region: OcrRegion;
  /** Omit on the Instant OCR view — nothing has been interpreted yet. */
  declaration?: Declaration | null;
  images: PackageImage[];
}) {
  const [x1, y1, x2, y2] = region.bbox;
  const img = images.find((i) => i.image_id === region.image_id);
  const imageW = img?.width ?? 0;
  const imageH = img?.height ?? 0;
  return (
    <Panel flush>
      <PanelHeader title="Region evidence" meta={region.id} />
      <dl className="px-5 py-2">
        <DefinitionRow label="Raw text">
          <Mono className="text-ink">{region.text}</Mono>
        </DefinitionRow>
        <DefinitionRow label="Confidence">
          <Mono>{(region.confidence * 100).toFixed(1)}%</Mono>
        </DefinitionRow>
        <DefinitionRow label="Bounding box">
          <Mono muted className="text-[12px]">
            x {x1}–{x2} · y {y1}–{y2} px (of {imageW}×{imageH})
          </Mono>
        </DefinitionRow>
        <DefinitionRow label="Polygon">
          <Mono muted className="text-[11px]">
            {region.polygon.map((p) => `(${p[0]},${p[1]})`).join(" ")}
          </Mono>
        </DefinitionRow>
        {declaration !== undefined && (
        <DefinitionRow label="Interpretation">
          {declaration ? (
            <span className="text-ink">
              <span className="font-medium">{declaration.label}:</span>{" "}
              {declaration.value ?? "no value read"}
              <Mono muted className="mt-0.5 block text-[10px] uppercase tracking-[0.1em]">
                {declaration.method} · {declarationStatusLabel(declaration.status)}
              </Mono>
            </span>
          ) : (
            <span className="text-ink-faint">
              Not part of an extracted declaration.
            </span>
          )}
        </DefinitionRow>
        )}
      </dl>
    </Panel>
  );
}

/* -- pipeline panels -------------------------------------------------- */

function stageTone(status: string): string {
  switch (status) {
    case "COMPLETED":
    case "CLASSIFIED":
    case "MATCHED":
      return "text-accent";
    case "DETECTED":
      return "text-accent";
    case "PARTIAL":
    case "REVIEW":
    case "UNCERTAIN":
    case "NO_RELIABLE_TEXT":
      return "text-review";
    case "NEXT":
      return "text-ink-soft";
    default:
      return "text-ink-faint";
  }
}

function methodTone(method: Declaration["method"]): string {
  return method === "heuristic" ? "text-ink-faint" : "text-ink-soft";
}

function declarationStatusLabel(status: Declaration["status"]): string {
  return status === "DETECTED"
    ? "Detected"
    : status === "UNCERTAIN"
      ? "Uncertain"
      : "Not detected";
}

/** The declaration (with evidence) that uses this OCR region, if any. */
function declarationFor(
  stage: DeclarationStage,
  regionId: string | null,
): Declaration | null {
  if (!regionId) return null;
  return (
    stage.fields.find(
      (d) => d.status !== "NOT_DETECTED" && d.source_regions.includes(regionId),
    ) ?? null
  );
}

function DeclarationsPanel({
  stage,
  selected,
  onSelect,
  open,
}: {
  stage: DeclarationStage;
  selected: string[];
  onSelect: (ids: string[]) => void;
  /** Instant OCR shows the reading itself, so it opens these by default. */
  open?: boolean;
}) {
  const where = useWhere();
  const withEvidence = stage.fields.filter((d) => d.status !== "NOT_DETECTED");
  const notDetected = stage.fields.filter((d) => d.status === "NOT_DETECTED");
  const isActive = (d: Declaration) =>
    selected.length > 0 &&
    selected.length === d.source_regions.length &&
    d.source_regions.every((id, i) => selected[i] === id);

  return (
    <CollapsiblePanel
      defaultOpen={open}
      title="Values declared on the package"
      meta={
        <span className={stageTone(stage.status)}>
          {stage.status.replace(/_/g, " ")}
          {stage.principal_display_panel ? " · PDP" : ""}
        </span>
      }
    >
      <p className="border-b border-line px-5 py-2.5 text-[11px] leading-relaxed text-ink-faint">
        Parsed from the OCR text by fixed rules — select one to see where it came
        from. “OCR %” is how confident PaddleOCR was reading that text, not
        whether the declaration is correct or compliant.
      </p>

      {stage.status === "NO_RELIABLE_TEXT" ? (
        <p className="px-5 py-4 text-[13px] text-ink-soft">
          No reliable text to read declarations from. Nothing is shown rather
          than guessed.
        </p>
      ) : withEvidence.length === 0 ? (
        <p className="px-5 py-4 text-[13px] text-ink-soft">
          No declaration fields could be read from the OCR text — no values are
          shown.
        </p>
      ) : (
        <ul>
          {withEvidence.map((d, i) => {
            const active = isActive(d);
            return (
              <li key={d.field}>
                <button
                  type="button"
                  onMouseEnter={() => onSelect(d.source_regions)}
                  onFocus={() => onSelect(d.source_regions)}
                  onClick={() => onSelect(d.source_regions)}
                  className={cn(
                    "block w-full px-5 py-3 text-left transition-colors",
                    i > 0 && "border-t border-line",
                    active ? "bg-accent-soft" : "hover:bg-surface",
                  )}
                >
                  <div className="flex items-baseline justify-between gap-4">
                    <div className="kicker">{d.label}</div>
                    <Mono
                      className={cn(
                        "shrink-0 text-[10px] uppercase tracking-[0.1em]",
                        stageTone(d.status),
                      )}
                    >
                      {declarationStatusLabel(d.status)}
                    </Mono>
                  </div>
                  <div
                    className={cn(
                      "mt-1 text-[13px] font-medium",
                      d.value ? "text-ink" : "italic text-ink-faint",
                    )}
                  >
                    {d.value ?? "No value read"}
                  </div>
                  <Mono muted className="mt-1 block truncate text-[10px]">
                    from “{d.raw_text}”
                  </Mono>
                  <Mono muted className="mt-0.5 block text-[10px]">
                    {where(d.source_regions)}
                    {d.ocr_confidence !== null &&
                      ` · OCR ${Math.round(d.ocr_confidence * 100)}%`}
                    {" · "}
                    <span className={methodTone(d.method)}>{d.method}</span>
                    {d.extraction_method === "deterministic_normalization" && (
                      <span className="text-review"> · normalized from OCR “{d.raw_text}”</span>
                    )}
                  </Mono>
                  {d.reason && (
                    <p className="mt-1 text-[11px] leading-snug text-review">
                      {d.reason}
                    </p>
                  )}
                  {d.observations.length > 1 && (
                    <div className="mt-2 border-l-2 border-line pl-2">
                      <div className="kicker">
                        {d.consistency === "CONFLICT" ? "Different readings" : "Same value read on"}
                      </div>
                      {d.observations.map((o, j) => (
                        <Mono key={j} muted className="mt-0.5 block text-[10px]">
                          {d.consistency === "CONFLICT" ? `${o.value ?? "—"} — ` : ""}
                          {where(o.source_regions)} · OCR {Math.round(o.ocr_confidence * 100)}%
                        </Mono>
                      ))}
                    </div>
                  )}
                  {d.note && (
                    <p className="mt-1 text-[11px] leading-snug text-ink-faint">
                      {d.note}
                    </p>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {stage.status !== "NO_RELIABLE_TEXT" && notDetected.length > 0 && (
        <p className="border-t border-line px-5 py-3 text-[11px] leading-relaxed text-ink-faint">
          <span className="text-ink-soft">Not detected in the OCR text of the uploaded images:</span>{" "}
          {notDetected.map((d) => d.label).join(" · ")}
        </p>
      )}
    </CollapsiblePanel>
  );
}

const CLUE_LABEL: Record<ProductEvidence["clue"]["kind"], string> = {
  product_name: "Product name",
  product_description: "Product description",
  brand: "Brand",
  standard_number: "Printed standard number",
  ocr_text: "Label text",
  model_hint: "Local model suggestion",
};

const MATCH_LABEL: Record<ProductEvidence["match"], string> = {
  product: "matches the BIS product description",
  alias: "matches a knowledge-base keyword",
  category: "matches a category shared by several standards",
  standard_number: "number found in the verified knowledge base",
};

/** One piece of package evidence; selecting it lights up its OCR boxes. */
function EvidenceRow({
  evidence,
  selected,
  onSelect,
  divider,
}: {
  evidence: ProductEvidence;
  selected: string[];
  onSelect: (ids: string[]) => void;
  divider: boolean;
}) {
  const where = useWhere();
  const { clue } = evidence;
  const ids = clue.source_regions;
  const active =
    ids.length > 0 &&
    ids.length === selected.length &&
    ids.every((id, i) => selected[i] === id);
  const body = (
    <>
      <div className="kicker">{CLUE_LABEL[clue.kind]}</div>
      <div className="mt-1 text-[13px] text-ink">“{clue.text}”</div>
      {clue.search_text && (
        <Mono muted className="mt-0.5 block text-[10px]">
          OCR ran words together · searched as “{clue.search_text}”
        </Mono>
      )}
      <Mono muted className="mt-0.5 block text-[10px]">
        {ids.length ? where(ids) : "not read from the label"}
        {clue.declaration_status ? ` · declaration ${clue.declaration_status.toLowerCase()}` : ""}
        {clue.ocr_confidence !== null ? ` · OCR ${Math.round(clue.ocr_confidence * 100)}%` : ""}
      </Mono>
      <p className="mt-1 text-[11px] leading-snug text-ink-soft">
        {MATCH_LABEL[evidence.match]}
        {evidence.match !== "standard_number" && evidence.matched_phrase
          ? ` (“${evidence.matched_phrase}”)`
          : ""}
      </p>
    </>
  );
  const cls = cn(
    "block w-full px-5 py-3 text-left transition-colors",
    divider && "border-t border-line",
    active ? "bg-accent-soft" : ids.length ? "hover:bg-surface" : "",
  );
  if (!ids.length) return <div className={cls}>{body}</div>;
  return (
    <button
      type="button"
      onMouseEnter={() => onSelect(ids)}
      onFocus={() => onSelect(ids)}
      onClick={() => onSelect(ids)}
      className={cls}
    >
      {body}
    </button>
  );
}

const APPLICABILITY_LABEL: Record<NonNullable<ProductIdentification["product_applicability"]>, string> = {
  PRODUCT_CONFIRMED: "Product confirmed from the package text",
  PRODUCT_NOT_MODELLED: "No product-level requirement data for this standard",
  PRODUCT_NOT_CONFIRMED: "Package text did not confirm a modelled product",
  PRODUCT_AMBIGUOUS: "Package text names more than one modelled product",
};

function ProductPanel({
  product,
  vision = [],
  selected,
  onSelect,
}: {
  product: ProductIdentification;
  vision?: VisionObservation[];
  selected: string[];
  onSelect: (ids: string[]) => void;
}) {
  const matched = product.status === "MATCHED";
  const seen = vision.filter((v) => v.status === "OK" && v.product_label);
  const signals = product.signals;
  return (
    <Panel flush>
      <PanelHeader
        title="Product identification"
        meta={<span className={stageTone(product.status)}>{product.status}</span>}
      />
      {matched ? (
        <dl className="px-5 py-2">
          <DefinitionRow label="Product">
            <span className="text-ink">{product.name}</span>
            <Mono muted className="mt-0.5 block text-[10px] uppercase tracking-[0.1em]">
              BIS product description · knowledge base
            </Mono>
          </DefinitionRow>
          <DefinitionRow label="Retrieval confidence">
            <ConfidenceMeter confidence={product.confidence} />
          </DefinitionRow>
          {product.product_applicability && (
            <DefinitionRow label="Requirement knowledge">
              <span className={product.modelled_product_id ? "text-ink" : "text-ink-soft"}>
                {product.modelled_product_id
                  ? `${product.modelled_product_category ?? product.modelled_product_id}`
                  : APPLICABILITY_LABEL[product.product_applicability]}
              </span>
              {product.modelled_product_id && (
                <Mono muted className="mt-0.5 block text-[10px]">
                  {APPLICABILITY_LABEL[product.product_applicability].toLowerCase()}
                </Mono>
              )}
            </DefinitionRow>
          )}
        </dl>
      ) : (
        <p className="px-5 py-4 text-[13px] leading-relaxed text-review">
          {product.reason}
        </p>
      )}

      {product.evidence.length > 0 && (
        <div className="border-t border-line">
          <div className="kicker px-5 pt-3">Evidence from the package</div>
          <ul>
            {product.evidence.map((ev, i) => (
              <li key={`${ev.clue.kind}-${ev.clue.text}-${i}`}>
                <EvidenceRow evidence={ev} selected={selected} onSelect={onSelect} divider={i > 0} />
              </li>
            ))}
          </ul>
        </div>
      )}

      {product.vision_status !== "NOT_RUN" && (
        <div className="border-t border-line px-5 py-3">
          <div className="kicker mb-2">Visual observation</div>
          {seen.length === 0 ? (
            <p className="text-[12px] leading-relaxed text-ink-faint">
              {/* The backend reason already ends with what was used instead. */}
              {vision[0]?.reason ??
                "Visual understanding unavailable — OCR and deterministic identification were used."}
            </p>
          ) : (
            <>
              {seen.map((v) => (
                <div key={v.image_id + v.side} className="mb-2 last:mb-0">
                  <p className="text-[13px] leading-relaxed text-ink">
                    {v.visual_observations[0] ?? `Appears to be ${v.product_label.toLowerCase()}.`}
                  </p>
                  <Mono muted className="mt-0.5 block text-[10px] uppercase tracking-[0.1em]">
                    {v.side} · unverified AI observation · {v.model}
                    {v.confidence ? ` · model confidence ${v.confidence.toFixed(2)}` : ""}
                  </Mono>
                  {v.scrubbed && (
                    <p className="mt-1 text-[11px] leading-relaxed text-review">
                      The model wrote something resembling a declared value; MetrIQ removed it. Only OCR
                      evidence may report such values.
                    </p>
                  )}
                </div>
              ))}
              <p className="mt-1.5 text-[11px] leading-relaxed text-ink-faint">
                {signals.conflicts.length > 0
                  ? "This disagrees with the package text, so the product is reported as needing review."
                  : signals.agreement
                    ? "Agrees with the product read from the package text. Agreement supports the identification; it adds no verified evidence."
                    : "Used only to help identify the product. It is not evidence, not a declaration and not a compliance result."}
              </p>
            </>
          )}
        </div>
      )}

      {(signals.ocr_supported || signals.vision_supported) && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-line px-5 py-2.5">
          <span className="kicker">Support</span>
          {[
            ["OCR text", signals.ocr_supported],
            ["Visual", signals.vision_supported],
            ["Knowledge base", signals.knowledge_supported],
          ].map(([label, on]) => (
            <Mono
              key={String(label)}
              muted
              className={cn("text-[10px] uppercase tracking-[0.1em]", on && "text-accent")}
            >
              {on ? "✓" : "—"} {label}
            </Mono>
          ))}
        </div>
      )}

      {signals.conflicts.length > 0 && (
        <ul className="space-y-1 border-t border-line px-5 py-3 text-[12px] leading-relaxed text-review">
          {signals.conflicts.map((c, i) => (
            <li key={i}>· {c}</li>
          ))}
        </ul>
      )}

      {product.notes.length > 0 && (
        <ul className="space-y-1 border-t border-line px-5 py-3 text-[12px] text-review">
          {product.notes.map((n, i) => (
            <li key={i}>· {n}</li>
          ))}
        </ul>
      )}
      <p className="border-t border-line px-5 py-3 text-[11px] leading-relaxed text-ink-faint">
        {matched
          ? "The best-supported product in the verified knowledge base — not a compliance, certification or conformity decision."
          : "MetrIQ only names products that exist in its verified BIS knowledge base. It never guesses one."}
      </p>
    </Panel>
  );
}

const TIER_LABEL: Record<StandardCandidate["tier"], string> = {
  product: "Product match",
  alias: "Keyword only",
  category: "Category only",
  standard_number: "Printed number only",
};

function StandardCandidatesPanel({
  standards,
  product,
  note,
  selected,
  onSelect,
}: {
  standards: StandardCandidate[];
  product: ProductIdentification;
  note: string;
  selected: string[];
  onSelect: (ids: string[]) => void;
}) {
  return (
    <Panel flush>
      <PanelHeader
        title="BIS standard candidates"
        meta={`${standards.length} ${standards.length === 1 ? "candidate" : "candidates"}`}
      />
      <p className="border-b border-line px-5 py-2.5 text-[11px] leading-relaxed text-ink-faint">
        {note}
      </p>

      {product.unverified_standard_numbers.length > 0 && (
        <p className="border-b border-line px-5 py-3 text-[12px] text-review">
          Printed on the package but not in the verified knowledge base, so not
          shown as a standard: {product.unverified_standard_numbers.join(", ")}
        </p>
      )}

      {standards.length === 0 ? (
        <p className="px-5 py-4 text-[13px] text-ink-soft">
          No verified standard in the knowledge base is supported by this label.
          MetrIQ never generates an IS number.
        </p>
      ) : (
        <ol>
          {standards.map((c, i) => {
            const best =
              product.status === "MATCHED" && c.standard_number === product.standard_number;
            const topReasons = [...c.reasons].sort((a, b) => b.weight - a.weight).slice(0, 4);
            return (
              <li key={c.id} className={cn("relative", i > 0 && "border-t border-line")}>
                {best && <span className="absolute inset-y-0 left-0 w-[2px] bg-accent" aria-hidden />}
                <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-3">
                      <Mono muted className="text-[11px] tabular-nums">
                        {String(i + 1).padStart(2, "0")}
                      </Mono>
                      <Link to={passportPath(c.id)} className="hover:underline">
                        <Mono className="text-[14px] font-semibold text-accent">
                          {c.standard_number}
                        </Mono>
                      </Link>
                      <Mono
                        className={cn(
                          "text-[10px] uppercase tracking-[0.1em]",
                          best ? "text-accent" : c.tier === "product" ? "text-ink-soft" : "text-review",
                        )}
                      >
                        {best ? "Best-supported candidate" : TIER_LABEL[c.tier]}
                        {c.printed_on_label ? " · printed on label" : ""}
                      </Mono>
                    </div>
                    <div className="mt-1.5 text-[14px] font-medium text-ink">
                      {standardTitle(c.title)}
                    </div>
                    <p className="mt-1 text-[11px] text-ink-faint">
                      {c.source_organization}
                      {c.document_name ? ` · ${c.document_name}` : ""}
                      {c.last_verified ? ` · verified ${c.last_verified}` : ""}
                    </p>
                    <EditionCurrency currency={c.currency} className="mt-3" />
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <ConfidenceMeter confidence={c.confidence} />
                    <Mono muted className="text-[10px]">
                      retrieval · score {c.score.toFixed(1)}
                    </Mono>
                  </div>
                </div>

                <ul className="mt-3 border-t border-line">
                  {c.evidence.map((ev, j) => (
                    <li key={`${ev.clue.text}-${j}`}>
                      <EvidenceRow evidence={ev} selected={selected} onSelect={onSelect} divider={j > 0} />
                    </li>
                  ))}
                </ul>

                <div className="border-t border-line bg-surface px-5 py-4">
                  <div className="eyebrow mb-2 !text-ink-faint">Why this result</div>
                  <p className="text-[13px] leading-relaxed text-ink">{c.why.summary}</p>
                  {topReasons.length > 0 && (
                    <>
                      <div className="kicker mb-2 mt-3">Retrieval signals</div>
                      <ul className="divide-y divide-line border-y border-line">
                        {topReasons.map((reason, k) => (
                          <li
                            key={`${reason.field}-${reason.term}-${k}`}
                            className="flex items-baseline gap-3 py-2 text-[12px] text-ink-soft"
                          >
                            <Mono muted className="w-24 shrink-0 text-[10px] uppercase tracking-[0.1em]">
                              {reason.field}
                            </Mono>
                            <span className="min-w-0 flex-1">
                              term <Mono>{reason.term}</Mono>
                              {reason.detail ? ` — ${reason.detail}` : ""}
                            </span>
                            <Mono className="shrink-0 text-[11px] text-accent">+{reason.weight}</Mono>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                  {c.source_url && (
                    <a
                      href={c.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="group/src mt-3 inline-flex items-center gap-1.5 text-[12px] font-medium text-accent hover:text-accent-hover"
                    >
                      Official BIS source
                      <ArrowUpRight className="h-3.5 w-3.5 transition-transform group-hover/src:translate-x-0.5" />
                    </a>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </Panel>
  );
}

const COMPLETENESS_LABEL: Record<DeclarationCompleteness["items"][number]["status"], string> = {
  DETECTED: "Detected",
  UNCERTAIN: "Uncertain",
  NOT_DETECTED: "Not detected",
};

/** Declaration completeness across every uploaded photo of the package. */
function CompletenessPanel({
  completeness,
  selected,
  onSelect,
}: {
  completeness: DeclarationCompleteness;
  selected: string[];
  onSelect: (ids: string[]) => void;
}) {
  const where = useWhere();
  return (
    <CollapsiblePanel
      title="What the photos did and did not show"
      meta={`${completeness.detected} detected · ${completeness.uncertain} uncertain · ${completeness.not_detected} not detected`}
    >
      <p className="border-b border-line px-5 py-2.5 text-[11px] leading-relaxed text-ink-faint">
        {completeness.note}
        {completeness.with_verified_requirement === 0 &&
          " No field is linked to a verified, checkable requirement for this package."}
      </p>
      {completeness.unreadable_images.length > 0 && (
        <p className="border-b border-line px-5 py-2.5 text-[12px] text-review">
          No usable OCR evidence from {completeness.unreadable_images.join(", ")} — declarations on
          {completeness.unreadable_images.length === 1 ? " that photo" : " those photos"} cannot be determined.
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-[12px]">
          <thead>
            <tr className="border-b border-line">
              {["Declaration", "Observation", "Value / source", "Verified requirement"].map((h) => (
                <th key={h} className="kicker px-5 py-2 font-normal">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {completeness.items.map((item) => {
              const clickable = item.source_regions.length > 0;
              const active =
                clickable &&
                item.source_regions.length === selected.length &&
                item.source_regions.every((id, i) => selected[i] === id);
              return (
                <tr
                  key={item.field}
                  onClick={clickable ? () => onSelect(item.source_regions) : undefined}
                  className={cn(
                    "border-b border-line align-top last:border-b-0",
                    clickable && "cursor-pointer hover:bg-surface",
                    active && "bg-accent-soft",
                  )}
                >
                  <td className="px-5 py-2.5 text-ink">{item.label}</td>
                  <td className="px-5 py-2.5">
                    <Mono
                      className={cn(
                        "text-[10px] uppercase tracking-[0.1em]",
                        item.status === "DETECTED" ? "text-accent" : item.status === "UNCERTAIN" ? "text-review" : "text-ink-faint",
                      )}
                    >
                      {item.conflict ? "Conflict" : COMPLETENESS_LABEL[item.status]}
                    </Mono>
                  </td>
                  <td className="px-5 py-2.5">
                    {item.value && <div className="text-ink">{item.value}</div>}
                    {clickable && (
                      <Mono muted className="block text-[10px]">
                        {where(item.source_regions)}
                        {item.ocr_confidence !== null ? ` · OCR ${Math.round(item.ocr_confidence * 100)}%` : ""}
                      </Mono>
                    )}
                    <div className={cn("text-[11px] leading-snug", item.status === "DETECTED" ? "text-ink-faint" : "text-review")}>
                      {item.status === "DETECTED" ? null : item.statement}
                    </div>
                  </td>
                  <td className="px-5 py-2.5">
                    {item.requirement_coverage === "VERIFIED_REQUIREMENT" ? (
                      <Mono className="text-[10px] text-ink">{item.requirement_ids.join(", ")}</Mono>
                    ) : (
                      <Mono className="text-[10px] text-ink-faint">
                        —
                      </Mono>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </CollapsiblePanel>
  );
}

function DownstreamPanel({ result }: { result: InspectionAnalysis }) {
  const p = result.pipeline;
  const rows: [string, string, string][] = [
    ["OCR", "Local PaddleOCR text detection", p.ocr],
    [
      "Declaration extraction",
      "Deterministic parse of OCR text into declared fields",
      p.declaration_extraction,
    ],
    [
      "Product identification",
      result.product.method === "model_assisted"
        ? "Knowledge-base retrieval; search term suggested by the local model"
        : "Deterministic retrieval over the verified BIS knowledge base",
      p.product_identification,
    ],
    [
      "Standard candidates",
      "Verified knowledge-base records only — never generated",
      p.standard_retrieval,
    ],
  ];
  return (
    <CollapsiblePanel title="How the pipeline ran" meta="OCR → standard">
      <ul>
        {rows.map(([k, v, status], i) => (
          <li
            key={k}
            className={cn(
              "flex items-baseline justify-between gap-4 px-5 py-3",
              i > 0 && "border-t border-line",
            )}
          >
            <div>
              <div className="text-[13px] font-medium text-ink-soft">{k}</div>
              <div className="text-[12px] text-ink-faint">{v}</div>
            </div>
            <Mono
              className={cn(
                "shrink-0 text-[10px] uppercase tracking-[0.1em]",
                stageTone(status),
              )}
            >
              {status}
            </Mono>
          </li>
        ))}
      </ul>
    </CollapsiblePanel>
  );
}

function RawTextPanel({
  text,
  title = "Raw OCR text",
  open,
}: {
  text: string;
  title?: string;
  open?: boolean;
}) {
  return (
    <CollapsiblePanel defaultOpen={open} title={title} meta="verbatim">
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap px-5 py-4 font-mono text-[12px] leading-relaxed text-ink">
        {text || "— no text —"}
      </pre>
    </CollapsiblePanel>
  );
}

