import { type FormEvent, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type LanguageChoice } from "@/lib/api";
import { useAsyncTask } from "@/lib/hooks";
import {
  Button,
  Callout,
  InlineLoading,
  Mono,
  PageHeader,
  TextInput,
} from "@/components/ui";
import {
  Annotation,
  BlueprintField,
  Bracket,
  HeaderMotif,
  PhotoFragment,
} from "@/components/decor";
import { GroundedAnswer } from "@/components/GroundedAnswer";
import { LanguagePicker } from "@/components/LanguagePicker";
import { LaboratoryResults } from "@/components/LaboratoryResults";
import { ErrorNote } from "@/features/StandardsView";
import { CopilotPanel } from "@/features/CopilotPanel";

const EXAMPLES = [
  "Where can I test an electric kettle?",
  "IS 367:1993",
  "laboratories in Noida",
  "packaged drinking water testing",
];

export function LaboratoriesView() {
  const [query, setQuery] = useState("");
  const [standard, setStandard] = useState("");
  const [explain, setExplain] = useState(false);
  const [language, setLanguage] = useState<LanguageChoice>("auto");
  const task = useAsyncTask(api.laboratorySearch);
  const [params, setParams] = useSearchParams();

  // Deep link from product intelligence or an inspection: ?standard=IS 367:1993.
  // Retrieval-only, so it never waits on the local model.
  const deepLink = params.get("standard") ?? "";
  useEffect(() => {
    if (!deepLink) return;
    setParams({}, { replace: true });
    setQuery(deepLink);
    setStandard(deepLink);
    task.run(deepLink, deepLink, false, language).catch(() => {});
    // Consumed once, on arrival.
  }, [deepLink]);

  // Phase 6.1: ?q=helmet from the Ask page when several standards were
  // returned — the product text, so this page does its own lookup and no
  // standard is picked on the user's behalf.
  const productLink = params.get("q") ?? "";
  useEffect(() => {
    if (!productLink || deepLink) return;
    setParams({}, { replace: true });
    setQuery(productLink);
    setStandard("");
    task.run(productLink, "", false, language).catch(() => {});
  }, [productLink]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (q) task.run(q, standard.trim(), explain, language).catch(() => {});
  }

  const res = task.data;

  return (
    <div className="space-y-12">
      <div className="relative">
        <HeaderMotif name="pillar" label="Measurement" width="w-[22%]" />
        <PageHeader
          eyebrow="Laboratory search"
          title="BIS-recognized testing laboratories"
          lead="MetrIQ identifies laboratories from a verified snapshot of BIS's own LIMS listing of IS-wise test facilities. It reports what BIS listed and when, links to the official lists and the LIMS portal, and abstains rather than fabricate laboratory data."
        />
      </div>

      <Callout>
        Laboratory records come from MetrIQ's verified BIS LIMS snapshot
        (retrieved 2026&#8209;09&#8209;19). A record states that BIS listed that
        laboratory for that standard on that date — it does not establish current
        recognition, accreditation, NABL status, test scope or availability, and
        MetrIQ holds no addresses or contact details. Results are ordered
        alphabetically; MetrIQ does not rank laboratories.
      </Callout>

      <div className="relative border border-line bg-raised">
        <Bracket tone="accent" />
        <form onSubmit={submit} className="flex flex-col gap-4 p-5 sm:p-6">
          <TextInput
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. BIS recognised laboratory for testing steel"
            className="h-11"
            autoFocus
          />
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1">
              <label className="kicker mb-2 block">
                Standard / product <span className="normal-case">(optional)</span>
              </label>
              <TextInput
                value={standard}
                onChange={(e) => setStandard(e.target.value)}
                placeholder="e.g. IS 1786"
              />
            </div>
            <Button type="submit" size="lg" disabled={task.loading || !query.trim()}>
              {task.loading ? <InlineLoading label="Searching" /> : "Search"}
            </Button>
          </div>
          <label className="flex items-center gap-2 text-[12px] text-ink-soft">
            <input
              type="checkbox"
              checked={explain}
              onChange={(e) => setExplain(e.target.checked)}
              className="h-3.5 w-3.5 accent-[color:var(--color-accent)]"
            />
            Explain the evidence with the local model
            <span className="text-ink-faint">(slower)</span>
          </label>
          <LanguagePicker value={language} onChange={setLanguage} />
          <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
            <span className="kicker mr-1">Try</span>
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                onClick={() => {
                  setQuery(ex);
                  task.run(ex, "", explain, language).catch(() => {});
                }}
                className="border border-line bg-surface px-2 py-1 font-mono text-[11px] text-ink-soft transition-colors hover:border-ink hover:text-ink"
              >
                {ex}
              </button>
            ))}
          </div>
        </form>
      </div>

      {task.error != null && <ErrorNote error={task.error} />}

      {res && (
        <>
          <LaboratoryResults result={res} />
          {res.standard_context && (
            <div className="flex items-center gap-2 text-[12px]">
              <span className="kicker">Standard context</span>
              <Mono>{res.standard_context}</Mono>
            </div>
          )}
          <GroundedAnswer
            question={res.query}
            answer={res.answer}
            grounded={res.grounded}
            confidence={res.confidence}
            note={res.note}
            sources={res.sources}
            context={{ label: "Standard", value: res.standard_context }}
            abstentionMessage="Insufficient verified laboratory information. No BIS laboratory or testing evidence in the knowledge base matched this query."
          />
          <CopilotPanel
            context={{ feature: "LABORATORY", laboratory: res }}
            language={language}
          />
        </>
      )}

      {!res && task.error == null && !task.loading && (
        <div className="relative overflow-hidden border border-dashed border-line-strong bg-surface p-10">
          <BlueprintField fade="radial" />
          <PhotoFragment
            src="/blue-botanical.png"
            className="absolute inset-y-0 right-0 hidden h-full w-[46%] object-cover object-left opacity-[0.2] [mask-image:linear-gradient(to_left,#000,transparent)] md:block"
          />
          <Bracket tone="line" className="-inset-2" />
          <div className="relative max-w-md">
            <Annotation className="mb-3 inline-flex">Awaiting query</Annotation>
            <div className="text-[15px] font-medium">No search yet</div>
            <p className="mt-2 text-[13px] leading-relaxed text-ink-soft">
              Results link to BIS's official recognised-laboratory lists and the
              LIMS portal (lims.bis.gov.in).
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
