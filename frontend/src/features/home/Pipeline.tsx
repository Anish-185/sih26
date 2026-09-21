import { useId } from "react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/cn";
import { useScrollStep } from "@/lib/motion";
import { Mono } from "@/components/ui";

/**
 * "How MetrIQ works" — the four stages of the real pipeline, advanced by the
 * reader's scroll position rather than a timer, so the motion answers the
 * reader instead of demanding attention. The stage list is also clickable, and
 * the whole thing degrades to a plain ordered list on narrow screens.
 *
 * These four ARE a sequence (a photo becomes text becomes a product becomes a
 * standard), so they are numbered. Nothing here is a claim about a result.
 */
interface Stage {
  n: string;
  name: string;
  line: string;
  detail: string;
  /** What the stage actually produces, shown in the stage panel. */
  output: { label: string; value: string }[];
  foot: string;
}

const STAGES: Stage[] = [
  {
    n: "01",
    name: "Capture",
    line: "A photograph of the package",
    detail:
      "Photograph one side or several. Every image is read on its own, and a side that cannot be read is reported rather than treated as absent.",
    output: [
      { label: "Image", value: "front.png · 1000 × 1150" },
      { label: "Regions found", value: "15" },
      { label: "Mean confidence", value: "88%" },
    ],
    foot: "Local OCR. No image leaves the machine for text.",
  },
  {
    n: "02",
    name: "Understand",
    line: "Text becomes declared values",
    detail:
      "Fixed rules turn the raw text into declared fields — net quantity, MRP, packer, dates — each one linked back to the exact region it was read from.",
    output: [
      { label: "Net quantity", value: "1 L" },
      { label: "MRP", value: "₹20.00" },
      { label: "Printed standard", value: "IS 14543" },
    ],
    foot: "A field MetrIQ cannot read stays uncertain. It is never guessed.",
  },
  {
    n: "03",
    name: "Connect",
    line: "Evidence reaches a verified standard",
    detail:
      "Deterministic retrieval matches the evidence against the verified knowledge base. A standard only appears because a record for it exists.",
    output: [
      { label: "Product", value: "Packaged Drinking Water" },
      { label: "Standard", value: "IS 14543:2016" },
      { label: "Route", value: "Scheme I · ISI Mark" },
    ],
    foot: "97 verified Indian Standards, each with an official BIS source.",
  },
  {
    n: "04",
    name: "Explain",
    line: "Every link is traceable",
    detail:
      "The evidence graph shows how each conclusion was reached, and an optional grounded explanation puts it in plain language — in English, Hindi or Telugu.",
    output: [
      { label: "Graph", value: "64 nodes · 60 relationships" },
      { label: "Sources", value: "bis.gov.in · verified" },
      { label: "Report", value: "PDF, from the stored record" },
    ],
    foot: "The explanation reads the evidence. It never produces it.",
  },
];

export function Pipeline() {
  const { ref, step, setStep } = useScrollStep<HTMLDivElement>(STAGES.length);
  const active = STAGES[Math.min(step, STAGES.length - 1)];
  const headingId = useId();

  return (
    <section aria-labelledby={headingId}>
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-6">
        <div className="max-w-xl">
          <span className="eyebrow">How it works</span>
          <h2 id={headingId} className="display mt-4 text-[1.8rem] sm:text-[2.4rem]">
            A photograph becomes a traceable chain
          </h2>
        </div>
        <p className="max-w-xs text-[13px] leading-relaxed text-ink-soft">
          Four stages, each one recording what it read and where it read it.
        </p>
      </div>

      {/* The tall track gives the scroll something to map onto; the stage panel
          stays fixed in view while the reader moves through it. */}
      <div ref={ref} className="lg:h-[200vh]">
        <div className="lg:sticky lg:top-[68px] lg:flex lg:h-[calc(100vh-68px)] lg:items-center">
          <div className="grid w-full gap-x-12 gap-y-8 py-10 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
            {/* stage list */}
            <ol className="relative">
              {STAGES.map((s, i) => {
                const on = i === step;
                return (
                  <li key={s.n}>
                    <button
                      type="button"
                      onClick={() => setStep(i)}
                      aria-current={on ? "step" : undefined}
                      className="group flex w-full gap-5 border-t border-line py-5 text-left last:border-b"
                    >
                      <Mono
                        className={cn(
                          "mt-0.5 shrink-0 text-[12px] tabular-nums transition-colors",
                          on ? "!text-accent" : "!text-ink-faint",
                        )}
                      >
                        {s.n}
                      </Mono>
                      <span className="min-w-0 flex-1">
                        <span
                          className={cn(
                            "display block text-[1.35rem] transition-colors sm:text-[1.6rem]",
                            on ? "text-ink" : "text-ink-faint group-hover:text-ink-soft",
                          )}
                        >
                          {s.name}
                        </span>
                        <span
                          className={cn(
                            "mt-1 block text-[13px] leading-relaxed transition-colors",
                            on ? "text-ink-soft" : "text-ink-faint",
                          )}
                        >
                          {s.line}
                        </span>
                        {/* The detail belongs to the open stage only — progressive
                            disclosure rather than four paragraphs at once. */}
                        <span
                          className={cn(
                            "grid transition-[grid-template-rows,opacity] duration-500",
                            on ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0",
                          )}
                        >
                          <span className="overflow-hidden">
                            <span className="mt-3 block max-w-md text-[13px] leading-relaxed text-ink-soft">
                              {s.detail}
                            </span>
                          </span>
                        </span>
                      </span>
                      <span
                        aria-hidden
                        className={cn(
                          "mt-2 h-px shrink-0 self-start bg-accent transition-all duration-500",
                          on ? "w-8 opacity-100" : "w-0 opacity-0",
                        )}
                      />
                    </button>
                  </li>
                );
              })}
            </ol>

            {/* stage panel */}
            <div className="relative min-h-[300px] border border-line bg-surface">
              <div className="blueprint-field absolute inset-0 opacity-70" aria-hidden />
              <div className="relative flex h-full flex-col">
                <div className="flex items-center justify-between border-b border-line px-6 py-4">
                  <Mono className="text-[11px] uppercase tracking-[0.16em] !text-accent">
                    {active.n} · {active.name}
                  </Mono>
                  <span className="annotation">Illustrative values</span>
                </div>
                <dl className="flex-1 px-6 py-2">
                  {active.output.map((row, i) => (
                    <div
                      key={row.label}
                      className={cn(
                        "flex items-baseline justify-between gap-6 border-line py-4",
                        i > 0 && "border-t",
                      )}
                      style={{ animation: `metriq-ink 420ms ${i * 70}ms both` }}
                    >
                      <dt className="kicker">{row.label}</dt>
                      <dd className="text-right font-mono text-[13px] text-ink">{row.value}</dd>
                    </div>
                  ))}
                </dl>
                <p className="border-t border-line px-6 py-4 text-[12px] leading-relaxed text-ink-soft">
                  {active.foot}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="mt-2 flex justify-end">
        <Link
          to="/inspection"
          className="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.16em] text-accent transition-colors hover:text-accent-hover"
        >
          Run this on your own package
          <span aria-hidden className="h-px w-6 bg-current" />
        </Link>
      </div>
    </section>
  );
}
