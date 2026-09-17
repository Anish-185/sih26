import { Link } from "react-router-dom";
import { ArrowUpRight } from "lucide-react";
import { Callout, EmptyState, InlineLoading, LinkButton, Mono, PageHeader, StatusBadge } from "@/components/ui";
import { HeaderMotif } from "@/components/decor";
import { ApiError, api } from "@/lib/api";
import { useOnMount } from "@/lib/hooks";
import { formatDate } from "@/lib/format";
import { FinalDecision, OfficerStatusMark, productLabel } from "./records";

// Stable reference: useOnMount re-runs when its task changes.
const loadHistory = () => api.listInspections();

export function HistoryView() {
  const { data, error, loading } = useOnMount(loadHistory);
  const rows = data?.items ?? [];

  return (
    <div className="space-y-10">
      <div className="relative">
        <HeaderMotif name="mountain" label={data ? `${data.total} records` : "records"} width="w-[26%]" />
        <PageHeader
          eyebrow="History"
          title="Inspection history"
          lead="Every saved inspection: the result MetrIQ's deterministic checks produced, and the officer's review of it — kept separately."
        />
      </div>

      {loading && <InlineLoading label="Loading inspections" />}

      {error != null && (
        <Callout tone="abstain" title="Inspection history is unavailable">
          {error instanceof ApiError ? error.detail : "The inspection history could not be loaded."}
        </Callout>
      )}

      {data && rows.length === 0 && (
        <EmptyState
          title="No inspections recorded yet."
          description="Run an inspection and save it for officer review — it will appear here."
          action={
            <LinkButton to="/inspection" size="sm">
              Start an inspection
            </LinkButton>
          }
        />
      )}

      {rows.length > 0 && (
        <div className="overflow-x-auto border border-line">
          <table className="w-full min-w-[860px] border-collapse text-left">
            <thead>
              <tr className="border-b border-line bg-surface">
                {["Inspection", "Date", "Product", "BIS standard", "System result", "Officer status", "Final decision"].map(
                  (h) => (
                    <th key={h} className="kicker px-4 py-3 font-normal first:pl-5 last:pr-5">
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((ins) => (
                <tr
                  key={ins.inspection_id}
                  className="group border-b border-line last:border-0 transition-colors hover:bg-surface"
                >
                  <td className="px-4 py-3.5 pl-5">
                    <Link
                      to={`/history/${ins.inspection_id}`}
                      className="inline-flex items-center gap-1 font-mono text-[12px] text-accent hover:text-accent-hover"
                    >
                      {ins.inspection_id}
                      <ArrowUpRight className="h-3 w-3 opacity-0 transition-opacity group-hover:opacity-100" />
                    </Link>
                  </td>
                  <td className="px-4 py-3.5 text-[12px] text-ink-soft">{formatDate(ins.created_at)}</td>
                  <td className="px-4 py-3.5 text-[13px] font-medium">
                    <span className={ins.product_name ? undefined : "font-normal text-review"}>{productLabel(ins)}</span>
                  </td>
                  <td className="px-4 py-3.5">
                    <Mono muted className="text-[12px]">
                      {ins.standard_number ?? "—"}
                    </Mono>
                  </td>
                  <td className="px-4 py-3.5">
                    <StatusBadge status={ins.system_result} size="sm" />
                  </td>
                  <td className="px-4 py-3.5">
                    <OfficerStatusMark status={ins.officer_status} />
                  </td>
                  <td className="px-4 py-3.5 pr-5">
                    <FinalDecision record={ins} />
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
