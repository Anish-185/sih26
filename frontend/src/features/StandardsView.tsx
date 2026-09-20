import { type FormEvent, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ArrowUpRight, Search } from "lucide-react";
import {
  ApiError,
  api,
  type CoverageStatus,
  type ProductStandardResult,
  type StandardCoverage,
} from "@/lib/api";
import { useAsyncTask, useOnMount } from "@/lib/hooks";
import { standardTitle } from "@/lib/format";
import { cn } from "@/lib/cn";
import {
  ArrowLink,
  Button,
  Callout,
  Chip,
  ConfidenceMeter,
  InlineLoading,
  Mono,
  PageHeader,
  TextInput,
} from "@/components/ui";
import {
  Annotation,
  BlueprintField,
  Bracket,
  HeaderMotif,
  Motif,
} from "@/components/decor";
import { CopilotPanel } from "@/features/CopilotPanel";
import { ProductIntelligence } from "@/components/ProductIntelligence";

const EXAMPLES = [
  "stainless steel water bottle",
  "LED lamp",
  "packaged drinking water",
  "electric iron",
];

/** What MetrIQ can do with a standard once it has been retrieved. */
const COVERAGE_LABEL: Record<CoverageStatus, string> = {
  INSPECTION_SUPPORTED: "Inspection supported",
  STANDARD_ONLY: "Standard only",
  UNSUPPORTED: "Not package-inspectable",
};

