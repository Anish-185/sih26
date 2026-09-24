import { ArrowUpRight, ExternalLink } from "lucide-react";
import type { CoverageBoundary as Boundary } from "@/lib/api";
import { Chip, Mono } from "@/components/ui";

/**
 * MetrIQ's own account of why it did not answer: what the verified data covers,
 * what the search did, why the boundary sits where it does, and where to look
 * next — plus any weak match, shown as evidence and never as an answer.
 *
 * Every sentence comes from the backend, written by code in the user's language
 * (backend/app/boundary.py). Nothing here is composed in the browser, so the
 * wording cannot drift away from what MetrIQ actually verified.
 */
export function CoverageBoundaryPanel({ boundary }: { boundary: Boundary }) {
  return (
    <div className="border border-line bg-surface">
      <div className="flex items-center justify-between border-b border-line px-5 py-2.5 sm:px-6">
        <Mono muted className="text-[10px] uppercase tracking-[0.18em]">
          {boundary.heading}
        </Mono>
        <Mono muted className="text-[11px]">
          no answer given
        </Mono>
      </div>

      <div className="space-y-3 px-5 py-5 sm:px-6">
        {boundary.lines.map((line, i) => (
          <p
            key={i}
            className={
              i === 1
                ? "text-[14px] leading-relaxed text-ink"
                : "text-[13px] leading-relaxed text-ink-soft"
            }
          >
            {line}
          </p>
        ))}
      </div>

      <div className="border-t border-line px-5 py-4 sm:px-6">
        <span className="kicker block">{boundary.next_step}</span>
        <a
          href={boundary.next_step_url}
          target="_blank"
          rel="noreferrer"
          className="group mt-2 inline-flex items-center gap-1.5 text-[13px] font-medium text-accent hover:text-accent-hover"
        >
          <ExternalLink className="h-3.5 w-3.5" />
          BIS Know Your Standards
          <ArrowUpRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
        </a>
      </div>

      {boundary.weak_matches.length > 0 && (
        <div className="border-t border-line">
          <div className="border-b border-line bg-paper px-5 py-2.5 sm:px-6">
            <Mono muted className="text-[10px] uppercase tracking-[0.18em]">
              {boundary.weak_heading}
            </Mono>
            <p className="mt-2 max-w-2xl text-[12px] leading-relaxed text-ink-soft">
              {boundary.weak_note}
            </p>
          </div>
          <ul>
            {boundary.weak_matches.map((m, i) => (
              <li
                key={`${m.standard_number ?? m.title}-${i}`}
                className={i > 0 ? "border-t border-line" : ""}
              >
                <div className="px-5 py-3.5 sm:px-6">
                  <div className="flex flex-wrap items-center gap-2">
                    {m.standard_number && (
                      <Mono className="text-[13px] font-medium text-ink-soft">
                        {m.standard_number}
                      </Mono>
                    )}
                    <Chip>weak match — not an answer</Chip>
                    <Mono muted className="text-[11px]">
                      {m.confidence}
                    </Mono>
                  </div>
                  <div className="mt-1.5 text-[13px] text-ink-soft">{m.title}</div>
                  {m.matched_terms.length > 0 && (
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <span className="kicker mr-1">Matched only</span>
                      {m.matched_terms.map((t) => (
                        <Chip key={t}>{t}</Chip>
                      ))}
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
