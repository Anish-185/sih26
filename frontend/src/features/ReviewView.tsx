import { type ReactNode, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Check, ClipboardCheck, FileText, Pencil, Search } from "lucide-react";
import { cn } from "@/lib/cn";
import {
  Button,
  Callout,
  DefinitionRow,
  InlineLoading,
  LinkButton,
  Mono,
  PageHeader,
  Panel,
  PanelHeader,
  StatusBadge,
  TextArea,
} from "@/components/ui";
import {
  ApiError,
  api,
  inspectionImageUrl,
  inspectionReportUrl,
  type InspectionRecord,
  type OfficerDecision,
  type ReviewInput,
  type SystemResult,
} from "@/lib/api";
import { useAsyncTask } from "@/lib/hooks";
import { formatDateTime } from "@/lib/format";
import { CopilotPanel } from "./CopilotPanel";
import { Workspace } from "./inspection/InspectionView";
import { DECISION_LABEL, EscalationPanel, OFFICER_STATUS_LABEL, OfficerStatusMark, productLabel } from "./records";

const NOTE_MAX = 2000;
const AUTHORITY: Record<string, string> = {
  BIS: "BIS compliance",
  LEGAL_METROLOGY: "Legal Metrology package label",
  HALLMARKING: "Hallmarking (not verified)",
};

/** A saved inspection: the fixed system result, its evidence, and the officer review. */
export function ReviewView() {
  const { inspectionId = "" } = useParams();
  const load = useAsyncTask(api.getInspection);
  const [record, setRecord] = useState<InspectionRecord | null>(null);
  const [activeImageId, setActiveImageId] = useState<string | null>(null);
  const [selection, setSelection] = useState<string[]>([]);

  const { run } = load;
  useEffect(() => {
    setRecord(null);
    run(inspectionId)
      .then(setRecord)
      .catch(() => {});
  }, [inspectionId, run]);

  if (load.loading && !record) return <InlineLoading label={`Loading ${inspectionId}`} />;

  if (!record) {
    const err = load.error;
    const notFound = err instanceof ApiError && (err.status === 404 || err.status === 422);
    return (
      <div className="space-y-8 py-6">
        <PageHeader
          eyebrow="Officer review"
          title={notFound ? "Inspection not found" : "Inspection unavailable"}
          lead={
            notFound
              ? "No saved inspection matches this identifier."
              : err instanceof ApiError
                ? err.detail
                : "The inspection could not be loaded."
          }
        />
        <LinkButton to="/history" variant="secondary" size="lg">
          Back to history
        </LinkButton>
      </div>
    );
  }

  const analysis = record.analysis;
  const images = analysis.images;
  function selectRegions(ids: string[]) {
    setSelection(ids);
    const img = images.find((i) => i.ocr?.regions.some((r) => r.id === ids[0]));
    if (img) setActiveImageId(img.image_id);
  }

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow={`Saved inspection · ${record.inspection_id}`}
        title={productLabel(record)}
        lead={`Saved ${formatDateTime(record.created_at)} · ${record.image_count} ${record.image_count === 1 ? "photo" : "photos"}${record.standard_number ? ` · ${record.standard_number}` : ""}`}
        actions={
          <div className="flex flex-wrap items-center justify-end gap-4">
            <ReportButton inspectionId={record.inspection_id} />
            <Link
              to="/review"
              className="inline-flex items-center gap-1 font-mono text-[11px] uppercase tracking-[0.14em] text-accent hover:text-accent-hover"
            >
              Review queue
            </Link>
            <Link
              to="/history"
              className="inline-flex items-center gap-1 font-mono text-[11px] uppercase tracking-[0.14em] text-accent hover:text-accent-hover"
            >
              All inspections
            </Link>
          </div>
        }
      />

      <EscalationPanel
        required={record.escalation_required}
        systemResult={record.system_result}
        reasons={record.escalation_reasons}
        officerStatus={record.officer_status}
        selected={selection}
        onSelect={selectRegions}
      />

      <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
        <SystemResultPanel record={record} />
        <OfficerReviewPanel record={record} onSaved={setRecord} />
      </div>

      <CopilotPanel
        inspectionId={record.inspection_id}
        systemResult={record.system_result}
        hasHallmark={Boolean(analysis.hallmark?.detected)}
      />

      <Workspace
        result={analysis}
        urls={record.images.map((i) => inspectionImageUrl(i.url))}
        activeImageId={activeImageId ?? images[0].image_id}
        setActiveImageId={setActiveImageId}
        selectedRegion={selection[0] ?? null}
        setSelectedRegion={(id) => selectRegions(id ? [id] : [])}
        linkedRegions={selection}
        selectRegions={selectRegions}
        hideEscalation
        hideCopilot
        intro={
          <Callout>
            <span className="font-medium">Saved evidence.</span> Everything below is the deterministic
            analysis stored when this inspection was saved — OCR regions on the stored photos,
            declarations, the BIS standard and the Legal Metrology package-label checks, each with its
            source. Select a declaration or a check to see its OCR box on the photo. It does not change
            when the officer reviews it.
          </Callout>
        }
      />
    </div>
  );
}

