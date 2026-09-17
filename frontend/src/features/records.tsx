/*
  Shared pieces for saved inspections (History, Review queue, inspection detail,
  Dashboard). The system result and the officer review are always shown as two
  separate things.
*/
import { Mono, StatusBadge } from "@/components/ui";
import { cn } from "@/lib/cn";
import type { InspectionSummary, OfficerDecision, OfficerStatus } from "@/lib/api";

export const OFFICER_STATUS_LABEL: Record<OfficerStatus, string> = {
  PENDING: "Pending",
  IN_REVIEW: "In review",
  COMPLETED: "Completed",
};

export const DECISION_LABEL: Record<OfficerDecision, string> = {
  ACCEPT_SYSTEM_RESULT: "Accepted system result",
  OVERRIDE: "Overridden",
  MANUAL_REVIEW: "Manual verification required",
};

export function OfficerStatusMark({ status }: { status: OfficerStatus }) {
  return (
    <Mono
      className={cn(
        "text-[11px] uppercase tracking-[0.08em]",
        status === "COMPLETED" ? "text-ink" : status === "IN_REVIEW" ? "text-accent" : "text-review",
      )}
    >
      {OFFICER_STATUS_LABEL[status]}
    </Mono>
  );
}

/** The officer's final decision, or a dash while the review is open. */
export function FinalDecision({ record }: { record: InspectionSummary }) {
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