export function StandardsView() {
  const [query, setQuery] = useState("");
  const task = useAsyncTask(api.productStandard);
  // Loaded once: it is the same data-derived matrix for every search.
  const coverage = useOnMount(api.inspectionCoverage);
  const coverageBy = new Map(
    (coverage.data?.standards ?? []).map((s) => [s.standard_number, s]),
  );

  const [params, setParams] = useSearchParams();
  // Deep link from product intelligence: ?q=IS 367:1993 (or a product name).
  const deepLink = params.get("q") ?? "";
  useEffect(() => {
    if (!deepLink) return;
    setParams({}, { replace: true });
    setQuery(deepLink);
    task.run(deepLink).catch(() => {});
    contextTask.run(deepLink, "").catch(() => {});
    // Consumed once, on arrival.
  }, [deepLink]);

  // Milestone 21: the canonical product context for the query, derived by the
  // server from the same text. It connects the retrieved standard to the
  // certification route, the laboratory snapshot and inspection coverage.
  const contextTask = useAsyncTask(api.productContext);

  function submit(e: FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    task.run(q).catch(() => {});
    contextTask.run(q, "").catch(() => {});
  }

  const res = task.data;

  return (
    <div className="space-y-12">
      <div className="relative">
        <HeaderMotif name="lotus" label="Precision · purity" width="w-[22%]" />
        <PageHeader
          eyebrow="Product → Standard · Flagship"
          title="Find the Indian Standard for a product"
          lead="Describe a product in plain words. MetrIQ runs deterministic retrieval over the curated BIS knowledge base and only returns a standard when the retrieved evidence actually describes that product."
          size="xl"
        />
      </div>

      {/* search — the flagship affordance */}
      <div className="relative border border-line bg-raised">
        <span className="absolute inset-y-0 left-0 w-[2px] bg-accent" aria-hidden />
        <form onSubmit={submit} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:p-5">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
            <TextInput
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. stainless steel water bottle"
              className="h-11 pl-9"
              autoFocus
            />
          </div>
          <Button type="submit" size="lg" disabled={task.loading || !query.trim()}>
            {task.loading ? <InlineLoading label="Retrieving" /> : "Retrieve"}
          </Button>
        </form>
        <div className="flex flex-wrap items-center gap-2 border-t border-line px-4 py-3 sm:px-5">
          <span className="kicker mr-1">Try</span>
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => {
                setQuery(ex);
                task.run(ex).catch(() => {});
                contextTask.run(ex, "").catch(() => {});
              }}
              className="border border-line bg-surface px-2 py-1 font-mono text-[11px] text-ink-soft transition-colors hover:border-ink hover:text-ink"
            >
              {ex}
            </button>
          ))}
        </div>
      </div>

      {task.loading && (
        <p className="flex items-center gap-2 text-[12px] text-ink-faint">
          <span className="h-1 w-1 animate-pulse bg-accent" />
          Running deterministic retrieval over the BIS knowledge base…
        </p>
      )}
      {task.error != null && <ErrorNote error={task.error} />}

      {res && (
        <section className="space-y-6">
          <div className="flex flex-wrap items-end justify-between gap-3 border-b border-line pb-3">
            <div>
              <span className="eyebrow !text-ink-faint">
                {res.grounded ? "Candidate standards" : "No standard returned"}
              </span>
              <h2 className="display mt-2 text-xl">
                query <span className="text-accent">“{res.product}”</span>
              </h2>
            </div>
            <ConfidenceMeter confidence={res.confidence} />
          </div>

          {res.grounded ? (
            <ol className="space-y-4">
              {res.results.map((r, i) => (
                <StandardResult
                  key={r.id}
                  result={r}
                  rank={i + 1}
                  coverage={coverageBy.get(r.standard_number)}
                />
              ))}
            </ol>
          ) : (
            <Callout tone="abstain" title="Retrieval abstained">
              {res.note ||
                "No Indian Standard in the knowledge base clearly describes this product. MetrIQ does not guess a standard number."}
            </Callout>
          )}

          {contextTask.data && <ProductIntelligence context={contextTask.data} />}

          {res.results.length > 0 && (
            <CopilotPanel
              context={
                contextTask.data
                  ? { feature: "PRODUCT", product: contextTask.data }
                  : { feature: "STANDARD", standard: res }
              }
            />
          )}
        </section>
      )}

      {!res && task.error == null && !task.loading && (
        <div className="relative overflow-hidden border border-dashed border-line-strong bg-surface p-10">
          <BlueprintField fade="radial" />
          {/* blue-duotone motif — a research-desk fragment at the edge */}
          <Motif
            name="pillar"
            className="absolute -right-6 top-1/2 hidden h-[150%] w-auto max-w-none -translate-y-1/2 opacity-[0.5] [mask-image:linear-gradient(to_left,#000_30%,transparent)] sm:block"
          />
          <Bracket tone="line" className="-inset-2" />
          <div className="relative max-w-md">
            <Annotation className="mb-3 inline-flex">Awaiting query</Annotation>
            <div className="text-[15px] font-medium">No search yet</div>
            <p className="mt-2 text-[13px] leading-relaxed text-ink-soft">
              Results appear here as ranked candidate standards — each with its
              matched terms, the scored retrieval signals behind it, and the
              official BIS source.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function StandardResult({
  result,
  coverage,
  rank,
}: {
  result: ProductStandardResult;
  coverage?: StandardCoverage;
  rank: number;
}) {
  const topReasons = [...result.reasons]
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 4);

  return (
    <li className="group relative border border-line bg-raised transition-colors hover:border-line-strong">
      {rank === 1 && (
        <span className="absolute inset-y-0 left-0 w-[2px] bg-accent" aria-hidden />
      )}
      <div className="flex flex-col gap-5 p-5 sm:flex-row sm:items-start sm:justify-between sm:p-6">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <Mono muted className="text-[11px] tabular-nums">
              {String(rank).padStart(2, "0")}
            </Mono>
            <Mono className="text-[15px] font-semibold text-accent">
              {result.standard_number}
            </Mono>
          </div>
          <h3 className="display mt-2 text-[1.35rem] leading-tight">
            {standardTitle(result.title)}
          </h3>
          <p className="mt-2 text-[12px] text-ink-faint">
            {result.source_organization}
            {result.document_name ? ` · ${result.document_name}` : ""}
            {result.last_verified ? ` · verified ${result.last_verified}` : ""}
          </p>
          {coverage && (
            <p className="mt-1.5 text-[12px] leading-relaxed text-ink-soft">
              <Mono
                muted
                className={cn(
                  "mr-2 text-[10px] uppercase tracking-[0.12em]",
                  coverage.coverage_status === "INSPECTION_SUPPORTED" && "text-accent",
                )}
              >
                {COVERAGE_LABEL[coverage.coverage_status]}
              </Mono>
              {coverage.certification_route
                ? `Certification route recorded in the knowledge base: ${coverage.certification_route}. `
                : ""}
              {coverage.coverage_status === "INSPECTION_SUPPORTED"
                ? `${coverage.deterministic_rules} deterministic label check${coverage.deterministic_rules === 1 ? "" : "s"} available.`
                : "MetrIQ can identify and explain this standard; it has no verified image-checkable rule."}
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-row items-center gap-4 sm:flex-col sm:items-end">
          <ConfidenceMeter confidence={result.confidence} />
          <Mono muted className="text-[11px]">
            score {result.score.toFixed(1)}
          </Mono>
        </div>
      </div>

      {result.matched_terms.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 border-t border-line px-5 py-3 sm:px-6">
          <span className="kicker mr-1">Matched</span>
          {result.matched_terms.map((t) => (
            <Chip key={t} tone="accent">
              {t}
            </Chip>
          ))}
        </div>
      )}

      <div className="border-t border-line bg-surface px-5 py-4 sm:px-6">
        <div className="eyebrow mb-2 !text-ink-faint">Why this result</div>
        {result.why?.summary && (
          <p className="max-w-2xl text-[13px] leading-relaxed text-ink">
            {result.why.summary}
          </p>
        )}
        {topReasons.length > 0 && (
          <>
            <div className="kicker mb-2 mt-4">Retrieval signals</div>
            <ul className="divide-y divide-line border-y border-line">
              {topReasons.map((reason, i) => (
                <li
                  key={`${reason.field}-${reason.term}-${i}`}
                  className="flex items-baseline gap-3 py-2 text-[12px] text-ink-soft"
                >
                  <Mono muted className="w-24 shrink-0 text-[10px] uppercase tracking-[0.1em]">
                    {reason.field}
                  </Mono>
                  <span className="min-w-0 flex-1">
                    term <Mono>{reason.term}</Mono>
                    {reason.detail ? ` — ${reason.detail}` : ""}
                  </span>
                  <Mono className="shrink-0 text-[11px] text-accent">
                    +{reason.weight}
                  </Mono>
                </li>
              ))}
            </ul>
          </>
        )}
        <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2">
          {result.source_url && (
            <a
              href={result.source_url}
              target="_blank"
              rel="noreferrer"
              className="group/src inline-flex items-center gap-1.5 text-[12px] font-medium text-accent hover:text-accent-hover"
            >
              Official BIS source
              <ArrowUpRight className="h-3.5 w-3.5 transition-transform group-hover/src:translate-x-0.5" />
            </a>
          )}
          {result.standard_number && (
            <ArrowLink
              to={`/certification?standard=${encodeURIComponent(result.standard_number)}`}
            >
              Certification journey
            </ArrowLink>
          )}
        </div>
      </div>
    </li>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  const apiError = error instanceof ApiError ? error : null;
  // A timeout or an unreachable local model is an environment condition, not a
  // failed request the user should worry about — label it accordingly.
  const modelSlow = apiError?.status === 408 || apiError?.isModelUnavailable;
  const msg =
    apiError?.detail ??
    (error instanceof Error ? error.message : "Something went wrong.");
  return (
    <Callout title={modelSlow ? "The local model didn’t respond" : "Request failed"}>
      {msg}
    </Callout>
  );
}
