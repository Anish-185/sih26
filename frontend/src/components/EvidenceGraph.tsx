/*
  Evidence graph (Milestone 22) — how MetrIQ arrived at this result.

  A READ-ONLY picture of relationships MetrIQ's deterministic systems already
  established: OCR and declarations, the product identification, the standard,
  the requirement it specifies, and the verified source behind each one.
  MetrIQ produces no automatic compliance verdict, so the graph has none to
  show — it decides nothing and infers nothing; every node, status and
  explanation is copied from the evidence the backend produced.

  Layout: one row per layer, so it reads top-down as a chain and degrades to a
  vertical evidence chain on a narrow screen without a canvas. Click a node for
  its evidence and its relationships; click an OCR region to light it up on the
  photograph.
*/
import { useMemo, useState } from "react";
import { ArrowUpRight, ChevronDown } from "lucide-react";
import type { EvidenceGraph as Graph, GraphEdge, GraphNode, GraphNodeType } from "@/lib/api";
import { Mono, Panel, PanelHeader } from "@/components/ui";
import { cn } from "@/lib/cn";

const LAYER_LABEL: Record<number, string> = {
  0: "Evidence read from the photographs",
  1: "Declarations extracted",
  2: "Product identification",
  3: "Indian Standard",
  4: "Requirements · certification · laboratories · hallmark",
  5: "Verified sources",
};

const TYPE_LABEL: Record<GraphNodeType, string> = {
  PRODUCT: "Product",
  OCR_EVIDENCE: "OCR region",
  DECLARATION: "Declaration",
  VISION_OBSERVATION: "Visual observation",
  STANDARD: "Standard",
  CERTIFICATION: "Certification",
  REQUIREMENT: "Requirement",
  LABORATORY: "Laboratory",
  HALLMARK_OBSERVATION: "Hallmark observation",
  HUID_OBSERVATION: "HUID observation",
  SOURCE: "Verified source",
};

/** The main chain, for "focus on the evidence path". */
const CHAIN: GraphNodeType[] = ["PRODUCT", "STANDARD", "REQUIREMENT", "SOURCE"];

/** Status colouring is the status the producing system recorded — never a score. */
function tone(node: GraphNode): string {
  const s = node.status;
  if (s === "MATCHED" || s === "IDENTIFIED" || s === "VERIFIED" || s === "DETECTED")
    return "border-pass-line bg-pass-soft text-pass";
  if (
    s === "REVIEW" ||
    s === "UNCERTAIN" ||
    s === "CONFLICT" ||
    s === "MULTIPLE" ||
    s === "PARTIAL" ||
    s === "NOT_VERIFIED"
  )
    return "border-review-line bg-review-soft text-review";
  if (s === "CANDIDATE") return "border-accent-line bg-accent-soft text-accent";
  return "border-line bg-surface text-ink-soft";
}

function prettyKey(key: string): string {
  return key.replaceAll("_", " ");
}

function prettyValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value))
    return value
      .map((v) => (typeof v === "object" && v !== null ? Object.values(v).join(" · ") : String(v)))
      .join(" · ");
  if (typeof value === "object") return Object.values(value as object).join(" · ");
  return String(value);
}