/* ---------------------------------------------------------------- report --- */

/** Opens the evidence-backed PDF report, generated by the backend from the stored record. */
function ReportButton({ inspectionId }: { inspectionId: string }) {
  return (
    <LinkButton to={inspectionReportUrl(inspectionId)} external variant="secondary" size="sm">
      <FileText className="h-3.5 w-3.5" />
      View report
    </LinkButton>
  );
}

/* -------------------------------------------------------- system result --- */

function SystemResultPanel({ record }: { record: InspectionRecord }) {
  const lmNotCheckable = record.system_reasons.some(
    (r) => r.source === "LEGAL_METROLOGY" && r.reason_code === "REQUIREMENTS_NOT_CHECKABLE",
  );
  return (
    <Panel flush>
      <PanelHeader title="System result" meta="fixed when saved" />
      <dl className="px-5 py-2">
        <DefinitionRow label="Overall">
          <StatusBadge status={record.system_result} />
          <p className="mt-1.5 text-[12px] leading-relaxed text-ink-soft">
            FAIL if any applicable evidence system failed; PASS only if all passed; otherwise REVIEW.
          </p>
        </DefinitionRow>
        {record.system_reasons.map((r) => (
          <DefinitionRow key={r.source} label={AUTHORITY[r.source] ?? r.source}>
            <StatusBadge status={r.result} size="sm" />
            <p className="mt-1.5 text-[12px] leading-relaxed text-ink-soft">{r.reason}</p>
            <Mono muted className="mt-0.5 block text-[10px]">
              {r.reason_code}
            </Mono>
          </DefinitionRow>
        ))}
      </dl>
      {record.system_result === "REVIEW" && record.escalation_required && (
        <p className="border-t border-line px-5 py-3 text-[12px] leading-relaxed text-ink-soft">
          REVIEW is not a failure. It means the photos could not establish every applicable requirement
          {lmNotCheckable ? " — some Legal Metrology requirement areas cannot be checked from an image at all" : ""}.
          The officer review exists for exactly this: verify against the evidence or the physical package.
        </p>
      )}
    </Panel>
  );
}

/* -------------------------------------------------------- officer review --- */

const RESULTS: SystemResult[] = ["PASS", "FAIL", "REVIEW"];

