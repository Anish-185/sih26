import type { LaboratoryRecord, LaboratorySearchResponse } from "@/lib/api";
import { Callout, Chip, Mono, Panel, PanelHeader } from "@/components/ui";
import { cn } from "@/lib/cn";

const NOT_AVAILABLE = "Not available in the verified MetrIQ record.";

/** How the standard behind these laboratories was established. */
const VIA: Record<string, string> = {
  standard: "You gave the Indian Standard.",
  query: "The Indian Standard was named in your query.",
  product: "Your product was matched to this Indian Standard by deterministic retrieval.",
  text: "Matched on laboratory name, city or listed product text — not a capability statement.",
};

const VALIDITY: Record<LaboratoryRecord["validity_status"], string> = {
  VALID_AT_SNAPSHOT: "Recognition valid at snapshot",
  EXPIRED_AT_SNAPSHOT: "Recognition date had passed at snapshot",
  NOT_STATED: "Validity not stated in the record",
};

function Field({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <dt className="kicker mb-0.5">{label}</dt>
      <dd className={cn("text-[12px]", value ? "text-ink" : "text-ink-faint")}>
        {value ?? NOT_AVAILABLE}
      </dd>
    </div>
  );
}

function LabCard({ record }: { record: LaboratoryRecord }) {
  return (
    <li className="border-b border-line px-5 py-4 last:border-b-0 sm:px-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h4 className="text-[13px] font-medium">{record.lab_name}</h4>
        {record.osl_code && (
          <Mono muted className="text-[11px]">
            OSL {record.osl_code}
          </Mono>
        )}
      </div>

      <p className="mt-1.5 text-[12px] leading-relaxed text-ink-soft">
        {record.why.summary}
      </p>

      <dl className="mt-3 grid gap-x-8 gap-y-2.5 sm:grid-cols-2">
        <Field label="City" value={record.city} />
        <Field label="Listed for" value={record.standard_as_listed} />
        <Field label="Product as listed by BIS" value={record.product_as_listed} />
        <Field label="Grade / type" value={record.grade_or_type} />
        <Field
          label="Recognition validity"
          value={
            record.validity_date
              ? `${record.validity_date} — ${VALIDITY[record.validity_status]}`
              : VALIDITY[record.validity_status]
          }
        />
        <Field label="BIS remark" value={record.remark} />
      </dl>

      <p className="mt-3 text-[11px] text-ink-faint">
        {record.document_name} · retrieved {record.retrieved_on} ·{" "}
        <a
          href={record.source_url}
          target="_blank"
          rel="noreferrer"
          className="underline decoration-line-strong underline-offset-2 transition-colors hover:text-accent"
        >
          official source
        </a>
      </p>
    </li>
  );
}

/**
 * Laboratories BIS's own LIMS listing supports for a standard.
 *
 * Deliberately not a ranking: the list is alphabetical, and nothing here calls
 * a laboratory best, recommended or approved. A laboratory appears because BIS
 * lists it against the standard — or, for a name/city search, because the text
 * matched, which the explanation says plainly.
 */
export function LaboratoryResults({ result }: { result: LaboratorySearchResponse }) {
  const { laboratories, laboratory_standard, laboratory_standard_source, coverage } = result;

  if (laboratories.length === 0) {
    return (
      <Callout tone="abstain" title="No matching verified laboratory record">
        {result.no_match_note}
        {coverage && (
          <p className="mt-2 text-[12px] text-ink-faint">
            MetrIQ's laboratory snapshot currently holds {coverage.records} record
            {coverage.records === 1 ? "" : "s"} across {coverage.laboratories} laborator
            {coverage.laboratories === 1 ? "y" : "ies"} and {coverage.standards} standard
            {coverage.standards === 1 ? "" : "s"}
            {coverage.retrieved_on ? `, retrieved ${coverage.retrieved_on}` : ""}.
          </p>
        )}
      </Callout>
    );
  }

  return (
    <Panel flush>
      <PanelHeader
        title="Testing laboratories"
        meta={
          <span className="font-mono text-[11px]">
            {laboratories.length} record{laboratories.length === 1 ? "" : "s"}
          </span>
        }
      />

      <div className="space-y-2 border-b border-line px-5 py-4 sm:px-6">
        {laboratory_standard && (
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="kicker">Listed for</span>
            <Mono className="text-[12px] font-semibold text-accent">{laboratory_standard}</Mono>
            {laboratory_standard_source && (
              <Chip>{laboratory_standard_source}</Chip>
            )}
          </div>
        )}
        {laboratory_standard_source && (
          <p className="text-[12px] leading-relaxed text-ink-soft">
            {VIA[laboratory_standard_source]}
          </p>
        )}
        <p className="text-[12px] leading-relaxed text-ink-soft">
          Listed alphabetically. This is evidence-backed discovery, not a ranking —
          MetrIQ does not identify a best or recommended laboratory.
        </p>
        {result.other_editions.length > 0 && (
          <p className="text-[12px] leading-relaxed text-review">
            BIS also lists {result.other_editions.join(", ")} separately. A different
            edition is a different standard, so those laboratories are not shown here.
          </p>
        )}
      </div>

      <ol>
        {laboratories.map((record) => (
          <LabCard key={`${record.lab_name}-${record.standard_as_listed}`} record={record} />
        ))}
      </ol>

      {coverage && (
        <div className="border-t border-line bg-surface px-5 py-3 text-[11px] leading-relaxed text-ink-faint sm:px-6">
          {coverage.note} Confirm current scope, availability and contact details with the
          laboratory before arranging testing.
          {coverage.retrieved_on && ` Snapshot retrieved ${coverage.retrieved_on}.`}
        </div>
      )}
    </Panel>
  );
}
