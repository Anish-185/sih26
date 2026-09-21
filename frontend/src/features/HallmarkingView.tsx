import { type FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Save, ScanSearch } from "lucide-react";
import { ApiError, api, type Confidence, type InspectionAnalysis, type LanguageChoice } from "@/lib/api";
import { useAsyncTask } from "@/lib/hooks";
import {
  Button,
  Callout,
  InlineLoading,
  Mono,
  PageHeader,
  SectionHeading,
  TextArea,
  TextInput,
} from "@/components/ui";
import { Dropzone } from "@/components/Dropzone";
import { ResolutionPanel } from "@/features/records";
import { HallmarkEvidencePanel } from "@/features/HallmarkEvidence";
import {
  Annotation,
  BlueprintField,
  Bracket,
  HeaderMotif,
} from "@/components/decor";
import { GroundedAnswer } from "@/components/GroundedAnswer";
import { LanguagePicker } from "@/components/LanguagePicker";
import { ErrorNote } from "@/features/StandardsView";

const EXAMPLES = [
  "What is HUID and how can a consumer verify it?",
  "What are the three marks on a hallmarked gold article?",
  "What should I check when buying hallmarked jewellery?",
  "Which gold purities can be hallmarked in India?",
  "Is hallmarking of gold jewellery mandatory?",
];

