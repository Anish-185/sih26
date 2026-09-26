/*
  Product intelligence — MetrIQ's canonical product context, compactly.

  It shows what MetrIQ's EXISTING deterministic features already established
  about one product, connected: product identity, standard, certification route,
  inspection, laboratories and (only when it applies) hallmarking. It creates no
  evidence of its own, so every line here is produced elsewhere and carries the
  name of the system that produced it.

  Each feature states its availability explicitly, because "MetrIQ has nothing"
  and "this does not apply to this product" are different facts. Detail lives in
  the feature pages — this panel links to them rather than repeating them.
*/
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { passportByNumber } from "@/lib/format";
import {
  BadgeCheck,
  FlaskConical,
  Gem,
  ScrollText,
  ShieldCheck,
  Tag,
} from "lucide-react";
import type { ContextAvailability, ContextFeature, ProductContext } from "@/lib/api";
import { Mono, Panel, PanelHeader } from "@/components/ui";
import { cn } from "@/lib/cn";

const ICON: Record<ContextFeature, typeof Tag> = {
  PRODUCT: Tag,
  STANDARD: ScrollText,
  CERTIFICATION: BadgeCheck,
  INSPECTION: ShieldCheck,
  LABORATORY: FlaskConical,
  HALLMARKING: Gem,
};

const LABEL: Record<ContextFeature, string> = {
  PRODUCT: "Product",
  STANDARD: "Indian Standard",
  CERTIFICATION: "Certification route",
  INSPECTION: "Package inspection",
  LABORATORY: "Testing laboratories",
  HALLMARKING: "Hallmarking",
};

/** Availability is a fact about MetrIQ's evidence, not a quality score. */
const TONE: Record<ContextAvailability, string> = {
  AVAILABLE: "border-accent-line bg-accent-soft text-accent",
  UNCERTAIN: "border-review-line bg-review-soft text-review",
  NOT_AVAILABLE: "border-line bg-surface text-ink-soft",
  NOT_APPLICABLE: "border-line bg-surface text-ink-faint",
};

const AVAILABILITY_TEXT: Record<ContextAvailability, string> = {
  AVAILABLE: "Available",
  UNCERTAIN: "Uncertain",
  NOT_AVAILABLE: "Not in MetrIQ's data",
  NOT_APPLICABLE: "Not applicable",
};

/** Where the reader goes for the full evidence — always an existing route. */
function link(feature: ContextFeature, context: ProductContext): ReactNode {
  const standard = (context.sections.find((s) => s.feature === "STANDARD")?.detail
    ?.standard_number ?? "") as string;
  if (feature === "STANDARD" && standard) {
    return <To to={passportByNumber(standard)}>Standard passport</To>;
  }
  if (feature === "CERTIFICATION" && standard) {
    return <To to={`/certification?standard=${encodeURIComponent(standard)}`}>Certification journey</To>;
  }
  if (feature === "LABORATORY" && standard) {
    return <To to={`/laboratories?standard=${encodeURIComponent(standard)}`}>Laboratory records</To>;
  }
  if (feature === "HALLMARKING") return <To to="/hallmarking">Hallmarking</To>;
  if (feature === "INSPECTION" && context.inspection_id) {
    return <To to={`/history/${context.inspection_id}`}>Inspection record</To>;
  }
  return null;
}

function To({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="text-[11px] text-accent hover:text-accent-hover">
      {children} →
    </Link>
  );
}

export function ProductIntelligence({ context }: { context: ProductContext }) {
  const title = context.product_name || context.query || "Product context";
  return (
    <Panel flush>
      <PanelHeader
        title="Product intelligence"
        meta={
          <Mono muted className="text-[10px] uppercase tracking-[0.16em]">
            {context.origin === "QUERY" ? "Derived by MetrIQ from your description" : "Composed from this inspection"}
          </Mono>
        }
      />

      <div className="border-b border-line px-5 py-3 sm:px-6">
        <div className="text-[14px] font-medium text-ink">{title}</div>
        <p className="mt-1 text-[12px] leading-relaxed text-ink-soft">{context.note}</p>
      </div>

      <ul className="divide-y divide-line">
        {context.sections.map((section) => {
          const Icon = ICON[section.feature];
          return (
            <li key={section.feature} className="flex gap-3 px-5 py-3.5 sm:px-6">
              <Icon
                className={cn(
                  "mt-0.5 h-4 w-4 shrink-0",
                  section.status === "AVAILABLE" ? "text-accent" : "text-ink-faint",
                )}
              />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[12px] font-medium text-ink">{LABEL[section.feature]}</span>
                  <span
                    className={cn(
                      "inline-flex items-center rounded-xs border px-1.5 py-0.5 font-mono text-[10px] uppercase leading-none tracking-[0.08em]",
                      TONE[section.status],
                    )}
                  >
                    {AVAILABILITY_TEXT[section.status]}
                  </span>
                  {link(section.feature, context)}
                </div>
                <p className="mt-1 text-[12.5px] leading-relaxed text-ink-soft">{section.headline}</p>
                {section.provenance.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {section.provenance.map((source) => (
                      <Mono key={source} muted className="text-[10px]">
                        {source.toLowerCase().replace(/_/g, " ")}
                      </Mono>
                    ))}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      {context.conflicts.length > 0 && (
        <div className="border-t border-line px-5 py-4 sm:px-6">
          <div className="kicker mb-2">What the evidence sources say about each other</div>
          <ul className="space-y-1.5">
            {context.conflicts.map((item, i) => (
              <li key={i} className="text-[12px] leading-relaxed text-ink-soft">
                {item}
              </li>
            ))}
          </ul>
        </div>
      )}

      {context.limitations.length > 0 && (
        <details className="border-t border-line px-5 py-3 sm:px-6">
          <summary className="cursor-pointer text-[12px] text-ink-soft hover:text-ink">
            What this context cannot establish ({context.limitations.length})
          </summary>
          <ul className="mt-2 space-y-1.5">
            {context.limitations.map((item, i) => (
              <li key={i} className="text-[12px] leading-relaxed text-ink-faint">
                {item}
              </li>
            ))}
          </ul>
        </details>
      )}
    </Panel>
  );
}
