import { type ReactNode, useEffect } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ArrowUpRight } from "lucide-react";
import { api, type StandardPassport } from "@/lib/api";
import { useAsyncTask } from "@/lib/hooks";
import { passportPath, standardTitle } from "@/lib/format";
import { cn } from "@/lib/cn";
import { ArrowLink, Callout, DefinitionRow, EmptyState, InlineLoading, Mono, PageHeader } from "@/components/ui";
import { ClauseList } from "@/components/ClauseText";
import { ClauseGroups } from "@/components/ClauseGroups";
import { EditionCurrency } from "@/components/EditionCurrency";
import { QcoStatus } from "@/components/QcoStatus";
import { ListingOrders, OrderKind } from "@/components/ListingOrders";
import { CertificationJourney } from "@/components/CertificationJourney";
import { LaboratoryResults } from "@/components/LaboratoryResults";
import { EvidenceGraphSection } from "@/components/EvidenceGraphSection";
import { ErrorNote } from "@/features/StandardsView";

/**
 * /standard?number=<as stored> — standard numbers carry slashes, so they cannot be a
 * path segment. One record -> redirect to /standard/:id; several (a number without a
 * year where several editions are held) -> listed, never picked; none -> said so.
 */
export function StandardLookupView() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const number = params.get("number") ?? "";
  const task = useAsyncTask(api.standardPassportLookup);
  const { run } = task;

  useEffect(() => {
    if (number) run(number).catch(() => {});
  }, [number, run]);

  useEffect(() => {
    const matches = task.data?.matches ?? [];
    if (matches.length === 1) navigate(passportPath(matches[0].id), { replace: true });
  }, [task.data, navigate]);

  if (!number) {
    return <EmptyState title="No standard number given" description="Open a standard from the Standards page." />;
  }
  if (task.loading || !task.data) {
    return task.error != null ? <ErrorNote error={task.error} /> : <InlineLoading label="Looking up the standard" />;
  }
  const { matches, message } = task.data;
  if (matches.length === 0) {
    return (
      <div className="space-y-6">
        <PageHeader eyebrow="Standard passport" title={<Mono>{number}</Mono>} />
        <Callout tone="abstain" title="No verified record">
          {message}
        </Callout>
      </div>
    );
  }
  if (matches.length === 1) return <InlineLoading label="Opening the passport" />;
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Standard passport"
        title={<Mono>{number}</Mono>}
        lead="MetrIQ holds more than one record for this number. It does not choose between editions — pick the one you mean."
      />
      <ul className="divide-y divide-line border-y border-line">
        {matches.map((m) => (
          <li key={m.id} className="flex flex-wrap items-baseline justify-between gap-3 py-3">
            <span>
              <Mono className="mr-3 font-semibold text-accent">{m.standard_number}</Mono>
              <span className="text-[13px] text-ink-soft">{standardTitle(m.title)}</span>
            </span>
            <ArrowLink to={passportPath(m.id)}>Open passport</ArrowLink>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** One numbered Passport section. An empty section still renders, with its sentence. */
function Section({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section className="grid gap-4 border-t border-line pt-6 md:grid-cols-[180px_1fr]">
      <div>
        <Mono muted className="text-[11px] tabular-nums">
          {String(n).padStart(2, "0")}
        </Mono>
        <h2 className="mt-1 text-[15px] font-medium">{title}</h2>
      </div>
      <div className="min-w-0 space-y-3">{children}</div>
    </section>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="max-w-2xl text-[13px] leading-relaxed text-ink-faint">{children}</p>;
}

export function StandardPassportView() {
  const { id = "" } = useParams();
  const passport = useAsyncTask(api.standardPassport);
  const { run } = passport;
  useEffect(() => {
    run(id).catch(() => {});
  }, [id, run]);

  if (passport.error != null) return <ErrorNote error={passport.error} />;
  if (!passport.data) return <InlineLoading label="Composing the passport" />;
  return <Passport p={passport.data} />;
}

function Passport({ p }: { p: StandardPassport }) {
  const number = p.standard_number;
  const { identity, coverage, legal } = p;
  const clauseLevel = coverage.level === "CLAUSE";

  // Sections 8–10 are the existing features, composed by number. explain=false:
  // nothing on this page needs a model.
  const cert = useAsyncTask(api.certificationGuidance);
  const labs = useAsyncTask(api.laboratorySearch);
  const context = useAsyncTask(api.productContext);
  const runCert = cert.run, runLabs = labs.run, runContext = context.run;
  useEffect(() => {
    runCert("", "", number, false, "en").catch(() => {});
    runLabs(number, number, false, "en").catch(() => {});
    runContext("", number).catch(() => {});
  }, [number, runCert, runLabs, runContext]);

  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="Standard passport"
        title={<Mono className="text-accent">{number}</Mono>}
        lead={standardTitle(identity.title)}
        annotation={
          <Mono muted className={cn("text-[11px] uppercase tracking-[0.12em]", clauseLevel && "text-accent")}>
            {clauseLevel ? "Clause text held" : "Identity only"}
          </Mono>
        }
      />

      <Section n={1} title="Identity">
        <dl className="divide-y divide-line border-y border-line">
          <DefinitionRow label="Number">
            <Mono>{identity.standard_number}</Mono>
          </DefinitionRow>
          <DefinitionRow label="Catalogue title">
            {identity.catalogue ? (
              <>
                “{identity.catalogue.title}”
                <span className="mt-1 block text-[11px] text-ink-faint">
                  <Mono
                    muted
                    className={cn(
                      "mr-2 text-[10px] uppercase tracking-[0.12em]",
                      identity.catalogue.official ? "text-accent" : "text-review",
                    )}
                  >
                    {identity.catalogue.official ? "BIS catalogue" : "third-party mirror"}
                  </Mono>
                  {identity.catalogue.source_label}
                </span>
                {identity.catalogue.title_suspect && (
                  <span className="mt-1 block text-[11px] text-review">
                    The source returned this title damaged. It is shown exactly as recorded.
                  </span>
                )}
              </>
            ) : (
              <Empty>{identity.catalogue_note}</Empty>
            )}
          </DefinitionRow>
          <DefinitionRow label="Edition">
            {identity.cited_edition ? (
              <>This record cites the {identity.cited_edition} edition.</>
            ) : (
              <Empty>This record's number carries no year, so MetrIQ does not name an edition.</Empty>
            )}
            {identity.editions_known.length > 0 && (
              <span className="mt-1 block text-[12px] text-ink-soft">
                Editions in MetrIQ's evidence: {identity.editions_known.join(" · ")}
              </span>
            )}
          </DefinitionRow>
          <DefinitionRow label="ICS / committee">
            <Empty>{identity.ics_committee_note}</Empty>
          </DefinitionRow>
          <DefinitionRow label="BIS listing">
            {identity.listing_description ? (
              <>
                “{identity.listing_description}”
                <span className="mt-1 block text-[11px] text-ink-faint">
                  BIS's own product wording ·{" "}
                  {identity.listing_url ? (
                    <a href={identity.listing_url} target="_blank" rel="noreferrer" className="hover:underline">
                      {identity.listing_document}
                    </a>
                  ) : (
                    identity.listing_document
                  )}
                  {identity.last_verified ? ` · read ${identity.last_verified}` : ""}
                </span>
              </>
            ) : (
              <Empty>{identity.listing_note}</Empty>
            )}
          </DefinitionRow>
        </dl>
      </Section>

      <Section n={2} title="Coverage level">
        <p className="max-w-2xl text-[13px] leading-relaxed text-ink">
          <Mono muted className={cn("mr-2 text-[10px] uppercase tracking-[0.12em]", clauseLevel && "text-accent")}>
            {coverage.level}
          </Mono>
          {coverage.note}
        </p>
        {clauseLevel && (
          <p className="max-w-2xl text-[12px] leading-relaxed text-review">
            {coverage.clause_count} clauses held. {coverage.completeness}
          </p>
        )}
      </Section>

      <Section n={3} title="Currency">
        {p.currency ? <EditionCurrency currency={p.currency} /> : <Empty>{p.currency_note}</Empty>}
      </Section>

      <Section n={4} title="Legal status">
        <QcoStatus qco={legal.qco} />
        {legal.qco.status === "NOT_ESTABLISHED" && (
          <Empty>{legal.qco.statements.join(" ")}</Empty>
        )}
        {legal.listing_orders ? (
          <>
            {legal.listing_orders.groups.map((g) => (
              <OrderKind key={`${g.scheme}-${g.notification}`} group={g} />
            ))}
            <ListingOrders listing={legal.listing_orders} />
          </>
        ) : (
          <Empty>{legal.listing_note}</Empty>
        )}
      </Section>

      <Section n={5} title="What it covers">
        {p.scope.clauses.length > 0 ? (
          <ClauseList title="Scope" clauses={p.scope.clauses} />
        ) : (
          <Empty>{p.scope.note}</Empty>
        )}
      </Section>

      <Section n={6} title="Requirements">
        {p.requirements.clauses.length > 0 ? (
          <details>
            <summary className="kicker cursor-pointer select-none">
              {p.requirements.clauses.length} further clauses, in clause order
            </summary>
            <div className="mt-4">
              <ClauseList title="Clauses" clauses={p.requirements.clauses} />
            </div>
          </details>
        ) : (
          <Empty>{p.requirements.note}</Empty>
        )}
      </Section>

      <Section n={7} title="Sampling & testing">
        <ClauseGroups standardNumber={number} defaultOpen />
      </Section>

      <Section n={8} title="Certification">
        {cert.loading && <InlineLoading label="Reading the certification journey" />}
        {cert.error != null && <ErrorNote error={cert.error} />}
        {cert.data?.journey ? (
          <CertificationJourney journey={cert.data.journey} />
        ) : (
          cert.data && <Empty>{cert.data.answer || "MetrIQ holds no certification journey for this standard."}</Empty>
        )}
      </Section>

      <Section n={9} title="Testing laboratories">
        {labs.loading && <InlineLoading label="Reading the laboratory snapshot" />}
        {labs.error != null && <ErrorNote error={labs.error} />}
        {labs.data && <LaboratoryResults result={labs.data} />}
      </Section>

      <Section n={10} title="Evidence graph">
        {context.error != null && <ErrorNote error={context.error} />}
        {context.data ? (
          <EvidenceGraphSection source={{ product_context: context.data }} />
        ) : (
          context.loading && <InlineLoading label="Composing the evidence graph" />
        )}
      </Section>

      <Section n={11} title="Sources">
        <ul className="space-y-1.5">
          {p.sources.map((s) => (
            <li key={s.url}>
              <a
                href={s.url}
                target="_blank"
                rel="noreferrer"
                className="group inline-flex items-start gap-1.5 text-[12px] text-ink-soft hover:text-ink"
              >
                <ArrowUpRight className="mt-0.5 h-3 w-3 shrink-0 text-accent" />
                <span>
                  {s.label}
                  <Mono muted className="block break-all text-[11px]">
                    {s.url}
                  </Mono>
                </span>
              </a>
            </li>
          ))}
        </ul>
        <p className="text-[11px] text-ink-faint">
          Only the sources stored with the evidence above.{" "}
          <Link to="/standards" className="text-accent hover:underline">
            Back to standard search
          </Link>
        </p>
      </Section>
    </div>
  );
}