function OfficerReviewPanel({
  record,
  onSaved,
}: {
  record: InspectionRecord;
  onSaved: (r: InspectionRecord) => void;
}) {
  const task = useAsyncTask(api.reviewInspection);
  const [decision, setDecision] = useState<OfficerDecision | null>(null);
  const [officerResult, setOfficerResult] = useState<SystemResult | null>(null);
  const [note, setNote] = useState("");

  function submit(body: ReviewInput) {
    task
      .run(record.inspection_id, body)
      .then(onSaved)
      .catch(() => {});
  }

  const trimmed = note.trim();
  const needsNote = decision === "OVERRIDE" || decision === "MANUAL_REVIEW";
  const ready =
    decision !== null &&
    (!needsNote || trimmed.length > 0) &&
    (decision !== "OVERRIDE" || officerResult !== null) &&
    trimmed.length <= NOTE_MAX;

  return (
    <Panel flush>
      <PanelHeader title="Officer review" meta={<OfficerStatusMark status={record.officer_status} />} />
      <dl className="px-5 py-2">
        <DefinitionRow label="Status">{OFFICER_STATUS_LABEL[record.officer_status]}</DefinitionRow>
        <DefinitionRow label="Started">
          {record.review_started_at ? formatDateTime(record.review_started_at) : <Mono muted>—</Mono>}
        </DefinitionRow>
        {record.officer_status === "COMPLETED" && record.officer_decision && (
          <>
            <DefinitionRow label="Completed">
              {record.review_completed_at && formatDateTime(record.review_completed_at)}
            </DefinitionRow>
            <DefinitionRow label="Decision">{DECISION_LABEL[record.officer_decision]}</DefinitionRow>
            <DefinitionRow label="Final result">
              {record.final_result === "MANUAL_REVIEW" || !record.final_result ? (
                <span className="text-review">Manual verification required</span>
              ) : (
                <StatusBadge status={record.final_result} size="sm" />
              )}
            </DefinitionRow>
            <DefinitionRow label="Officer note">
              {record.officer_note ? (
                <p className="whitespace-pre-wrap text-[13px] leading-relaxed">{record.officer_note}</p>
              ) : (
                <Mono muted>—</Mono>
              )}
            </DefinitionRow>
          </>
        )}
      </dl>

      {record.officer_status === "NOT_REQUIRED" && (
        <div className="border-t border-line px-5 py-4 text-[12px] leading-relaxed text-ink-soft">
          <p>
            <span className="font-medium text-ink">No officer review required.</span> The system resolved this
            inspection on clear evidence, so it was never sent to the officer queue. The final result is the
            system result:
          </p>
          <div className="mt-2">
            <StatusBadge status={record.system_result} size="sm" />
          </div>
        </div>
      )}

      {record.officer_status === "PENDING" && (
        <div className="border-t border-line px-5 py-4">
          <p className="mb-3 text-[12px] leading-relaxed text-ink-soft">
            Inspect the evidence below, then start the review to record a decision.
          </p>
          <Button size="sm" onClick={() => submit({ action: "START" })} disabled={task.loading}>
            <ClipboardCheck className="h-3.5 w-3.5" />
            Start review
          </Button>
        </div>
      )}

      {record.officer_status === "IN_REVIEW" && (
        <div className="space-y-3 border-t border-line px-5 py-4">
          <div className="kicker">Decision</div>
          <div className="flex flex-wrap gap-2">
            <DecisionButton
              active={decision === "ACCEPT_SYSTEM_RESULT"}
              onClick={() => setDecision("ACCEPT_SYSTEM_RESULT")}
              icon={<Check className="h-3.5 w-3.5" />}
            >
              Accept {record.system_result}
            </DecisionButton>
            <DecisionButton
              active={decision === "OVERRIDE"}
              onClick={() => setDecision("OVERRIDE")}
              icon={<Pencil className="h-3.5 w-3.5" />}
            >
              Override
            </DecisionButton>
            <DecisionButton
              active={decision === "MANUAL_REVIEW"}
              onClick={() => setDecision("MANUAL_REVIEW")}
              icon={<Search className="h-3.5 w-3.5" />}
            >
              Manual review
            </DecisionButton>
          </div>

          {decision === "OVERRIDE" && (
            <div>
              <div className="kicker mb-1.5">Officer result</div>
              <div className="flex gap-2">
                {RESULTS.filter((r) => r !== record.system_result).map((r) => (
                  <DecisionButton key={r} active={officerResult === r} onClick={() => setOfficerResult(r)}>
                    {r}
                  </DecisionButton>
                ))}
              </div>
            </div>
          )}

          <div>
            <label className="kicker mb-1.5 block" htmlFor="officer-note">
              Officer note{needsNote ? " (required)" : " (optional)"}
            </label>
            <TextArea
              id="officer-note"
              rows={3}
              maxLength={NOTE_MAX}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. Verified against physical package."
            />
          </div>

          <Button
            size="sm"
            className="w-full"
            disabled={!ready || task.loading}
            onClick={() =>
              decision &&
              submit({
                action: "COMPLETE",
                decision,
                ...(decision === "OVERRIDE" && officerResult ? { officer_result: officerResult } : {}),
                ...(trimmed ? { note: trimmed } : {}),
              })
            }
          >
            {task.loading ? "Saving…" : "Save decision"}
          </Button>
          <p className="text-[11px] leading-relaxed text-ink-faint">
            The decision is recorded next to the system result, which stays {record.system_result}. A completed
            review is final.
          </p>
        </div>
      )}

      {record.officer_status === "COMPLETED" && (
        <p className="border-t border-line px-5 py-3 text-[11px] leading-relaxed text-ink-faint">
          Review completed. The system result above is unchanged; this decision is recorded separately.
        </p>
      )}

      {task.error != null && (
        <p className="border-t border-line px-5 py-3 text-[12px] text-review">
          {task.error instanceof ApiError ? task.error.detail : "The review could not be saved."}
        </p>
      )}
    </Panel>
  );
}

function DecisionButton({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean;
  onClick: () => void;
  icon?: ReactNode;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-sm border px-3 py-1.5 text-[12px] font-medium transition-colors",
        active ? "border-accent bg-accent-soft text-accent" : "border-line-strong text-ink-soft hover:border-ink hover:text-ink",
      )}
    >
      {icon}
      {children}
    </button>
  );
}
