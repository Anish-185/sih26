import { useId } from "react";
import { useReveal } from "@/lib/motion";
import { cn } from "@/lib/cn";
import { BrailleField } from "@/components/decor";

/**
 * The statement section: MetrIQ's philosophy, drawn as the chain its evidence
 * graph actually walks. The connecting line draws itself once, when the band
 * is first reached — motion that explains the relationship rather than
 * decorating it.
 */
const LINKS: { name: string; note: string }[] = [
  { name: "Product", note: "photographed, never assumed" },
  { name: "Evidence", note: "OCR regions and declared values" },
  { name: "Standard", note: "retrieved from verified records" },
  { name: "Source", note: "an official BIS page" },
  { name: "Explanation", note: "optional, and grounded" },
];

export function EvidenceChain() {
  const { ref, shown } = useReveal<HTMLDivElement>(0.25);
  const headingId = useId();

  return (
    <section ref={ref} aria-labelledby={headingId} className="bleed relative overflow-hidden bg-ink text-paper">
      <BrailleField
        tone="white"
        rows={14}
        cols={70}
        className="left-0 top-0 leading-[14px] [mask-image:linear-gradient(to_right,#000,transparent_70%)]"
      />
      <div className="relative mx-auto max-w-[1240px] px-5 py-24 sm:px-8 sm:py-32">
        <h2 id={headingId} className="display max-w-3xl text-[2rem] leading-[1.06] sm:text-[3.1rem]">
          The evidence is the source of truth.{" "}
          <span className="mt-2 block text-paper/45">The AI explains the evidence.</span>
        </h2>

        <p className="mt-8 max-w-lg text-[15px] leading-relaxed text-paper/60">
          Nothing on this site is produced by a language model. Retrieval, extraction
          and the links between them are deterministic, and every one of them can be
          walked back to the BIS page it came from.
        </p>

        {/* the chain */}
        <ol className="relative mt-20 grid gap-y-10 sm:grid-cols-5 sm:gap-y-0">
          {/* connector: one line that draws across the row once */}
          <svg
            aria-hidden
            className="pointer-events-none absolute left-0 top-[7px] hidden h-px w-4/5 sm:block"
            preserveAspectRatio="none"
            viewBox="0 0 100 1"
          >
            <line
              x1="0"
              y1="0.5"
              x2="100"
              y2="0.5"
              stroke="currentColor"
              strokeWidth="1"
              vectorEffect="non-scaling-stroke"
              className={cn("text-paper/25", shown && "draw")}
              style={{ ["--dash" as string]: "100", strokeDasharray: 100 }}
            />
          </svg>

          {LINKS.map((l, i) => (
            <li key={l.name} className="relative sm:pr-6">
              <span
                aria-hidden
                className={cn(
                  "block h-3.5 w-3.5 border border-paper/45 bg-ink transition-all duration-500",
                  shown ? "opacity-100" : "opacity-0",
                  i === 0 && "!border-accent bg-accent",
                )}
                style={{ transitionDelay: `${300 + i * 170}ms` }}
              />
              <div
                className={cn(
                  "mt-5 transition-all duration-600",
                  shown ? "translate-y-0 opacity-100" : "translate-y-2 opacity-0",
                )}
                style={{ transitionDelay: `${380 + i * 170}ms` }}
              >
                <div className="display text-[1.25rem]">{l.name}</div>
                <p className="mt-1.5 max-w-[22ch] text-[12px] leading-relaxed text-paper/50">
                  {l.note}
                </p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
