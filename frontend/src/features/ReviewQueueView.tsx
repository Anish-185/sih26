import { Callout, EmptyState, InlineLoading, LinkButton, Mono, PageHeader, StatusBadge } from "@/components/ui";
import { HeaderMotif } from "@/components/decor";
import { ApiError, api } from "@/lib/api";
import { useOnMount } from "@/lib/hooks";
import { formatDateTime } from "@/lib/format";
import { OfficerStatusMark, productLabel, reasonLabels } from "./records";

// Stable reference: useOnMount re-runs when its task changes.
const loadQueue = () => api.listInspections(["PENDING", "IN_REVIEW"]);

/** Inspections waiting for an officer (PENDING and IN_REVIEW), newest first. */
export function ReviewQueueView() {
  const { data, error, loading } = useOnMount(loadQueue);
  const rows = data?.items ?? [];

  return (
    <div className="space-y-10">
      <div className="relative">
        <HeaderMotif name="mountain" label={data ? `${data.total} awaiting` : "queue"} width="w-[26%]" />
        <PageHeader
          eyebrow="Officer review"
          title="Pending reviews"
          lead="Officer review is the final escalation step. Only inspections the automated checks could not confidently resolve are sent here; the system result is shown as MetrIQ produced it, and the officer records a separate, final decision."
        />
      </div>

      {loading && <InlineLoading label="Loading the review queue" />}

      {error != null && (
        <Callout tone="abstain" title="The review queue is unavailable">
          {error instanceof ApiError ? error.detail : "The review queue could not be loaded."}
        </Callout>
      )}

      {data && rows.length === 0 && (
        <EmptyState
          title="No inspections awaiting officer review."
          description="Inspections the system cannot resolve by itself appear here until an officer completes their review. Inspections the system resolved go straight to history."
        />
      )}

      {rows.length > 0 && (
        <div className="overflow-x-auto border border-line">
          <table className="w-full min-w-[960px] border-collapse text-left">
            <thead>
              <tr className="border-b border-line bg-surface">
                {["Inspection", "Product", "System result", "Why escalated", "Created", "Status", "Action"].map((h) => (
                  <th key={h} className="kicker px-4 py-3 font-normal first:pl-5 last:pr-5">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((ins) => (
                <tr key={ins.inspection_id} className="border-b border-line last:border-0">
                  <td className="px-4 py-3.5 pl-5">
                    <Mono className="text-[12px]">{ins.inspection_id}</Mono>
                  </td>
                  <td className="px-4 py-3.5 text-[13px] font-medium">
                    <span className={ins.product_name ? undefined : "font-normal text-review"}>{productLabel(ins)}</span>
                  </td>
                  <td className="px-4 py-3.5">
                    <StatusBadge status={ins.system_result} size="sm" />
                  </td>
                  <td className="max-w-[18rem] px-4 py-3.5 text-[12px] leading-snug text-ink-soft">
                    {reasonLabels(ins.escalation_reasons).join(" · ") || "—"}
                  </td>
                  <td className="px-4 py-3.5 text-[12px] text-ink-soft">{formatDateTime(ins.created_at)}</td>
                  <td className="px-4 py-3.5">
                    <OfficerStatusMark status={ins.officer_status} />
                  </td>
                  <td className="px-4 py-3.5 pr-5">
                    <LinkButton to={`/history/${ins.inspection_id}`} size="sm" variant="secondary">
                      Review
                    </LinkButton>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
