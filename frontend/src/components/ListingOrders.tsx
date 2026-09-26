import { Mono } from "@/components/ui";
import { cn } from "@/lib/cn";
import type { ListingOrders as Listing } from "@/lib/api";

/**
 * Phase 9.1 — the orders BIS's compulsory-certification listing names for this
 * standard. Every sentence comes from the backend (app/qco.py); it is what the
 * LISTING names, never a statement that an order is in force or applies. The
 * Notification cell is shown verbatim, and a flagged cell (rescission, withdrawal,
 * suspension, supersession) is marked so it is never read as "the" order.
 */
export function ListingOrders({ listing, className }: { listing?: Listing | null; className?: string }) {
  if (!listing) return null;
  const flagged = listing.groups.some((g) => g.flags.length > 0);
  return (
    <div className={cn("border-l-2 border-line-strong pl-3", className)}>
      <span className="kicker block">Order named by BIS&rsquo;s listing</span>
      {flagged && (
        <Mono muted className="mt-1 block text-[10px] uppercase tracking-[0.12em] text-review">
          Cell also records a rescission or supersession — not interpreted
        </Mono>
      )}
      <p className="mt-1 text-[12px] leading-relaxed text-ink-soft">{listing.statements.join(" ")}</p>
      <details className="mt-1 text-[11px] leading-relaxed text-ink-faint">
        <summary className="cursor-pointer select-none">The listing&rsquo;s Notification cell, as printed</summary>
        {listing.groups.map((g) => (
          <div key={`${g.scheme}-${g.notification}`} className="mt-1">
            <p>{g.notification}</p>
            <p className="mt-0.5">
              {g.orders
                .filter((o) => o.url)
                .map((o, i) => (
                  <span key={`${o.url}-${i}`}>
                    {i > 0 && " · "}
                    <a href={o.url!} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">
                      {o.number ?? o.text}
                    </a>
                  </span>
                ))}
            </p>
            <p className="mt-0.5">
              <a href={g.source_url} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">
                BIS Scheme {g.scheme} listing
              </a>
              {listing.read_on ? ` · read on ${listing.read_on}` : ""}
            </p>
          </div>
        ))}
      </details>
    </div>
  );
}
