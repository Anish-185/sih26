import { Link } from "react-router-dom";
import {
  ArrowRight,
  ArrowUpRight,
  BadgeCheck,
  FlaskConical,
  Gem,
  ScanLine,
  Target,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { LinkButton, Mono, StatusBadge, type ComplianceStatus } from "@/components/ui";
import { Annotation, Figurine, PhotoFragment } from "@/components/decor";
import { api } from "@/lib/api";
import { useOnMount } from "@/lib/hooks";
import { formatDate } from "@/lib/format";
import { OfficerStatusMark, productLabel } from "./records";

// Stable references: useOnMount re-runs when its task changes.
const loadStats = () => api.inspectionStats();
const loadRecent = () => api.listInspections([], 4);

interface Surface {
  to: string;
  label: string;
  hint: string;
  icon: LucideIcon;
  flagship?: boolean;
}

const SURFACES: Surface[] = [
  { to: "/inspection", label: "Inspection", hint: "Image → declared values → report", icon: ScanLine },
  {
    to: "/standards",
    label: "Product → Standard",
    hint: "Deterministic Indian Standard discovery",
    icon: Target,
    flagship: true,
  },
  { to: "/certification", label: "Certification", hint: "Grounded BIS certification guidance", icon: BadgeCheck },
  { to: "/laboratories", label: "Laboratories", hint: "BIS recognised-lab directories", icon: FlaskConical },
  { to: "/hallmarking", label: "Hallmarking / HUID", hint: "Grounded hallmarking information", icon: Gem },
];

const FLOW: [string, string, string][] = [
  ["Retrieval", "Source of truth", "Deterministic lexical search over the curated BIS knowledge base"],
  ["Evidence", "Language model", "Ranks and explains only what retrieval already found"],
  ["Verification", "On weak evidence", "Abstains — never guesses; every finding traces to a BIS source"],
];

export function DashboardView() {
  const stats = useOnMount(loadStats);
  const recent = useOnMount(loadRecent);
  const s = stats.data;
  // Counts come straight from the database. Unavailable -> "—", never a made-up number.
  const count = (n: number | undefined) => (n === undefined ? "—" : String(n).padStart(2, "0"));

  return (
    <div className="space-y-20 sm:space-y-24">
      {/* ============================================================ hero */}
      <section className="relative grid items-center gap-x-8 gap-y-12 lg:grid-cols-[1.02fr_0.98fr]">
        {/* left — editorial column */}
        <div className="relative z-10 max-w-2xl">
          <div className="flex items-center gap-3">
            <span className="eyebrow">AI-Assisted Legal Metrology Inspection</span>
            <span className="h-px w-8 bg-accent/40" aria-hidden />
            <Annotation className="hidden sm:inline-flex">BIS / India</Annotation>
          </div>

          <h1 className="display mt-6 text-[2.7rem] leading-[1] sm:text-[4rem]">
            Inspect a package.
            <br />
            Get evidence,
            <br />
            <span className="text-accent">not opinions.</span>
          </h1>

          <p className="mt-7 max-w-lg text-[15px] leading-relaxed text-ink-soft">
            MetrIQ reads declared values from a product image, retrieves the
            applicable Indian Standard, runs deterministic legal-metrology rule
            checks, and produces an inspection report an officer verifies — with
            every finding traced to its source.
          </p>

          <div className="mt-9 flex flex-wrap items-stretch gap-3">
            <LinkButton to="/inspection" size="lg">
              <ScanLine className="h-4 w-4" />
              Start an inspection
            </LinkButton>
            <LinkButton to="/standards" variant="secondary" size="lg">
              Explore standards
              <ArrowUpRight className="h-4 w-4" />
            </LinkButton>
          </div>

          {/* inline stats — not a dashboard grid. System results and officer
              review states are different things and are never added together. */}
          <div className="mt-10 border-t border-line pt-6">
            <div className="kicker mb-3">System results · saved inspections</div>
            <dl className="flex flex-wrap gap-x-10 gap-y-4">
              {(
                [
                  ["Inspections", s?.total, undefined],
                  ["Pass", s?.system.PASS, "PASS"],
                  ["Review", s?.system.REVIEW, "REVIEW"],
                  ["Fail", s?.system.FAIL, "FAIL"],
                ] as [string, number | undefined, ComplianceStatus | undefined][]
              ).map(([label, value, status]) => (
                <div key={label}>
                  <dd className="flex items-baseline gap-2">
                    <span className="font-mono text-2xl font-semibold tabular-nums text-ink">{count(value)}</span>
                    {status && <StatusBadge status={status} size="sm" />}
                  </dd>
                  <dt className="kicker mt-1">{label}</dt>
                </div>
              ))}
            </dl>
            <div className="kicker mb-3 mt-6">Officer review</div>
            <dl className="flex flex-wrap gap-x-10 gap-y-4">
              {(
                [
                  ["Pending", s?.officer.PENDING],
                  ["In review", s?.officer.IN_REVIEW],
                  ["Completed", s?.officer.COMPLETED],
                ] as [string, number | undefined][]
              ).map(([label, value]) => (
                <div key={label}>
                  <dd className="font-mono text-2xl font-semibold tabular-nums text-ink">{count(value)}</dd>
                  <dt className="kicker mt-1">{label}</dt>
                </div>
              ))}
            </dl>
            {stats.error != null && (
              <p className="mt-3 text-[12px] text-review">
                Inspection statistics are unavailable — the inspection database could not be reached.
              </p>
            )}
          </div>
        </div>

        {/* right — the reference hero plate (Lion Capital + its own blueprint
            dimension lines, brackets, markers and annotations), cropped at the
            top and bleeding a little past the right edge of the column. */}
        <div className="relative -mr-5 mt-4 min-h-[380px] sm:mr-0 sm:min-h-[440px] lg:min-h-[520px]">
          <Figurine className="metriq-rise absolute -top-6 right-0 w-[92%] max-w-none sm:-top-10 sm:w-[86%] lg:-right-8 lg:-top-14 lg:w-[82%]" />
        </div>
      </section>

      {/* ==================================================== upload strip */}
      <Link
        to="/inspection"
        className="group relative flex items-center gap-4 border border-accent bg-accent px-5 py-5 text-white transition-colors hover:bg-accent-hover sm:px-7"
      >
        <span
          className="grid h-10 w-10 shrink-0 place-items-center bg-white/15"
          aria-hidden
        >
          <ScanLine className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[14px] font-medium">
            Start an inspection from a package image
          </div>
          <Mono className="mt-0.5 block text-[10px] uppercase tracking-[0.16em] !text-white/65">
            PNG · JPG · WEBP · multiple images supported
          </Mono>
        </div>
        <span className="hidden items-center gap-2 font-mono text-[11px] uppercase tracking-[0.16em] sm:flex">
          Inspect
          <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
        </span>
      </Link>

      {/* ======================================================= surfaces */}
      <section>
        <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <span className="eyebrow">The five surfaces</span>
              <span className="h-px w-8 bg-accent/40" aria-hidden />
            </div>
            <h2 className="display mt-3 text-2xl sm:text-[1.9rem]">
              One evidence pipeline, five ways in
            </h2>
          </div>
          <Annotation className="hidden md:inline-flex">
            Deterministic core · grounded explanation
          </Annotation>
        </div>

        <div className="grid gap-px border border-line bg-line sm:grid-cols-2 lg:grid-cols-5">
          {SURFACES.map((a) => {
            const Icon = a.icon;
            return (
              <Link
                key={a.to}
                to={a.to}
                className="group relative flex flex-col gap-4 bg-raised p-5 transition-colors hover:bg-surface"
              >
                {a.flagship && (
                  <span
                    className="absolute inset-x-0 top-0 h-[2px] bg-accent"
                    aria-hidden
                  />
                )}
                <div className="flex items-center justify-between">
                  <span
                    className={`grid h-9 w-9 place-items-center border transition-colors ${
                      a.flagship
                        ? "border-accent bg-accent text-white"
                        : "border-accent-line bg-accent-soft text-accent group-hover:border-accent"
                    }`}
                    aria-hidden
                  >
                    <Icon className="h-4 w-4" />
                  </span>
                  <ArrowUpRight className="h-4 w-4 text-ink-faint transition-transform group-hover:translate-x-0.5 group-hover:text-accent" />
                </div>
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[13px] font-semibold">{a.label}</span>
                    {a.flagship && (
                      <span className="annotation border border-accent-line bg-accent-soft px-1 py-px !text-accent">
                        Flagship
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-[12px] leading-snug text-ink-faint">
                    {a.hint}
                  </p>
                </div>
              </Link>
            );
          })}
        </div>
      </section>

      {/* ===================================== photographic punctuation */}
      <div className="relative -mx-5 h-20 overflow-hidden bg-ink sm:mx-0 sm:h-24">
        <PhotoFragment
          src="/blue-botanical.png"
          blend="luminosity"
          className="absolute inset-0 h-full w-full object-cover object-[35%_45%] opacity-70"
        />
        <span className="absolute inset-0 bg-accent/40 mix-blend-color" aria-hidden />
        <div className="relative flex h-full items-center justify-between px-5 sm:px-8">
          <span className="flex items-center gap-3 font-mono text-[11px] uppercase tracking-[0.16em] text-white/85">
            Every finding
            <ArrowRight className="h-3.5 w-3.5" />
            one source
          </span>
          <span className="annotation !text-white/70">BIS / India</span>
        </div>
      </div>

      {/* =========================================== activity + signal */}
      <section className="grid gap-x-10 gap-y-12 lg:grid-cols-[1.5fr_1fr]">
        <div>
          <div className="mb-6 flex items-end justify-between gap-4 border-b border-line pb-4">
            <div>
              <span className="eyebrow">Recent inspections</span>
              <h2 className="display mt-2 text-xl">Latest activity</h2>
            </div>
            <Link
              to="/history"
              className="inline-flex items-center gap-1 font-mono text-[11px] uppercase tracking-[0.14em] text-accent hover:text-accent-hover"
            >
              All
              <ArrowUpRight className="h-3.5 w-3.5" />
            </Link>
          </div>
          {recent.data && recent.data.items.length === 0 && (
            <p className="border border-dashed border-line-strong bg-surface px-5 py-6 text-[13px] text-ink-soft">
              No inspections recorded yet.
            </p>
          )}
          {recent.error != null && (
            <p className="border border-line px-5 py-6 text-[13px] text-review">
              Recent inspections are unavailable.
            </p>
          )}
          {recent.data && recent.data.items.length > 0 && (
          <ul className="border border-line">
            {recent.data.items.map((ins, i) => (
              <li key={ins.inspection_id}>
                <Link
                  to={`/history/${ins.inspection_id}`}
                  className={`flex items-center justify-between gap-4 px-5 py-4 transition-colors hover:bg-surface ${
                    i > 0 ? "border-t border-line" : ""
                  }`}
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <Mono muted className="text-[11px]">
                        {ins.inspection_id}
                      </Mono>
                      <span className="truncate text-[13px] font-medium">
                        {productLabel(ins)}
                      </span>
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[12px] text-ink-faint">
                      <Mono muted>{ins.standard_number ?? "no standard"}</Mono> ·{" "}
                      {formatDate(ins.created_at)} · <OfficerStatusMark status={ins.officer_status} />
                    </div>
                  </div>
                  <StatusBadge status={ins.system_result} size="sm" />
                </Link>
              </li>
            ))}
          </ul>
          )}
        </div>

        <div>
          <div className="mb-6 border-b border-line pb-4">
            <span className="eyebrow">How MetrIQ answers</span>
            <h2 className="display mt-2 text-xl">Retrieval → Evidence → Verification</h2>
          </div>
          <ol className="relative">
            {FLOW.map(([step, label, detail], i) => (
              <li key={step} className="relative pb-8 pl-8 last:pb-0">
                {i < FLOW.length - 1 && (
                  <span
                    className="absolute left-[7px] top-6 h-full w-px bg-line"
                    aria-hidden
                  />
                )}
                <span
                  className="absolute left-0 top-1 h-3.5 w-3.5 border border-accent bg-paper"
                  aria-hidden
                />
                <div className="flex items-baseline gap-3">
                  <span className="display text-[1.35rem] leading-none">{step}</span>
                  <span className="kicker">{label}</span>
                </div>
                <p className="mt-1.5 text-[12px] leading-relaxed text-ink-soft">
                  {detail}
                </p>
              </li>
            ))}
          </ol>
          <div className="mt-2 border-t border-line pt-3">
            <Annotation>Verified BIS sources only</Annotation>
          </div>
        </div>
      </section>
    </div>
  );
}
