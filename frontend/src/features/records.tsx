/*
  Shared pieces for inspections and their escalation (Inspection workspace, Review
  queue, History, inspection detail, Dashboard). Three things are always shown
  apart: the SYSTEM RESULT, the ESCALATION (did it need an officer?) and the
  OFFICER DECISION.
*/
import { Mono, Panel, PanelHeader, StatusBadge } from "@/components/ui";
import { cn } from "@/lib/cn";
import type {
  EscalationReason,
  InspectionSummary,
  OfficerDecision,
  OfficerStatus,
  SystemResult,
} from "@/lib/api";

export const OFFICER_STATUS_LABEL: Record<OfficerStatus, string> = {
  NOT_REQUIRED: "Not required",
  PENDING: "Pending officer",
  IN_REVIEW: "In review",
  COMPLETED: "Completed",
};

export const DECISION_LABEL: Record<OfficerDecision, string> = {
  ACCEPT_SYSTEM_RESULT: "Accepted system result",
  OVERRIDE: "Overridden",
  MANUAL_REVIEW: "Manual verification required",
};

const SOURCE_LABEL: Record<EscalationReason["source"], string> = {
  OCR: "OCR evidence",
  PRODUCT: "Product",
  BIS: "BIS",
  LEGAL_METROLOGY: "Legal Metrology",
  PIPELINE: "Pipeline",
};

export function OfficerStatusMark({ status }: { status: OfficerStatus }) {
  return (
    <Mono
      className={cn(
        "text-[11px] uppercase tracking-[0.08em]",
        status === "COMPLETED" || status === "NOT_REQUIRED"
          ? "text-ink-soft"
          : status === "IN_REVIEW"
            ? "text-accent"
            : "text-review",
      )}
    >
      {OFFICER_STATUS_LABEL[status]}
    </Mono>
  );
}

/** The final decision: the system's own when no review was needed, the officer's once completed. */
export function FinalDecision({ record }: { record: InspectionSummary }) {
  if (record.officer_status === "NOT_REQUIRED") {
    return (
      <span className="inline-flex flex-wrap items-center gap-2 text-[12px] text-ink-soft">
        Final system result
        <StatusBadge status={record.system_result} size="sm" />
      </span>
    );
  }
  if (!record.officer_decision || !record.final_result) return <Mono muted>—</Mono>;
  return (
    <span className="inline-flex flex-wrap items-center gap-2 text-[12px] text-ink-soft">
      {DECISION_LABEL[record.officer_decision]}
      {record.final_result !== "MANUAL_REVIEW" && record.officer_decision === "OVERRIDE" && (
        <StatusBadge status={record.final_result} size="sm" />
      )}
    </span>
  );
}

export function productLabel(record: InspectionSummary): string {
  return record.product_name ?? "Product not identified";
}

/** Unique reason labels, for a compact "why escalated" cell. */
export function reasonLabels(reasons: EscalationReason[]): string[] {
  return [...new Set(reasons.map((r) => r.label))];
}

/* --------------------------------------------------------- escalation --- */

type Step = { label: string; detail?: React.ReactNode; state: "done" | "current" | "todo" | "skipped" };

/**
 * The escalation decision and its path:
 * system result → can the system resolve it? → final system result | officer queue → decision → final record.
 * `officerStatus` is undefined before the inspection is saved.
 */
export function EscalationPanel({
  required,
  systemResult,
  reasons,
  officerStatus,
  selected = [],
  onSelect,
}: {
  required: boolean;
  systemResult: SystemResult;
  reasons: EscalationReason[];
  officerStatus?: OfficerStatus;
  selected?: string[];
  onSelect?: (ids: string[]) => void;
}) {
  const saved = officerStatus !== undefined;
  const reviewed = officerStatus === "COMPLETED";
  const steps: Step[] = [
    { label: "System result", detail: <StatusBadge status={systemResult} size="sm" />, state: "done" },
    {
      label: "Can the system resolve it?",
      detail: <span className={required ? "text-review" : "text-ink"}>{required ? "No" : "Yes"}</span>,
      state: "done",
    },
    ...(required
      ? ([
          {
            label: "Officer review queue",
            state: !saved ? "todo" : officerStatus === "PENDING" ? "current" : "done",
          },
          {
            label: "Officer decision",
            state: reviewed ? "done" : officerStatus === "IN_REVIEW" ? "current" : "todo",
          },
          { label: "Final record", state: reviewed ? "done" : "todo" },
        ] as Step[])
      : ([
          { label: "Final system result", detail: <StatusBadge status={systemResult} size="sm" />, state: "done" },
          { label: "Officer review", detail: <Mono muted>not required</Mono>, state: "skipped" },
        ] as Step[])),
  ];

  return (
    <Panel flush>
      <PanelHeader
        title="Escalation"
        meta={
          <Mono className={cn("text-[11px] uppercase tracking-[0.08em]", required ? "text-review" : "text-ink-soft")}>
            {required ? "Officer review required" : "Resolved by the system"}
          </Mono>
        }
      />
      <ol className="flex flex-wrap items-stretch gap-px border-b border-line bg-line">
        {steps.map((s, i) => (
          <li
            key={s.label}
            className={cn(
              "flex min-w-[9rem] flex-1 flex-col gap-1 bg-raised px-4 py-3",
              s.state === "current" && "bg-accent-soft",
              (s.state === "todo" || s.state === "skipped") && "opacity-60",
            )}
          >
            <Mono muted className="text-[10px] uppercase tracking-[0.1em]">
              {String(i + 1).padStart(2, "0")}
              {s.state === "current" ? " · now" : ""}
            </Mono>
            <span className="text-[12px] font-medium text-ink">{s.label}</span>
            {s.detail && <span className="text-[12px]">{s.detail}</span>}
          </li>
        ))}
      </ol>

      <p className="px-5 py-3 text-[12px] leading-relaxed text-ink-soft">
        {required
          ? "The automated checks could not confidently resolve this inspection, so it goes to an officer. The system result stays as it is; the officer records a separate, final decision."
          : "Every check the system needed was decided on clear evidence, so the system result is final and no officer review is needed."}
      </p>

      {reasons.length > 0 && (
        <ul className="border-t border-line">
          {reasons.map((r, i) => {
            const clickable = r.source_regions.length > 0 && !!onSelect;
            const active =
              clickable &&
              r.source_regions.length === selected.length &&
              r.source_regions.every((id, j) => selected[j] === id);
            return (
              <li key={`${r.code}-${r.source}-${i}`} className={cn(i > 0 && "border-t border-line")}>
                <button
                  type="button"
                  disabled={!clickable}
                  onClick={clickable ? () => onSelect?.(r.source_regions) : undefined}
                  className={cn(
                    "block w-full px-5 py-3 text-left",
                    clickable && "hover:bg-surface",
                    active && "bg-accent-soft",
                  )}
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-[13px] font-medium text-ink">{r.label}</span>
                    <Mono muted className="text-[10px] uppercase tracking-[0.1em]">
                      {SOURCE_LABEL[r.source]}
                      {clickable ? " · view evidence →" : ""}
                    </Mono>
                  </div>
                  <p className="mt-0.5 text-[12px] leading-relaxed text-ink-soft">{r.message}</p>
                  {!required && r.code === "REQUIREMENT_NOT_CHECKABLE" && (
                    <p className="mt-0.5 text-[11px] text-ink-faint">
                      Listed for the record — it cannot overturn a FAIL established on clear evidence.
                    </p>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
