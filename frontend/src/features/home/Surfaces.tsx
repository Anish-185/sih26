import { useId, useState } from "react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/cn";
import { Motif, Bracket } from "@/components/decor";
import { Mono } from "@/components/ui";

/**
 * The seven surfaces, as one switchable preview rather than seven cards.
 * Pointer and keyboard both drive it; the preview is a description of what the
 * surface actually returns, never a mock result.
 */
interface Surface {
  to: string;
  name: string;
  motif: "lotus" | "dome" | "pillar" | "fingerprint" | "mountain" | "botanical";
  lead: string;
  returns: string[];
  note: string;
}

const SURFACES: Surface[] = [
  {
    to: "/standards",
    name: "Product → Standard",
    motif: "lotus",
    lead: "Describe a product in plain words and MetrIQ retrieves the Indian Standards whose verified records actually describe it.",
    returns: ["Candidate standards, ranked by deterministic match", "Why this result — the signals that scored", "The official BIS page each record came from"],
    note: "Retrieval confidence is not a legal determination of applicability.",
  },
  {
    to: "/inspection",
    name: "Inspection",
    motif: "fingerprint",
    lead: "Photograph a package from any number of sides. MetrIQ reads it, extracts the declared values and links them to a verified standard.",
    returns: ["OCR regions with per-region confidence", "Declared fields, each tied to its region", "Product identification and standard candidates"],
    note: "A field that was not read is reported as not detected, never as missing.",
  },
  {
    to: "/certification",
    name: "Certification",
    motif: "dome",
    lead: "The route BIS publishes for a standard — assembled from verified records, where every sentence is a quote.",
    returns: ["Scheme and mark, established from verified text", "Ordered steps, each quoting its source", "The official BIS portal for applications"],
    note: "Guidance about a route. Never a statement that an item is certified.",
  },
  {
    to: "/laboratories",
    name: "Laboratories",
    motif: "mountain",
    lead: "A dated snapshot of BIS's own LIMS listing of IS-wise test facilities, searchable by standard, product or city.",
    returns: ["1,205 records · 245 laboratories · 157 standards", "Recognition validity as at the snapshot date", "Listed alphabetically — MetrIQ does not rank"],
    note: "Being listed is the only relationship established. No accreditation, no current status.",
  },
  {
    to: "/hallmarking",
    name: "Hallmarking",
    motif: "pillar",
    lead: "Observable hallmark evidence read from a photograph — a potential HUID, a purity mark, hallmark wording.",
    returns: ["Components BIS itself enumerates, each with a reason", "Purity grades checked against verified IS records", "What must be verified outside MetrIQ"],
    note: "MetrIQ never authenticates a hallmark, a HUID or a jeweller.",
  },
  {
    to: "/standards",
    name: "Evidence graph",
    motif: "botanical",
    lead: "How MetrIQ reached a result, drawn as the relationships its deterministic pipeline already established.",
    returns: ["Nodes for evidence, product, standard, source", "Each edge explains itself from the evidence", "Clicking a region lights its box on the photo"],
    note: "A projection of existing evidence. It infers nothing of its own.",
  },
  {
    to: "/hallmarking",
    name: "Copilot",
    motif: "lotus",
    lead: "An optional explanation layer over a finished result, in English, Hindi or Telugu.",
    returns: ["Answers grounded in the record it was given", "Every claim carries the evidence behind it", "Withheld outright if it strays from the evidence"],
    note: "It explains the record. It never produces one.",
  },
];

export function Surfaces() {
  const [i, setI] = useState(0);
  const s = SURFACES[i];
  const headingId = useId();
  const panelId = useId();

  return (
    <section aria-labelledby={headingId}>
      <div className="max-w-xl">
        <span className="eyebrow">Seven surfaces</span>
        <h2 id={headingId} className="display mt-4 text-[1.8rem] sm:text-[2.4rem]">
          One evidence pipeline, seven ways in
        </h2>
      </div>

      <div className="mt-10 grid gap-x-10 gap-y-6 lg:grid-cols-[minmax(0,0.62fr)_minmax(0,1fr)]">
        {/* selector */}
        <div role="tablist" aria-label="MetrIQ surfaces" className="flex flex-col">
          {SURFACES.map((item, index) => {
            const on = index === i;
            return (
              <button
                key={item.name}
                role="tab"
                id={`${panelId}-tab-${index}`}
                aria-selected={on}
                aria-controls={panelId}
                tabIndex={on ? 0 : -1}
                onClick={() => setI(index)}
                onMouseEnter={() => setI(index)}
                onFocus={() => setI(index)}
                onKeyDown={(e) => {
                  if (e.key === "ArrowDown" || e.key === "ArrowRight") {
                    e.preventDefault();
                    setI((v) => (v + 1) % SURFACES.length);
                  }
                  if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
                    e.preventDefault();
                    setI((v) => (v - 1 + SURFACES.length) % SURFACES.length);
                  }
                }}
                className={cn(
                  "group relative flex items-center gap-4 border-t border-line py-4 text-left last:border-b",
                  on ? "text-ink" : "text-ink-faint hover:text-ink-soft",
                )}
              >
                <span
                  aria-hidden
                  className={cn(
                    "h-px shrink-0 bg-accent transition-all duration-400",
                    on ? "w-6" : "w-0",
                  )}
                />
                <span className="display flex-1 text-[1.15rem] transition-colors sm:text-[1.35rem]">
                  {item.name}
                </span>
                <Mono className={cn("text-[11px] tabular-nums", on ? "!text-accent" : "!text-ink-faint")}>
                  {String(index + 1).padStart(2, "0")}
                </Mono>
              </button>
            );
          })}
        </div>

        {/* preview */}
        <div
          id={panelId}
          role="tabpanel"
          aria-labelledby={`${panelId}-tab-${i}`}
          className="relative min-h-[340px] overflow-hidden border border-line bg-surface"
        >
          <Motif
            name={s.motif}
            className="pointer-events-none absolute -right-10 -top-8 h-[62%] w-auto max-w-none opacity-[0.22]"
          />
          <Bracket tone="line" className="inset-4" />
          <div key={s.name} className="ink-in relative flex h-full flex-col p-7 sm:p-9">
            <p className="max-w-sm text-[15px] leading-relaxed text-ink">{s.lead}</p>
            <ul className="mt-7 space-y-2.5">
              {s.returns.map((r) => (
                <li key={r} className="flex gap-3 text-[13px] leading-relaxed text-ink-soft">
                  <span aria-hidden className="mt-[9px] h-1 w-1 shrink-0 bg-accent" />
                  {r}
                </li>
              ))}
            </ul>
            <div className="mt-auto flex flex-wrap items-end justify-between gap-4 pt-8">
              <p className="max-w-xs text-[12px] leading-relaxed text-ink-faint">{s.note}</p>
              <Link
                to={s.to}
                className="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.16em] text-accent transition-colors hover:text-accent-hover"
              >
                Open
                <span aria-hidden className="h-px w-6 bg-current transition-all group-hover:w-8" />
              </Link>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
