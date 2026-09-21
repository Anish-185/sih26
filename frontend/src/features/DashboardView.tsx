import { Link } from "react-router-dom";
import { ScanLine } from "lucide-react";
import { LinkButton, Mono, Reveal } from "@/components/ui";
import { Annotation, BrailleField, Figurine, Motif, PhotoFragment } from "@/components/decor";
import { api } from "@/lib/api";
import { useOnMount } from "@/lib/hooks";
import { useParallax } from "@/lib/motion";
import { formatDate } from "@/lib/format";
import { ResolutionMark, productLabel } from "./records";
import { Pipeline } from "./home/Pipeline";
import { Surfaces } from "./home/Surfaces";
import { EvidenceChain } from "./home/EvidenceChain";
import { Multilingual } from "./home/Multilingual";

// Stable references: useOnMount re-runs when its task changes.
const loadStats = () => api.inspectionStats();
const loadRecent = () => api.listInspections(3);

/* ------------------------------------------------------------------ hero --- */

function Hero() {
  const stats = useOnMount(loadStats);
  const s = stats.data;
  // Counts come straight from the database. Unavailable -> "—", never invented.
  const count = (n: number | undefined) => (n === undefined ? "—" : String(n).padStart(2, "0"));

  return (
    <section className="relative grid items-center gap-x-8 gap-y-14 pt-4 lg:grid-cols-[1.04fr_0.96fr] lg:pt-10">
      <div className="relative z-10 max-w-2xl">
        <div className="ink-in flex items-center gap-3" style={{ animationDelay: "60ms" }}>
          <span className="eyebrow">AI-assisted legal metrology inspection</span>
          <span className="h-px w-8 bg-accent/40" aria-hidden />
          <Annotation className="hidden sm:inline-flex">BIS / India</Annotation>
        </div>

        <h1
          className="display ink-in mt-7 text-[2.6rem] leading-[1] sm:text-[3.5rem] lg:text-[4.05rem]"
          style={{ animationDelay: "140ms" }}
        >
          Turn product evidence into standards intelligence.
        </h1>

        <p
          className="ink-in mt-7 max-w-lg text-[15.5px] leading-[1.7] text-ink-soft"
          style={{ animationDelay: "240ms" }}
        >
          Photograph a package. MetrIQ reads what is printed on it, connects the
          declared values to a verified Indian Standard, and shows you the BIS page
          it came from — with every step of the reasoning left open to inspection.
        </p>

        <div
          className="ink-in mt-9 flex flex-wrap items-stretch gap-3"
          style={{ animationDelay: "320ms" }}
        >
          <LinkButton to="/inspection" size="lg">
            <ScanLine className="h-4 w-4" />
            Inspect a product
          </LinkButton>
          <LinkButton to="/standards" variant="secondary" size="lg">
            Explore standards
          </LinkButton>
        </div>

        {/* Saved-inspection counts. MetrIQ produces no compliance verdict; what is
            counted is whether the deterministic system could establish the
            evidence chain from the photographs. */}
        <div
          className="ink-in mt-11 border-t border-line pt-6"
          style={{ animationDelay: "400ms" }}
        >
          <dl className="grid grid-cols-3 gap-x-6 gap-y-4">
            {(
              [
                ["Saved inspections", s?.total],
                ["Established from photos", s?.resolved],
                ["Needs verification elsewhere", s?.escalated],
              ] as [string, number | undefined][]
            ).map(([label, value]) => (
              <div key={label}>
                <dd className="font-mono text-[1.5rem] font-semibold tabular-nums leading-none text-ink sm:text-[1.6rem]">
                  {count(value)}
                </dd>
                <dt className="kicker mt-2 block leading-[1.5]">{label}</dt>
              </div>
            ))}
          </dl>
          {stats.error != null && (
            <p className="mt-4 text-[12px] text-review">
              Inspection statistics are unavailable — the inspection database could
              not be reached.
            </p>
          )}
        </div>
      </div>

      {/* The reference plate: Lion Capital with its own blueprint dimension lines,
          brackets and annotations. Cropped at the top, bleeding past the column
          edge, and carrying the page's one orchestrated entrance. */}
      <div className="relative -mr-5 min-h-[400px] sm:mr-0 sm:min-h-[460px] lg:min-h-[560px]">
        <div
          className="ink-in absolute inset-0"
          style={{ animationDelay: "120ms", animationDuration: "900ms" }}
        >
          <Figurine className="absolute -top-8 right-0 w-[96%] max-w-none sm:-top-12 sm:w-[90%] lg:-right-10 lg:-top-16 lg:w-[88%]" />
        </div>

      </div>
    </section>
  );
}

