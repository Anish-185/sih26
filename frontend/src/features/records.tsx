/*
  Shared pieces for saved inspections (Inspection workspace, History, inspection
  detail, Dashboard). MetrIQ produces no automatic compliance verdict — what is
  shown here is only whether the deterministic system could RESOLVE the case
  from the photographed evidence, and why not when it couldn't. MetrIQ records
  no human decision either.
*/
import { Mono, Panel, PanelHeader } from "@/components/ui";
import { cn } from "@/lib/cn";
import type { EscalationReason, InspectionSummary } from "@/lib/api";

const SOURCE_LABEL: Record<EscalationReason["source"], string> = {
  OCR: "OCR evidence",
  PRODUCT: "Product",
  HALLMARKING: "Hallmarking",
  PIPELINE: "Pipeline",
};

/** Did the deterministic system resolve this inspection from the photos, or not? */
export function ResolutionMark({ required }: { required: boolean }) {
  return (
    <Mono className={cn("text-[11px] uppercase tracking-[0.08em]", required ? "text-review" : "text-ink-soft")}>
      {required ? "Not fully established" : "Resolved by system"}
    </Mono>
  );
}

export function productLabel(record: InspectionSummary): string {
  return record.product_name ?? "Product not identified";
}

/** Unique reason labels, for a compact "what could not be established" cell. */
export function reasonLabels(reasons: EscalationReason[]): string[] {
  return [...new Set(reasons.map((r) => r.label))];
}

/* --------------------------------------------------------- resolution --- */

type Step = { label: string; detail?: React.ReactNode; state: "done" | "current" | "todo" };

/**
 * The deterministic path: evidence → could every part of the evidence chain be
 * established from the photos? → resolved, or a stated list of what MetrIQ
 * could not establish. No verdict and no decision is produced here.
 */
export function ResolutionPanel({
  required,
  reasons,
  selected = [],
  onSelect,
}: {
  required: boolean;
  reasons: EscalationReason[];
  selected?: string[];
  onSelect?: (ids: string[]) => void;
}) {
  const steps: Step[] = [
    { label: "Deterministic evidence", detail: <Mono muted>OCR → declarations → identification</Mono>, state: "done" },
    {
      label: "Established from the photos?",
      detail: <span className={required ? "text-review" : "text-ink"}>{required ? "Not completely" : "Yes"}</span>,
      state: "done",
    },
    required
      ? { label: "Needs verification outside MetrIQ", state: "current" }
      : { label: "Resolved by MetrIQ", state: "done" },
  ];

  return (
    <Panel flush>
      <PanelHeader
        title="How MetrIQ reached this result"
        meta={<ResolutionMark required={required} />}
      />
      <ol className="flex flex-wrap items-stretch gap-px border-b border-line bg-line">
        {steps.map((s, i) => (
          <li
            key={s.label}
            className={cn(
              "flex min-w-[9rem] flex-1 flex-col gap-1 bg-raised px-4 py-3",
              s.state === "current" && "bg-accent-soft",
              s.state === "todo" && "opacity-60",
            )}
          >
            <Mono muted className="text-[10px] uppercase tracking-[0.1em]">
              {String(i + 1).padStart(2, "0")}
            </Mono>
            <span className="text-[12px] font-medium text-ink">{s.label}</span>
            {s.detail && <span className="text-[12px]">{s.detail}</span>}
          </li>
        ))}
      </ol>

      <p className="px-5 py-3 text-[12px] leading-relaxed text-ink-soft">
        {required
          ? "MetrIQ could not establish every part of the evidence chain from these photos. Each thing it could not establish is listed below — MetrIQ states them rather than deciding them."
          : "Every part of the evidence chain MetrIQ needed was decided on clear evidence from the photos."}
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
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
