import { ArrowUpRight } from "lucide-react";
import type { ClauseEvidence } from "@/lib/api";
import { Mono } from "@/components/ui";

/**
 * Phase 8: the ONE way clause text is shown. It always carries MetrIQ's fixed OCR
 * label, because values such as "1.0 1 to 1.1 1" (litres read as "1") survive by
 * design — MetrIQ never corrects OCR, and the label is what makes that honest.
 *
 * The link opens the archive item, not a specific page: a page-specific link was
 * not verified to open that page, so the PDF page is shown as text instead.
 */
export function ClauseText({ clause }: { clause: ClauseEvidence }) {
  return (
    <div className="border-l-2 border-line-strong pl-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <Mono className="text-[12px] font-medium">{clause.standard_number}</Mono>
        <Mono muted className="text-[11px]">
          {clause.reference}
        </Mono>
      </div>
      <p className="mt-1.5 text-[11px] leading-relaxed text-review">{clause.ocr_label}</p>
      <p className="mt-2 whitespace-pre-line font-mono text-[12px] leading-relaxed text-ink-soft">
        {clause.text}
      </p>
      {clause.note && (
        <p className="mt-2 text-[11px] leading-relaxed text-ink-faint">{clause.note}</p>
      )}
      <a
        href={clause.source_url}
        target="_blank"
        rel="noreferrer"
        className="group mt-2 inline-flex items-center gap-1.5 text-[12px] font-medium text-accent hover:text-accent-hover"
      >
        Scanned document (Internet Archive)
        {clause.pdf_page != null && <span className="text-ink-faint">· PDF page {clause.pdf_page}</span>}
        <ArrowUpRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
      </a>
    </div>
  );
}

/** A list of clauses under one heading, as used by GroundedAnswer and the Standards cards. */
export function ClauseList({ title, clauses }: { title: string; clauses: ClauseEvidence[] }) {
  if (clauses.length === 0) return null;
  return (
    <div>
      <div className="kicker mb-2">{title}</div>
      <ul className="space-y-4">
        {clauses.map((c) => (
          <li key={c.id}>
            <ClauseText clause={c} />
          </li>
        ))}
      </ul>
    </div>
  );
}