export function EvidenceGraphPanel({
  graph,
  onSelectRegions,
  defaultFocused = false,
}: {
  graph: Graph;
  /** Light the node's OCR regions up on the photograph, when there is one. */
  onSelectRegions?: (ids: string[]) => void;
  defaultFocused?: boolean;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(graph.root_id);
  const [focused, setFocused] = useState(defaultFocused);
  const [showLimits, setShowLimits] = useState(false);

  const nodes = useMemo(
    () => (focused ? graph.nodes.filter((n) => CHAIN.includes(n.type)) : graph.nodes),
    [graph.nodes, focused],
  );
  const byId = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph.nodes]);
  const layers = useMemo(() => {
    const out = new Map<number, GraphNode[]>();
    for (const node of nodes) out.set(node.layer, [...(out.get(node.layer) ?? []), node]);
    return [...out.entries()].sort(([a], [b]) => a - b);
  }, [nodes]);

  const selected = selectedId ? (byId.get(selectedId) ?? null) : null;
  const outgoing = graph.edges.filter((e) => e.source === selectedId);
  const incoming = graph.edges.filter((e) => e.target === selectedId);

  function select(node: GraphNode) {
    setSelectedId(node.id);
    if (node.source_regions.length > 0) onSelectRegions?.(node.source_regions);
  }

  return (
    <Panel flush>
      <PanelHeader
        title="Evidence graph"
        meta={
          <span className="flex flex-wrap items-center gap-3">
            <Mono muted className="text-[11px]">
              {graph.node_count} nodes · {graph.edge_count} relationships · read-only
            </Mono>
            <button
              type="button"
              onClick={() => setFocused((v) => !v)}
              className="font-mono text-[11px] uppercase tracking-[0.1em] text-accent hover:text-accent-hover"
            >
              {focused ? "Show all evidence" : "Focus on the path"}
            </button>
          </span>
        }
      />

      <p className="border-b border-line px-5 py-3 text-[12px] leading-relaxed text-ink-soft sm:px-6">
        {graph.note}
      </p>

      <ol className="px-5 py-4 sm:px-6">
        {layers.map(([layer, layerNodes], i) => (
          <li key={layer} className="relative pl-5">
            {i < layers.length - 1 && (
              <span aria-hidden className="absolute bottom-0 left-[3px] top-2 w-px bg-line" />
            )}
            <span aria-hidden className="absolute left-0 top-[7px] h-1.5 w-1.5 bg-line-strong" />
            <div className="pb-5">
              <Mono muted className="text-[10px] uppercase tracking-[0.12em]">
                {LAYER_LABEL[layer] ?? `layer ${layer}`}
              </Mono>
              <div className="mt-2 flex flex-wrap gap-2">
                {layerNodes.map((node) => (
                  <button
                    key={node.id}
                    type="button"
                    onClick={() => select(node)}
                    aria-pressed={node.id === selectedId}
                    className={cn(
                      "max-w-full rounded-sm border px-2.5 py-1.5 text-left transition-colors",
                      tone(node),
                      node.id === selectedId && "ring-1 ring-ink",
                    )}
                  >
                    <span className="block truncate text-[12px] font-medium">{node.label}</span>
                    <span className="mt-0.5 block font-mono text-[10px] uppercase tracking-[0.08em] opacity-70">
                      {TYPE_LABEL[node.type]}
                      {node.status ? ` · ${node.status}` : ""}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </li>
        ))}
      </ol>

      {selected && (
        <div className="border-t border-line px-5 py-4 sm:px-6">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h4 className="text-[13px] font-semibold">{selected.label}</h4>
            <Mono muted className="text-[10px] uppercase tracking-[0.1em]">
              {TYPE_LABEL[selected.type]}
              {selected.status ? ` · ${selected.status}` : ""}
            </Mono>
          </div>

          {Object.keys(selected.detail).length > 0 && (
            <dl className="mt-3 grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
              {Object.entries(selected.detail).map(([key, value]) => (
                <div key={key} className="min-w-0">
                  <dt className="kicker">{prettyKey(key)}</dt>
                  <dd className="break-words text-[12px] leading-relaxed text-ink">{prettyValue(value)}</dd>
                </div>
              ))}
            </dl>
          )}

          {selected.provenance.length > 0 && (
            <p className="mt-3 text-[11px] text-ink-faint">
              Produced by: <Mono muted>{selected.provenance.join(" · ")}</Mono>
            </p>
          )}

          {selected.source_url && (
            <a
              href={selected.source_url}
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-flex items-center gap-1 text-[12px] text-accent hover:text-accent-hover"
            >
              Open the official source
              <ArrowUpRight className="h-3 w-3" />
            </a>
          )}

          {(outgoing.length > 0 || incoming.length > 0) && (
            <div className="mt-4">
              <div className="kicker mb-1.5">Relationships</div>
              <ul className="space-y-1.5">
                {[...outgoing, ...incoming].map((edge, i) => (
                  <EdgeRow
                    key={`${edge.source}-${edge.type}-${edge.target}-${i}`}
                    edge={edge}
                    from={selectedId === edge.source}
                    other={byId.get(selectedId === edge.source ? edge.target : edge.source)}
                    onGo={(node) => select(node)}
                  />
                ))}
              </ul>
            </div>
          )}

          {selected.limitations.length > 0 && (
            <ul className="mt-3 space-y-1 border-t border-line pt-3">
              {selected.limitations.map((limit) => (
                <li key={limit} className="text-[11px] leading-relaxed text-ink-faint">
                  {limit}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {graph.limitations.length > 0 && (
        <div className="border-t border-line px-5 py-3 sm:px-6">
          <button
            type="button"
            onClick={() => setShowLimits((v) => !v)}
            className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-faint hover:text-ink"
          >
            <ChevronDown className={cn("h-3 w-3 transition-transform", showLimits && "rotate-180")} />
            What this graph does not establish ({graph.limitations.length})
          </button>
          {showLimits && (
            <ul className="mt-2 space-y-1">
              {graph.limitations.map((limit) => (
                <li key={limit} className="text-[11px] leading-relaxed text-ink-soft">
                  {limit}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Panel>
  );
}

function EdgeRow({
  edge,
  from,
  other,
  onGo,
}: {
  edge: GraphEdge;
  from: boolean;
  other: GraphNode | undefined;
  onGo: (node: GraphNode) => void;
}) {
  if (!other) return null;
  return (
    <li className="text-[12px] leading-relaxed">
      <button
        type="button"
        onClick={() => onGo(other)}
        className="text-left hover:text-accent"
        title={edge.explanation}
      >
        <Mono muted className="text-[10px] uppercase tracking-[0.08em]">
          {from ? "→" : "←"} {edge.type.replaceAll("_", " ")}
        </Mono>{" "}
        <span className="font-medium">{other.label}</span>
        <span className="block text-ink-soft">{edge.explanation}</span>
      </button>
    </li>
  );
}