export function HallmarkingView() {
  const [question, setQuestion] = useState("");
  // Milestone 17: the answer language. Evidence and sources are identical in
  // every language — only the prose changes.
  const [language, setLanguage] = useState<LanguageChoice>("auto");
  const task = useAsyncTask(api.ask);

  function submit(e: FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (q) task.run(q, language).catch(() => {});
  }

  const res = task.data;
  // /ask has no confidence field; derive it from the retrieved evidence.
  const confidence: Confidence = res
    ? res.grounded
      ? ((res.sources[0]?.confidence as Confidence) ?? "medium")
      : "none"
    : "none";

  return (
    <div className="space-y-12">
      <div className="relative">
        <HeaderMotif name="dome" label="Heritage · craft" width="w-[24%]" />
        <PageHeader
          eyebrow="Hallmarking / HUID"
          title="Hallmarking & HUID information"
          lead="Inspect a hallmark photo for evidence — potential HUID, purity mark, BIS text — and ask grounded questions about BIS hallmarking. MetrIQ observes and extracts hallmark evidence; it never authenticates a HUID."
        />
      </div>

      <Callout>
        MetrIQ does not run live HUID verification. To check a real article, use
        the six-digit HUID printed on it with the BIS Care App, as BIS describes
        below.
      </Callout>

      <HallmarkInspection />

      <SectionHeading kicker="Ask" title="Hallmarking & HUID questions" />

      <div className="relative border border-line bg-raised">
        <Bracket tone="accent" />
        <form onSubmit={submit} className="space-y-4 p-5 sm:p-6">
          <label className="kicker mb-2 block">Question</label>
          <TextArea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask about hallmarking, HUID, purity grades, or consumer verification…"
            rows={3}
          />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <LanguagePicker value={language} onChange={setLanguage} />
            <Button type="submit" size="lg" disabled={task.loading || !question.trim()}>
              {task.loading ? <InlineLoading label="Reasoning" /> : "Ask"}
            </Button>
          </div>
        </form>
        <div className="flex flex-col gap-1.5 border-t border-line px-5 py-3 sm:px-6">
          <span className="kicker">Examples</span>
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => {
                setQuestion(ex);
                task.run(ex, language).catch(() => {});
              }}
              className="text-left text-[12px] text-ink-soft transition-colors hover:text-accent"
            >
              {ex}
            </button>
          ))}
        </div>
      </div>

      {task.loading && (
        <p className="flex items-center gap-2 text-[12px] text-ink-faint">
          <span className="h-1 w-1 animate-pulse bg-accent" />
          The grounded model is reading the retrieved BIS evidence — this can take
          a moment.
        </p>
      )}
      {task.error != null && <ErrorNote error={task.error} />}

      {res && (
        <GroundedAnswer
          question={res.question}
          answer={res.answer}
          grounded={res.grounded}
          confidence={confidence}
          note=""
          sources={res.sources}
          context={null}
          abstentionMessage="The available BIS knowledge base does not contain enough verified information to answer this reliably."
        />
      )}

      {!res && task.error == null && !task.loading && (
        <div className="relative border border-dashed border-line-strong bg-surface p-10">
          <BlueprintField fade="radial" />
          <div className="relative max-w-md">
            <Annotation className="mb-3 inline-flex">Awaiting question</Annotation>
            <div className="text-[15px] font-medium">No question asked yet</div>
            <p className="mt-2 text-[13px] leading-relaxed text-ink-soft">
              The answer and every BIS source used will appear here. Sources come
              from the BIS Hallmarking FAQ, the mandatory-hallmarking order, and
              BIS consumer pages.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------ hallmark inspection --- */

/**
 * Photo -> OCR -> hallmark evidence -> what MetrIQ could not establish. The analysis runs as a
 * HALLMARK inspection: Legal Metrology package-label rules are not applied to jewellery.
 */
function HallmarkInspection() {
  const [files, setFiles] = useState<File[]>([]);
  const [previews, setPreviews] = useState<string[]>([]);
  const [reference, setReference] = useState("");
  const analyse = useAsyncTask(analyseHallmark);
  const save = useAsyncTask(saveHallmark);
  const navigate = useNavigate();

  useEffect(() => {
    const urls = files.map((f) => URL.createObjectURL(f));
    setPreviews(urls);
    return () => urls.forEach((u) => URL.revokeObjectURL(u));
  }, [files]);

  const result: InspectionAnalysis | null = analyse.data;
  const hallmark = result?.hallmark ?? null;

  return (
    <section className="space-y-6">
      <SectionHeading kicker="Inspect" title="Inspect a hallmark photo" />
      <div className="relative border border-line bg-raised">
        <Bracket tone="accent" />
        <div className="space-y-4 p-5 sm:p-6">
          <Dropzone
            onFiles={(f) => {
              setFiles(f.slice(0, 6));
              analyse.reset();
              save.reset();
            }}
            disabled={analyse.loading || save.loading}
          />
          {previews.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {previews.map((u, i) => (
                <img key={u} src={u} alt={`Hallmark photo ${i + 1}`} className="h-24 border border-line object-contain" />
              ))}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" disabled={!files.length || analyse.loading} onClick={() => analyse.run(files, reference).catch(() => {})}>
              <ScanSearch className="h-3.5 w-3.5" />
              {analyse.loading ? "Reading the hallmark…" : "Analyse hallmark evidence"}
            </Button>
            {result && (
              <Button
                size="sm"
                variant="secondary"
                disabled={save.loading}
                onClick={() =>
                  save
                    .run(files, reference)
                    .then((r) => navigate(`/history/${r.inspection_id}`))
                    .catch(() => {})
                }
              >
                <Save className="h-3.5 w-3.5" />
                {save.loading
                  ? "Saving…"
                  : "Save inspection"}
              </Button>
            )}
          </div>
          {[analyse.error, save.error].map((e, i) =>
            e != null ? (
              <p key={i} className="text-[12px] text-review">
                {e instanceof ApiError ? e.detail : "The hallmark photo could not be processed."}
              </p>
            ) : null,
          )}
        </div>
      </div>

      {result && hallmark && (
        <>
          {result.escalation && (
            <ResolutionPanel
              required={result.escalation.required}
              reasons={result.escalation.reasons}
            />
          )}
          <HallmarkEvidencePanel hallmark={hallmark} />

          <div className="border border-line bg-raised px-5 py-4">
            <label className="kicker mb-1.5 block" htmlFor="huid-reference">
              HUID for reference (optional)
            </label>
            <TextInput
              id="huid-reference"
              value={reference}
              maxLength={12}
              onChange={(e) => setReference(e.target.value)}
              placeholder="Type the HUID you see on the article"
            />
            <p className="mt-2 text-[12px] leading-relaxed text-ink-soft">
              {hallmark?.user_huid
                ? hallmark.user_huid.note
                : "Enter the HUID printed on the article and analyse again. MetrIQ records it as " +
                  "user-provided and compares it with the text OCR read — it does not verify anything."}
            </p>
            <p className="mt-1 text-[12px] font-medium text-ink">
              External authoritative HUID verification required.{" "}
              <Mono muted className="text-[11px]">
                Not verified by MetrIQ
              </Mono>
            </p>
          </div>
        </>
      )}
    </section>
  );
}

const analyseHallmark = (files: File[], huid = "") =>
  api.analyzeInspection(files.map((file) => ({ file, side: "UNKNOWN" as const })), "HALLMARK", huid);
const saveHallmark = (files: File[], huid = "") =>
  api.saveInspection(files.map((file) => ({ file, side: "UNKNOWN" as const })), "HALLMARK", huid);
