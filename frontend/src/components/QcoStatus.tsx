import { Mono } from "@/components/ui";
import { cn } from "@/lib/cn";
import type { QcoStatus as Qco } from "@/lib/api";

/**
 * Phase 9 — Quality Control Order evidence for a standard. Every sentence comes
 * from the backend (app/qco.py): it quotes a BIS table row and is about the ORDER,
 * never about the user's item. NOT_ESTABLISHED is one quiet line (its sentence in
 * the tooltip), because most standards have no QCO row and the card should not
 * shout about an absence.
 */
const TONE: Record<Qco["status"], string> = {
  IN_FORCE: "text-accent",
  UPCOMING: "text-review",
  NOT_ESTABLISHED: "text-ink-faint",
};

export function QcoStatus({
  qco,
  compact,
  className,
}: {
  qco?: Qco | null;
  /** One line only — the label; the sentences stay in the title tooltip. */
  compact?: boolean;
  className?: string;
}) {
  if (!qco) return null;
  const label = (
    <Mono muted className={cn("text-[10px] uppercase tracking-[0.12em]", TONE[qco.status])}>
      {qco.label}
    </Mono>
  );
  if (compact || qco.status === "NOT_ESTABLISHED") {
    return (
      <span className={cn("block", className)} title={qco.statements.join(" ")}>
        {label}
      </span>
    );
  }
  return (
    <div className={cn("border-l-2 border-line-strong pl-3", className)}>
      <span className="kicker block">Quality Control Order</span>
      <p className="mt-1 text-[12px] leading-relaxed text-ink-soft">
        <span className="mr-2">{label}</span>
        {qco.statements.join(" ")}
      </p>
      {qco.rows.map((row) => (
        <p key={`${row.table}-${row.sr_no}`} className="mt-1 text-[11px] leading-relaxed text-ink-faint">
          <a href={row.source_url} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">
            {row.table}
          </a>
          {` · Sr. No. ${row.sr_no}`}
          {row.read_on ? ` · read on ${row.read_on}` : ""}
          {row.listed_products.length > 0 ? ` · ${row.listed_products.length} products listed under this row` : ""}
        </p>
      ))}
    </div>
  );
}