/* --------------------------------------------------------------- problem --- */

function Problem() {
  const drift = useParallax<HTMLDivElement>(34);

  return (
    <section className="bleed relative overflow-hidden border-y border-line bg-surface">
      <div className="blueprint-field absolute inset-0 opacity-60" aria-hidden />
      <div ref={drift} className="pointer-events-none absolute -right-16 -top-10 hidden w-[34%] md:block">
        <Motif name="pillar" className="h-auto w-full opacity-[0.28]" />
      </div>

      <div className="relative mx-auto max-w-[1240px] px-5 py-24 sm:px-8 sm:py-28">
        <Reveal className="max-w-3xl">
          <span className="eyebrow">The gap</span>
          <h2 className="sr-only">The gap between a label and what governs it</h2>
          <p className="display mt-6 text-[1.7rem] leading-[1.25] sm:text-[2.3rem]">
            A label carries everything you need to know about a product and almost
            nothing you can act on. The standard that governs it, the certification
            route behind it, the laboratories that test to it — all of it is
            published, and none of it is on the package.
          </p>
        </Reveal>

        <Reveal delay={1} className="mt-14 grid max-w-4xl gap-x-10 gap-y-8 sm:grid-cols-3">
          {[
            ["Scattered", "BIS publishes standards, schemes, QCOs and laboratory listings across separate pages and PDFs."],
            ["Unlinked", "Nothing connects the words printed on a package to the record that governs the product."],
            ["Unverifiable", "An answer from a language model reads well and cannot be traced to anything."],
          ].map(([t, d]) => (
            <div key={t} className="border-t border-line-strong pt-4">
              <div className="display text-[1.1rem]">{t}</div>
              <p className="mt-2 text-[13px] leading-relaxed text-ink-soft">{d}</p>
            </div>
          ))}
        </Reveal>
      </div>
    </section>
  );
}

/* --------------------------------------------- product intelligence band --- */

function ProductIntelligence() {
  return (
    <section className="grid items-center gap-x-14 gap-y-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.92fr)]">
      <Reveal>
        <span className="eyebrow">One product, every surface</span>
        <h2 className="display mt-4 text-[1.8rem] sm:text-[2.4rem]">
          Everything MetrIQ knows, composed into one context
        </h2>
        <p className="mt-6 max-w-md text-[15px] leading-relaxed text-ink-soft">
          Identify a product once and each surface contributes what it verifiably
          holds. Where a surface has nothing, it says so — a gap is reported, never
          filled in from a similar product.
        </p>

        <dl className="mt-10 border-t border-line">
          {[
            ["Evidence", "OCR regions and declared values, each linked to where it was read"],
            ["Standard", "Retrieved from the verified knowledge base, with its BIS source"],
            ["Certification", "The scheme the verified records state, quoted word for word"],
            ["Laboratories", "What the BIS LIMS snapshot lists against that standard"],
            ["Hallmarking", "Applied only where the product is jewellery — never to a package"],
          ].map(([k, v]) => (
            <div key={k} className="flex gap-6 border-b border-line py-3.5">
              <dt className="w-32 shrink-0 font-mono text-[11px] uppercase tracking-[0.14em] text-accent">
                {k}
              </dt>
              <dd className="text-[13px] leading-relaxed text-ink-soft">{v}</dd>
            </div>
          ))}
        </dl>
      </Reveal>

      <Reveal delay={1} className="relative">
        <div className="relative aspect-[4/5] overflow-hidden bg-ink sm:aspect-[5/6]">
          <PhotoFragment
            src="/motif-fingerprint.png"
            blend="luminosity"
            className="absolute inset-0 h-full w-full object-cover object-[50%_28%] opacity-80"
          />
          <span className="absolute inset-0 bg-accent/45 mix-blend-color" aria-hidden />
          <BrailleField
            tone="white"
            rows={7}
            cols={26}
            className="right-4 top-4 leading-[13px] opacity-50"
          />
          {/* The caption sits on its own darkened band so the type always has
              contrast, whatever the crop underneath is doing. */}
          <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-ink/85 to-transparent p-6 pt-16">
            <Mono className="block text-[11px] uppercase tracking-[0.16em] !text-white/70">
              Details matter
            </Mono>
            <p className="mt-2 max-w-[26ch] text-[17px] leading-snug text-white">
              Verified sources, stronger decisions.
            </p>
          </div>
        </div>
      </Reveal>
    </section>
  );
}

/* ----------------------------------------------------------------- trust --- */

