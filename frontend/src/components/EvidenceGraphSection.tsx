/*
  Loads the evidence graph for what is already on screen and renders it.

  The graph is a projection of evidence MetrIQ has already produced, so it is
  fetched once, on demand, and nothing on the page depends on it: if the request
  fails, the page keeps every result, check, source and limitation it already
  shows.
*/
import { useEffect } from "react";
import { ApiError, api, type EvidenceGraphInput } from "@/lib/api";
import { useAsyncTask } from "@/lib/hooks";
import { InlineLoading } from "@/components/ui";
import { EvidenceGraphPanel } from "@/components/EvidenceGraph";

export function EvidenceGraphSection({
  source,
  onSelectRegions,
}: {
  source: EvidenceGraphInput;
  onSelectRegions?: (ids: string[]) => void;
}) {
  const task = useAsyncTask(api.evidenceGraph);
  const { run } = task;
  // One request per evidence source. Each source identifies itself, so the graph
  // is refetched when the inspection (or the query behind a context) changes.
  const key =
    "inspection_id" in source
      ? source.inspection_id
      : "analysis" in source
        ? source.analysis.inspection_id
        : `${source.product_context.origin}:${source.product_context.query}`;

  useEffect(() => {
    run(source).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, run]);

  if (task.loading && !task.data) return <InlineLoading label="Building the evidence graph" />;
  if (!task.data) {
    if (task.error == null) return null;
    return (
      <p className="border border-line bg-surface px-5 py-4 text-[12px] leading-relaxed text-ink-soft">
        The evidence graph could not be built
        {task.error instanceof ApiError ? `: ${task.error.detail}` : "."} Every result, check and source
        above is unaffected.
      </p>
    );
  }
  return <EvidenceGraphPanel graph={task.data} onSelectRegions={onSelectRegions} />;
}
