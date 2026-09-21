import { type FormEvent, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type LanguageChoice } from "@/lib/api";
import { useAsyncTask } from "@/lib/hooks";
import {
  Button,
  InlineLoading,
  PageHeader,
  TextArea,
  TextInput,
} from "@/components/ui";
import {
  Annotation,
  BlueprintField,
  Bracket,
  HeaderMotif,
} from "@/components/decor";
import { GroundedAnswer } from "@/components/GroundedAnswer";
import { CertificationJourney } from "@/components/CertificationJourney";
import { LanguagePicker } from "@/components/LanguagePicker";
import { ErrorNote } from "@/features/StandardsView";
import { CopilotPanel } from "@/features/CopilotPanel";

const EXAMPLES = [
  "How do I get BIS certification for a stainless steel water bottle?",
  "What is the BIS certification process?",
  "Is BIS certification required for an LED lamp?",
];

export function CertificationView() {
  const [params, setParams] = useSearchParams();
  const [question, setQuestion] = useState("");
  const [product, setProduct] = useState("");
  const [language, setLanguage] = useState<LanguageChoice>("auto");
  const task = useAsyncTask(api.certificationGuidance);

  // Deep link from the Standards page or an inspection: ?standard=IS 302.
  // The journey is retrieval-only, so this never waits on the explanation model.
  const deepLink = params.get("standard") ?? "";
  useEffect(() => {
    if (!deepLink) return;
    setParams({}, { replace: true });
    setQuestion(`What certification applies to ${deepLink}?`);
    task.run("", "", deepLink, false, language).catch(() => {});
    // Deliberately keyed on the link alone: it is consumed once, on arrival.
  }, [deepLink]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (q) task.run(q, product.trim(), "", true, language).catch(() => {});
  }

  return (
    <div className="space-y-12">
      <div className="relative">
        <HeaderMotif name="fingerprint" label="Verified source" />
        <PageHeader
          eyebrow="Certification guidance"
          title="BIS certification, grounded in evidence"
          lead="MetrIQ retrieves certification evidence from the BIS knowledge base and asks the configured grounded model to explain only that evidence. When the knowledge base does not support an answer it abstains — it does not decide the legal requirement."
        />
      </div>

      <div className="relative border border-line bg-raised">
        <Bracket tone="accent" />
        <form onSubmit={submit} className="space-y-4 p-5 sm:p-6">
          <div>
            <label className="kicker mb-2 block">Question</label>
            <TextArea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask about the certification process, scheme, or whether certification applies…"
              rows={3}
            />
          </div>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1">
              <label className="kicker mb-2 block">
                Product context <span className="normal-case">(optional)</span>
              </label>
              <TextInput
                value={product}
                onChange={(e) => setProduct(e.target.value)}
                placeholder="e.g. stainless steel water bottle"
              />
            </div>
            <Button type="submit" size="lg" disabled={task.loading || !question.trim()}>
              {task.loading ? <InlineLoading label="Reasoning" /> : "Ask"}
            </Button>
          </div>
          <LanguagePicker value={language} onChange={setLanguage} />
        </form>
        <div className="flex flex-col gap-1.5 border-t border-line px-5 py-3 sm:px-6">
          <span className="kicker">Examples</span>
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => {
                setQuestion(ex);
                task.run(ex, "", "", true, language).catch(() => {});
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

      {task.data?.journey && <CertificationJourney journey={task.data.journey} />}

      {task.data && task.data.note !== "explanation skipped (explain=false)" && (
        <GroundedAnswer
          question={task.data.question}
          answer={task.data.answer}
          grounded={task.data.grounded}
          confidence={task.data.confidence}
          note={task.data.note}
          sources={task.data.sources}
          context={{ label: "Product", value: task.data.product_context }}
          abstentionMessage={
            task.data.answer ||
            "The available BIS knowledge base does not contain sufficient verified information to answer this certification question."
          }
        />
      )}

      {task.data && (
        <CopilotPanel
          context={{ feature: "CERTIFICATION", certification: task.data }}
          language={language}
        />
      )}

      {!task.data && task.error == null && !task.loading && (
        <div className="relative border border-dashed border-line-strong bg-surface p-10">
          <BlueprintField fade="radial" />
          <div className="relative max-w-md">
            <Annotation className="mb-3 inline-flex">Awaiting question</Annotation>
            <div className="text-[15px] font-medium">No question asked yet</div>
            <p className="mt-2 text-[13px] leading-relaxed text-ink-soft">
              The answer, its confidence, and every BIS source used will appear
              here as a single evidence exhibit.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
