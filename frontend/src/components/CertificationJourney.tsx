import type { CertificationJourney as Journey } from "@/lib/api";
import { Callout, Chip, Mono, Panel, PanelHeader } from "@/components/ui";
import { cn } from "@/lib/cn";
import { EditionCurrency } from "@/components/EditionCurrency";
import { QcoStatus } from "@/components/QcoStatus";

/** How much of this guidance the verified knowledge base actually supports. */
const STATUS: Record<
  Journey["verification_status"],
  { label: string; className: string; note: string }
> = {
  VERIFIED: {
    label: "Verified",
    className: "text-pass",
    note: "The certification route below is stated by verified BIS records, and every step quotes one.",
  },
  PARTIAL: {
    label: "Partial",
    className: "text-review",
    note: "Some of this guidance is verified, but part of it could not be established from the knowledge base.",
  },
  INSUFFICIENT: {
    label: "Insufficient",
    className: "text-ink-faint",
    note: "There is not enough verified information to give a certification route for this standard.",
  },
};

const SELECTION: Record<Journey["standard_selection"], string> = {
  CONFIRMED: "One standard identified",
  MULTIPLE_CANDIDATES: "Several candidate standards — not resolved",
  NOT_IDENTIFIED: "No standard identified",
};

function SourceLine({
  document,
  url,
  verified,
}: {
  document: string | null;
  url: string | null;
  verified: string | null;
}) {
  return (
    <p className="mt-1.5 text-[11px] text-ink-faint">
      {document ?? "Bureau of Indian Standards (BIS)"}
      {verified ? ` · verified ${verified}` : ""}
      {url && (
        <>
          {" · "}
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            className="underline decoration-line-strong underline-offset-2 transition-colors hover:text-accent"
          >
            official source
          </a>
        </>
      )}
    </p>
  );
}

/**
 * The certification journey: product -> standard -> scheme -> next steps.
 *
 * Everything shown here is retrieved and deterministic. Each step's body is a
 * word-for-word quote from a verified BIS record; MetrIQ writes none of it.
 */
export function CertificationJourney({ journey }: { journey: Journey }) {
  const status = STATUS[journey.verification_status];

  return (
    <Panel flush>
      <PanelHeader
        title="Certification journey"
        meta={
          <span className={cn("font-mono text-[11px] uppercase tracking-[0.12em]", status.className)}>
            {status.label}
          </span>
        }
      />

      <div className="space-y-5 p-5 sm:p-6">
        <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
          <div>
            <dt className="kicker mb-1">Product</dt>
            <dd className="text-[13px]">{journey.product || journey.query || "—"}</dd>
          </div>
          <div>
            <dt className="kicker mb-1">Standard</dt>
            <dd className="text-[13px]">
              {journey.standard_number ? (
                <>
                  <Mono className="font-semibold text-accent">{journey.standard_number}</Mono>
                  {journey.standard_title && (
                    <span className="ml-2 text-ink-soft">{journey.standard_title}</span>
                  )}
                </>
              ) : (
                <span className="text-ink-faint">{SELECTION[journey.standard_selection]}</span>
              )}
            </dd>
          </div>
          <div>
            <dt className="kicker mb-1">Certification scheme</dt>
            <dd className="text-[13px]">
              {journey.scheme ? journey.scheme.name : <span className="text-ink-faint">Not established</span>}
            </dd>
          </div>
          <div>
            <dt className="kicker mb-1">Mark</dt>
            <dd className="text-[13px]">
              {journey.scheme ? journey.scheme.mark : <span className="text-ink-faint">—</span>}
            </dd>
          </div>
        </dl>

        <EditionCurrency currency={journey.currency} />
        <QcoStatus qco={journey.qco} />

        <p className="text-[12px] leading-relaxed text-ink-soft">{status.note}</p>

        {journey.message && <Callout tone="abstain">{journey.message}</Callout>}
        {journey.scheme?.conflict && (
          <Callout tone="abstain" title="Verified records disagree">
            {journey.scheme.conflict}
          </Callout>
        )}
      </div>

      {journey.why.length > 0 && (
        <div className="border-t border-line px-5 py-4 sm:px-6">
          <span className="kicker">Why this result</span>
          <ul className="mt-2 space-y-1.5">
            {journey.why.map((line) => (
              <li key={line} className="text-[12px] leading-relaxed text-ink-soft">
                {line}
              </li>
            ))}
          </ul>
        </div>
      )}

      {journey.standard_selection === "MULTIPLE_CANDIDATES" && journey.candidates.length > 0 && (
        <div className="border-t border-line px-5 py-4 sm:px-6">
          <span className="kicker">Potentially relevant standards</span>
          <ul className="mt-2 space-y-2.5">
            {journey.candidates.map((c) => (
              <li key={c.knowledge_id}>
                <div className="flex flex-wrap items-baseline gap-2">
                  <Mono className="text-[12px] font-semibold text-accent">{c.standard_number}</Mono>
                  <span className="text-[12px] text-ink-soft">{c.title}</span>
                  <Chip>{c.confidence}</Chip>
                  <EditionCurrency currency={c.currency} compact />
                  <QcoStatus qco={c.qco} compact />
                </div>
                <p className="mt-0.5 text-[11px] leading-relaxed text-ink-faint">{c.why.summary}</p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {journey.steps.length > 0 && (
        <ol className="border-t border-line">
          {journey.steps.map((step) => (
            <li key={step.order} className="border-b border-line px-5 py-4 last:border-b-0 sm:px-6">
              <div className="flex gap-4">
                <Mono muted className="mt-0.5 shrink-0 text-[11px]">
                  {String(step.order).padStart(2, "0")}
                </Mono>
                <div className="min-w-0">
                  <div className="text-[13px] font-medium">{step.title}</div>
                  {step.evidence.map((e) => (
                    <div key={e.knowledge_id + e.quote.slice(0, 24)} className="mt-1.5">
                      <p className="border-l border-line-strong pl-3 text-[12px] leading-relaxed text-ink-soft">
                        {e.quote}
                      </p>
                      <SourceLine
                        document={e.document_name}
                        url={e.source_url}
                        verified={e.last_verified}
                      />
                    </div>
                  ))}
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}

      {journey.next_steps.length > 0 && (
        <div className="border-t border-line px-5 py-4 sm:px-6">
          <span className="kicker">What to do next</span>
          <ol className="mt-2 space-y-1.5">
            {journey.next_steps.map((step) => (
              <li key={step} className="text-[12px] leading-relaxed text-ink-soft">
                {step}
              </li>
            ))}
          </ol>
        </div>
      )}

      {journey.limitations.length > 0 && (
        <div className="border-t border-line px-5 py-4 sm:px-6">
          <span className="kicker">Limitations</span>
          <ul className="mt-2 space-y-1.5">
            {journey.limitations.map((line) => (
              <li key={line} className="text-[12px] leading-relaxed text-ink-soft">
                {line}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="border-t border-line bg-surface px-5 py-3 text-[11px] leading-relaxed text-ink-faint sm:px-6">
        {journey.disclaimer}
      </div>
    </Panel>
  );
}
