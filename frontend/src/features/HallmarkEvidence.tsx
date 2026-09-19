/*
  Hallmark / HUID evidence. Two things are kept visibly apart:

    OBSERVED FROM THE IMAGE   what OCR read (untrusted text, linked to its region)
    VERIFICATION STATUS       always "Not verified" — MetrIQ has no authoritative HUID verification

  Nothing here authenticates a HUID, a hallmark or an article.
*/
import { ArrowUpRight } from "lucide-react";
import { Mono, Panel, PanelHeader, StatusBadge } from "@/components/ui";
import { cn } from "@/lib/cn";
import type { HallmarkCheck, HallmarkEvidence, HallmarkObservation } from "@/lib/api";

const HUID_STATUS: Record<HallmarkEvidence["huid"]["status"], string> = {
  DETECTED: "Potential HUID detected",
  MULTIPLE: "Multiple potential HUID values detected",
  UNCERTAIN: "Potential HUID detected — uncertain",
  NOT_DETECTED: "No potential HUID read",
};

function pct(n: number) {
  return `${Math.round(n * 100)}%`;
}

function Observation({
  obs,
  selected,
  onSelect,
}: {
  obs: HallmarkObservation;
  selected: string[];
  onSelect?: (ids: string[]) => void;
}) {
  const active = obs.source_regions.length === selected.length && obs.source_regions.every((id, i) => selected[i] === id);
  return (
    <button
      type="button"
      disabled={!onSelect}
      onClick={() => onSelect?.(obs.source_regions)}
      className={cn(
        "block w-full border border-line px-3 py-2 text-left",
        onSelect && "hover:bg-surface",
        active && "bg-accent-soft",
      )}
    >
      <div className="text-[12px] text-ink">“{obs.raw_text}”</div>
      <Mono muted className="mt-0.5 block text-[10px]">
        {obs.source_regions.join(", ")}
        {obs.side ? ` · ${obs.side}` : ""} · OCR {pct(obs.ocr_confidence)} · {obs.method}
        {obs.status === "UNCERTAIN" ? " · uncertain" : ""}
      </Mono>
      {obs.note && <div className="mt-0.5 text-[11px] text-ink-faint">{obs.note}</div>}
    </button>
  );
}

function CheckRow({ check }: { check: HallmarkCheck }) {
  return (
    <li className="border-t border-line px-5 py-3">
      <div className="flex items-start justify-between gap-3">
        <span className="text-[12px] font-medium text-ink">{check.requirement}</span>
        {check.result === "NOT_SUPPORTED" ? (
          <Mono className="shrink-0 text-[10px] uppercase tracking-[0.1em] text-ink-faint">Not supported</Mono>
        ) : (
          <StatusBadge status={check.result} size="sm" />
        )}
      </div>
      <p className="mt-1 text-[12px] leading-relaxed text-ink-soft">{check.reason}</p>
      <Mono muted className="mt-0.5 block text-[10px]">
        {check.reason_code}
        {check.source ? ` · ${check.source.title}` : ""}
      </Mono>
    </li>
  );
}