function Trust() {
  return (
    <section className="bleed border-y border-line bg-surface">
      <div className="mx-auto max-w-[1240px] px-5 py-24 sm:px-8 sm:py-28">
        <Reveal className="max-w-2xl">
          <span className="eyebrow">Where MetrIQ stops</span>
          <h2 className="display mt-4 text-[1.8rem] sm:text-[2.4rem]">
            The limits are part of the product
          </h2>
          <p className="mt-6 text-[15px] leading-relaxed text-ink-soft">
            An assistant that never says “I cannot establish that” is not one you can
            check. MetrIQ names its boundaries in the same place it gives its answers.
          </p>
        </Reveal>

        <Reveal delay={1} className="mt-14 grid gap-px border border-line bg-line md:grid-cols-3">
          {[
            [
              "It does not judge compliance",
              "MetrIQ reports observed evidence and verified knowledge. It produces no automatic pass, fail or review verdict on any package.",
            ],
            [
              "It does not authenticate",
              "A hallmark, a HUID, a licence number or a jeweller's registration is read from the photograph. Verifying it happens with BIS, not here.",
            ],
            [
              "It does not invent",
              "A standard number, a fee, a testing requirement or a laboratory's status that is not in the verified records is simply not stated.",
            ],
          ].map(([t, d]) => (
            <div key={t} className="bg-paper p-7">
              <div className="display text-[1.15rem]">{t}</div>
              <p className="mt-3 text-[13px] leading-relaxed text-ink-soft">{d}</p>
            </div>
          ))}
        </Reveal>
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------- recent --- */

function Recent() {
  const recent = useOnMount(loadRecent);
  const items = recent.data?.items ?? [];
  if (recent.error != null || items.length === 0) return null;

  return (
    <section>
      <div className="mb-6 flex items-end justify-between gap-4 border-b border-line pb-4">
        <div>
          <span className="eyebrow">Saved inspections</span>
          <h2 className="display mt-3 text-[1.3rem]">Recent activity</h2>
        </div>
        <Link
          to="/history"
          className="font-mono text-[11px] uppercase tracking-[0.14em] text-accent hover:text-accent-hover"
        >
          All records
        </Link>
      </div>
      <ul>
        {items.map((ins) => (
          <li key={ins.inspection_id}>
            <Link
              to={`/history/${ins.inspection_id}`}
              className="flex items-center justify-between gap-4 border-b border-line py-4 transition-colors hover:bg-surface"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Mono muted className="text-[11px]">
                    {ins.inspection_id}
                  </Mono>
                  <span className="truncate text-[13px] font-medium">{productLabel(ins)}</span>
                </div>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[12px] text-ink-faint">
                  <Mono muted>{ins.standard_number ?? "no standard"}</Mono> ·{" "}
                  {formatDate(ins.created_at)}
                </div>
              </div>
              <ResolutionMark required={ins.escalation_required} />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

/* ------------------------------------------------------------- final CTA --- */

function FinalCta() {
  return (
    <section className="relative overflow-hidden border border-line bg-raised">
      <div className="dot-field absolute inset-0 opacity-50" aria-hidden />
      <Motif
        name="lotus"
        className="pointer-events-none absolute -bottom-10 -right-8 hidden h-[130%] w-auto max-w-none opacity-[0.2] sm:block"
      />
      <Reveal className="relative px-7 py-16 sm:px-12 sm:py-20">
        <h2 className="display max-w-lg text-[1.9rem] sm:text-[2.5rem]">
          Start with a photograph.
        </h2>
        <p className="mt-5 max-w-md text-[15px] leading-relaxed text-ink-soft">
          Or begin from the other end and look up the Indian Standard for a product
          you already have in mind.
        </p>
        <div className="mt-9 flex flex-wrap gap-3">
          <LinkButton to="/inspection" size="lg">
            <ScanLine className="h-4 w-4" />
            Inspect a product
          </LinkButton>
          <LinkButton to="/standards" variant="secondary" size="lg">
            Find a standard
          </LinkButton>
          <LinkButton to="/certification" variant="secondary" size="lg">
            Certification guidance
          </LinkButton>
        </div>
      </Reveal>
    </section>
  );
}

/* ----------------------------------------------------------------- page --- */

export function DashboardView() {
  return (
    <div className="space-y-24 sm:space-y-32">
      <Hero />
      <Problem />
      <Pipeline />
      <ProductIntelligence />
      <Surfaces />
      <EvidenceChain />
      <Multilingual />
      <Trust />
      <Recent />
      <FinalCta />
    </div>
  );
}
