import type { ReactNode } from "react";
import { ArrowUpRight, ExternalLink, FileText } from "lucide-react";
import type { CoverageBoundary, EvidenceSource } from "@/lib/api";
import { CoverageBoundaryPanel } from "@/components/CoverageBoundary";
import { categoryLabel, confidenceLabel } from "@/lib/format";
import { Callout, Chip, ConfidenceMeter, Mono, Panel } from "@/components/ui";
import { Annotation, Bracket } from "@/components/decor";

/**
 * Shared renderer for the grounded-explanation endpoints
 * (/ask, /certification-guidance, /laboratory-search). It keeps the hierarchy
 * the backend implies — QUESTION → ANSWER → EVIDENCE → SOURCES → CONFIDENCE —
 * and renders abstention distinctly so the UI never implies certainty the
 * backend did not give. Presented as an evidence exhibit, not a chat bubble.
 */
export function GroundedAnswer({
  question,
  answer,
  grounded,
  confidence,
  note,
  sources,
  context,
  abstentionMessage,
  explained = true,
  boundary = null,
}: {
  question: string;
  answer: string;
  grounded: boolean;
  confidence: string;
  note: string;
  sources: EvidenceSource[];
  context?: { label: string; value: string | null } | null;
  abstentionMessage: string;
  /** False when the provider was unavailable and `answer` is MetrIQ's own
      rendering of the retrieved records. The evidence below is unaffected. */
  explained?: boolean;
  /** Present only when MetrIQ abstained: its own account of the coverage
      boundary, rendered in place of a bare "nothing found". */
  boundary?: CoverageBoundary | null;
}) {
  return (
    <div className="relative border border-line bg-raised">
      <Bracket tone="accent" />

      {/* exhibit header */}
      <div className="flex items-center justify-between border-b border-line px-5 py-2.5 sm:px-6">
        <Mono muted className="text-[10px] uppercase tracking-[0.18em]">
          {!grounded ? "Result" : explained ? "Grounded answer" : "Evidence only"}
        </Mono>
        <Annotation className="hidden sm:inline-flex">Evidence first</Annotation>
      </div>

      <div className="grid lg:grid-cols-[1fr_320px]">
        {/* question + answer */}
        <div className="border-b border-line lg:border-b-0 lg:border-r">
          <div className="border-b border-line px-5 py-5 sm:px-6">
            <div className="eyebrow mb-2 !text-ink-faint">Question</div>
            <p className="text-balance text-[19px] leading-snug tracking-tight text-ink">
              {question}
            </p>
          </div>

          <div className="px-5 py-6 sm:px-6">
            {grounded ? (
              <>
                {!explained && (
                  <div className="mb-5 border-l-2 border-review bg-surface px-4 py-3">
                    <Mono muted className="text-[10px] uppercase tracking-[0.18em]">
                      No AI explanation
                    </Mono>
                    <p className="mt-1.5 text-[12px] leading-relaxed text-ink-soft">
                      The explanation service is unavailable. MetrIQ retrieved the
                      verified BIS records below and rendered them itself — the
                      evidence and its sources are unchanged.
                    </p>
                  </div>
                )}
                <Prose text={answer} />
              </>
            ) : boundary ? (
              <CoverageBoundaryPanel boundary={boundary} />
            ) : (
              <Callout tone="abstain" title="Insufficient verified evidence">
                {abstentionMessage}
              </Callout>
            )}

            {note && !answer.includes(note.slice(0, 40)) && (
              <p className="mt-5 border-t border-line pt-3 text-[12px] leading-relaxed text-ink-faint">
                {note}
              </p>
            )}
          </div>
        </div>

        {/* assessment — mono spec column */}
        <aside className="bg-surface px-5 py-5 sm:px-6">
          <div className="eyebrow mb-4 !text-ink-faint">Assessment</div>
          <dl className="divide-y divide-line border-y border-line">
            {context && (
              <SpecRow label={context.label}>
                {context.value ? (
                  <Mono>{context.value}</Mono>
                ) : (
                  <span className="text-ink-faint">Not identified</span>
                )}
              </SpecRow>
            )}
            <SpecRow label="Grounded">
              <Mono className={grounded ? "text-pass" : "text-review"}>
                {grounded ? "yes" : "no"}
              </Mono>
            </SpecRow>
            <SpecRow label="Explanation">
              <Mono muted className="text-[11px] uppercase tracking-[0.1em]">
                {explained ? "AI, grounded" : "none — evidence only"}
              </Mono>
            </SpecRow>
            <SpecRow label="Confidence">
              <Mono muted className="text-[11px] uppercase tracking-[0.1em]">
                {confidenceLabel(confidence)}
              </Mono>
            </SpecRow>
            <SpecRow label="Sources">
              <Mono>{String(sources.length).padStart(2, "0")}</Mono>
            </SpecRow>
          </dl>
          <div className="mt-4">
            <ConfidenceMeter confidence={confidence} />
          </div>
        </aside>
      </div>

      {/* evidence exhibits */}
      {sources.length > 0 && (
        <div className="border-t border-line">
          <div className="flex items-center justify-between border-b border-line px-5 py-2.5 sm:px-6">
            <Mono muted className="text-[10px] uppercase tracking-[0.18em]">
              Evidence
            </Mono>
            <Mono muted className="text-[11px]">
              {sources.length} BIS {sources.length === 1 ? "source" : "sources"}
            </Mono>
          </div>
          <ul>
            {sources.map((s, i) => (
              <li key={s.id} className={i > 0 ? "border-t border-line" : ""}>
                <SourceRow source={s} index={i + 1} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function SpecRow({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2.5">
      <dt className="kicker">{label}</dt>
      <dd className="text-right text-[12px] text-ink">{children}</dd>
    </div>
  );
}

/** Shared by the grounded views and the home page language demo. */
export function Prose({ text }: { text: string }) {
  // The backend answer is short plain text / light markdown. Render paragraphs
  // and simple bullets without pulling in a markdown dependency.
  const blocks = text.split(/\n{2,}/);
  return (
    <div className="space-y-3.5 text-[14px] leading-relaxed text-ink">
      {blocks.map((block, i) => {
        const lines = block.split("\n");
        const isList = lines.every((l) => /^\s*(\d+[.)]|[-*])\s+/.test(l));
        if (isList) {
          return (
            <ul key={i} className="space-y-2">
              {lines.map((l, j) => (
                <li key={j} className="flex gap-3">
                  <span className="mt-[7px] h-1.5 w-1.5 shrink-0 bg-accent" />
                  <span>{stripMarkers(l)}</span>
                </li>
              ))}
            </ul>
          );
        }
        return <p key={i}>{stripMarkers(block)}</p>;
      })}
    </div>
  );
}

function stripMarkers(s: string): string {
  return s
    .replace(/^\s*(\d+[.)]|[-*])\s+/, "")
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/`(.+?)`/g, "$1")
    .trim();
}

export function SourceRow({
  source,
  index,
}: {
  source: EvidenceSource;
  index?: number;
}) {
  return (
    <div className="px-5 py-4 sm:px-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 gap-3">
          {index != null && (
            <Mono muted className="mt-0.5 shrink-0 text-[11px] tabular-nums">
              {String(index).padStart(2, "0")}
            </Mono>
          )}
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              {source.standard_number && (
                <Mono className="text-[13px] font-medium">
                  {source.standard_number}
                </Mono>
              )}
              <Chip>{categoryLabel(source.category)}</Chip>
              <Chip
                tone={
                  source.verification_status === "verified" ? "accent" : "neutral"
                }
              >
                {source.verification_status}
              </Chip>
            </div>
            <div className="mt-1.5 text-[13px] font-medium text-ink">
              {source.title}
            </div>
            <div className="mt-1 text-[12px] text-ink-faint">
              {source.source_organization}
              {source.document_name ? ` · ${source.document_name}` : ""}
              {source.last_verified ? ` · verified ${source.last_verified}` : ""}
            </div>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <Mono muted className="text-[11px]">
            score {source.score.toFixed(1)}
          </Mono>
        </div>
      </div>

      {source.matched_terms.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 sm:pl-8">
          <span className="kicker mr-1">Matched</span>
          {source.matched_terms.map((t) => (
            <Chip key={t}>{t}</Chip>
          ))}
        </div>
      )}

      {source.source_url && (
        <a
          href={source.source_url}
          target="_blank"
          rel="noreferrer"
          className="group mt-3 inline-flex items-center gap-1.5 text-[12px] font-medium text-accent hover:text-accent-hover sm:ml-8"
        >
          {source.source_url.endsWith(".pdf") ? (
            <FileText className="h-3.5 w-3.5" />
          ) : (
            <ExternalLink className="h-3.5 w-3.5" />
          )}
          Official BIS source
          <ArrowUpRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
        </a>
      )}
    </div>
  );
}

export function ResultShell({ children }: { children: ReactNode }) {
  return <Panel flush>{children}</Panel>;
}