export function HallmarkEvidencePanel({
  hallmark,
  selected = [],
  onSelect,
}: {
  hallmark: HallmarkEvidence;
  selected?: string[];
  onSelect?: (ids: string[]) => void;
}) {
  const { huid, purity } = hallmark;
  const careSource = hallmark.sources.find((s) => s.quote.includes("BIS Care App"));

  return (
    <Panel flush>
      <PanelHeader title="Hallmark evidence" meta={<StatusBadge status={hallmark.overall_status} size="sm" />} />
      <p className="border-b border-line px-5 py-2.5 text-[11px] leading-relaxed text-ink-faint">
        Observing a potential HUID is not authenticating it. Everything below was read from the photos by OCR and is
        untrusted text; checks use the verified BIS Hallmarking FAQ.
      </p>

      <div className="grid gap-px bg-line md:grid-cols-2">
        {/* OBSERVED */}
        <div className="space-y-3 bg-raised px-5 py-4">
          <div className="kicker">Observed from the image</div>
          <div>
            <div className="text-[13px] font-medium text-ink">{HUID_STATUS[huid.status]}</div>
            {huid.value && <Mono className="mt-1 block text-[15px] text-ink">{huid.value}</Mono>}
            <p className="mt-1 text-[12px] leading-relaxed text-ink-soft">{huid.reason}</p>
          </div>
          {huid.candidates.length > 0 && (
            <div className="space-y-1.5">
              {huid.candidates.map((o, i) => (
                <Observation key={`h-${i}`} obs={o} selected={selected} onSelect={onSelect} />
              ))}
            </div>
          )}
          <div>
            <div className="kicker mb-1">Purity / fineness</div>
            <p className="text-[12px] leading-relaxed text-ink-soft">{purity.reason}</p>
            {purity.candidates.map((o, i) => (
              <div key={`p-${i}`} className="mt-1.5">
                <Observation obs={o} selected={selected} onSelect={onSelect} />
              </div>
            ))}
          </div>
          {hallmark.components.length > 0 && (
            <div>
              <div className="kicker mb-1.5">Hallmark components in this photograph</div>
              <ul className="divide-y divide-line border-y border-line">
                {hallmark.components.map((c) => (
                  <li key={c.component} className="flex items-baseline gap-3 py-2">
                    <Mono
                      muted
                      className={cn(
                        "w-24 shrink-0 text-[10px] uppercase tracking-[0.1em]",
                        c.status === "DETECTED" && "text-pass",
                        c.status === "UNCERTAIN" && "text-review",
                      )}
                    >
                      {c.status.replace(/_/g, " ")}
                    </Mono>
                    <div className="min-w-0 flex-1">
                      <div className="text-[12px] font-medium">
                        {c.label}
                        {c.observed_value && (
                          <Mono className="ml-2 text-[12px] text-ink">{c.observed_value}</Mono>
                        )}
                      </div>
                      <p className="mt-0.5 text-[11px] leading-relaxed text-ink-soft">{c.why}</p>
                    </div>
                  </li>
                ))}
              </ul>
              <p className="mt-1.5 text-[11px] text-ink-faint">
                “Not detected” means this photograph did not show the mark — not that the
                article lacks it.
              </p>
            </div>
          )}
        </div>

        {/* VERIFICATION */}
        <div className="space-y-3 bg-surface px-5 py-4">
          <div className="kicker">Verification status</div>
          <Mono className="inline-block border border-line-strong px-2 py-1 text-[12px] uppercase tracking-[0.08em] text-ink">
            {hallmark.verification_status === "NOT_VERIFIED" ? "Not verified" : "No hallmark evidence"}
          </Mono>
          <p className="text-[12px] leading-relaxed text-ink-soft">{hallmark.verification_note}</p>
          {hallmark.detected && (
            <p className="text-[12px] font-medium leading-relaxed text-ink">
              External authoritative HUID verification required.
            </p>
          )}
          {hallmark.user_huid && (
            <div className="border border-line-strong bg-raised p-3">
              <div className="kicker mb-1">User-provided HUID</div>
              <Mono className="block text-[13px] text-ink">{hallmark.user_huid.value}</Mono>
              <Mono muted className="mt-1 block text-[10px] uppercase tracking-[0.1em]">
                {hallmark.user_huid.status.replace(/_/g, " ")}
              </Mono>
              <p className="mt-1 text-[11px] leading-relaxed text-ink-soft">
                {hallmark.user_huid.note}
              </p>
            </div>
          )}
          {hallmark.vision?.conflict && (
            <p className="text-[12px] leading-relaxed text-review">{hallmark.vision.conflict}</p>
          )}
          {hallmark.official_verification && (
            <p className="text-[12px] leading-relaxed text-ink-soft">
              {hallmark.official_verification.guidance}
            </p>
          )}
          {careSource?.source_url && (
            <a
              href={careSource.source_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-[11px] font-medium text-accent hover:text-accent-hover"
            >
              BIS Hallmarking FAQ — “{careSource.quote}”
              <ArrowUpRight className="h-3 w-3 shrink-0" />
            </a>
          )}
        </div>
      </div>

      {hallmark.untrusted_claims.length > 0 && (
        <div className="border-t border-line bg-review-soft px-5 py-3">
          <div className="text-[12px] font-medium text-review">Untrusted text claims verification</div>
          <p className="mt-0.5 text-[12px] leading-relaxed text-ink-soft">
            Text printed on the item or package is OCR evidence, not verification. It does not change any status.
          </p>
          <div className="mt-2 space-y-1.5">
            {hallmark.untrusted_claims.map((o, i) => (
              <Observation key={`c-${i}`} obs={o} selected={selected} onSelect={onSelect} />
            ))}
          </div>
        </div>
      )}

      {hallmark.checks.length > 0 && (
        <ul>
          {hallmark.checks.map((c) => (
            <CheckRow key={c.rule_id} check={c} />
          ))}
        </ul>
      )}
      <p className="border-t border-line px-5 py-3 text-[11px] leading-relaxed text-ink-faint">{hallmark.reason}</p>
    </Panel>
  );
}

export function showHallmark(hallmark: HallmarkEvidence | null, inspectionType: string): hallmark is HallmarkEvidence {
  return !!hallmark && (hallmark.detected || inspectionType === "HALLMARK" || hallmark.untrusted_claims.length > 0);
}
