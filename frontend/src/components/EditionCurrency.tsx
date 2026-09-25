import { Mono } from "@/components/ui";
import { cn } from "@/lib/cn";
import type { EditionCurrency as Currency } from "@/lib/api";

/**
 * Phase 5 — is the edition MetrIQ cites the newest one its evidence shows?
 * Every sentence comes from the backend (app/standard_currency.py), so the browser
 * cannot word it more strongly than the evidence. It is a statement about
 * MetrIQ's evidence, never about BIS's catalogue as a whole.
 */
const TONE: Record<Currency["status"], string> = {
  ACTIVE: "text-accent",
  REAFFIRMED: "text-accent",
  SUPERSEDED_BY: "text-review",
  NOT_ESTABLISHED: "text-ink-faint",
};

export function EditionCurrency({
  currency,
  compact,
  className,
}: {
  currency?: Currency | null;
  /** One line only — the label; the statement stays in the title tooltip. */
  compact?: boolean;
  className?: string;
}) {
  if (!currency) return null;
  const label = (
    <Mono muted className={cn("text-[10px] uppercase tracking-[0.12em]", TONE[currency.status])}>
      {currency.label}
    </Mono>
  );
  if (compact) {
    return (
      <span className={className} title={currency.statement}>
        {label}
      </span>
    );
  }
  return (
    <div className={cn("border-l-2 border-line-strong pl-3", className)}>
      <span className="kicker block">Edition</span>
      <p className="mt-1 text-[12px] leading-relaxed text-ink-soft">
        <span className="mr-2">{label}</span>
        {currency.statement}
      </p>
      <p className="mt-1 text-[11px] leading-relaxed text-ink-faint">
        {currency.source_url ? (
          <a href={currency.source_url} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">
            {currency.source_label}
          </a>
        ) : (
          currency.source_label
        )}
        {" · "}
        {currency.boundary}
      </p>
    </div>
  );
}
