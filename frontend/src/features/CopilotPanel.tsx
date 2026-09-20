/*
  MetrIQ Copilot — a grounded explanation of an inspection that is already finished.

  It is deliberately secondary to the evidence: a panel, not a chat window. It
  reads the record and explains it; it cannot retrieve a standard, evaluate a
  requirement, change PASS / FAIL / REVIEW, edit a declaration or submit an
  officer decision. The deterministic result is shown next to every answer and
  comes from the record, never from the model.

  Nothing here runs on its own — a request is only sent when the officer presses
  a button, because the explanation service runs on a small free daily quota.
*/
import { type FormEvent, useState } from "react";
import { ExternalLink, MessageSquareText, ShieldAlert } from "lucide-react";
import {
  ApiError,
  api,
  type CopilotAnswer,
  type CopilotCapability,
  type CopilotFeatureContext,
  type CopilotInput,
  type InspectionAnalysis,
  type LanguageChoice,
  type SystemResult,
} from "@/lib/api";
import { useAsyncTask, useOnMount } from "@/lib/hooks";
import { Button, Mono, Panel, PanelHeader, Spinner, StatusBadge, TextInput } from "@/components/ui";
import { cn } from "@/lib/cn";

/** The questions offered up front. Everything else goes through the free-text field. */
type Prompt = { code: CopilotCapability; label: string };

const PACKAGE_PROMPTS: Prompt[] = [
  { code: "EXPLAIN_INSPECTION", label: "Explain this inspection" },
  { code: "EXPLAIN_RESULT", label: "Why this result?" },
  { code: "WHAT_IS_MISSING", label: "What information is missing?" },
  { code: "EXPLAIN_ESCALATION", label: "Why does an officer need to review this?" },
  { code: "EXPLAIN_CHECKS", label: "Which requirements were checked?" },
  { code: "EXPLAIN_UNCERTAINTY", label: "Which declarations are uncertain?" },
  { code: "EXPLAIN_EVIDENCE", label: "What evidence supports this result?" },
  { code: "MANUAL_VERIFICATION", label: "What should I verify manually?" },
  { code: "SUMMARIZE", label: "Summarise in simple language" },
];

/** Offered only when the inspection actually carries laboratory records. */
const LABORATORY_PROMPT: Prompt = {
  code: "EXPLAIN_LABORATORY",
  label: "Why were these laboratories returned?",
};

/* Milestone 20 — the same panel over a feature page's own result. One prompt
   each: these contexts are small, and a free-text question covers the rest. */
const FEATURE_PROMPTS: Record<CopilotFeatureContext["feature"], Prompt[]> = {
  STANDARD: [{ code: "EXPLAIN_STANDARD", label: "Why was this standard retrieved?" }],
  CERTIFICATION: [{ code: "EXPLAIN_CERTIFICATION", label: "Explain these certification steps" }],
  LABORATORY: [{ code: "EXPLAIN_LABORATORY", label: "Why were these laboratories returned?" }],
  // Milestone 21 — the context already spans features, so the questions do too.
  PRODUCT: [
    { code: "EXPLAIN_PRODUCT_CONTEXT", label: "Summarise everything MetrIQ found" },
    { code: "EXPLAIN_STANDARD", label: "Why was this standard selected?" },
    { code: "EXPLAIN_CERTIFICATION", label: "Explain the certification route" },
    { code: "EXPLAIN_LABORATORY", label: "Are there laboratory records for this standard?" },
  ],
};

const FEATURE_BLURB: Record<CopilotFeatureContext["feature"], string> = {
  STANDARD:
    "Explains the standards MetrIQ's deterministic retrieval returned for this query, and the evidence behind each. Retrieval confidence is a text-match strength — never a statement that a standard legally applies.",
  CERTIFICATION:
    "Explains the retrieved certification route and its steps. It describes what published BIS information states for this product type — never that any item, manufacturer or licence is certified.",
  LABORATORY:
    "Explains why each laboratory was returned. The records are a dated BIS LIMS snapshot: they never establish current recognition, accreditation, scope or availability, and MetrIQ does not rank laboratories.",
  PRODUCT:
    "Explains MetrIQ's canonical product context — what its deterministic features established about this product, and which features do not apply to it. It connects existing evidence; it never adds any.",
};

const FEATURE_PLACEHOLDER: Record<CopilotFeatureContext["feature"], string> = {
  STANDARD: "Ask about these standards and the evidence behind them…",
  CERTIFICATION: "Ask about this certification route and its evidence…",
  LABORATORY: "Ask about these laboratory records…",
  PRODUCT: "Ask about what MetrIQ found for this product…",
};

const HALLMARK_PROMPT: { code: CopilotCapability; label: string } = {
  code: "EXPLAIN_HALLMARK",
  label: "What does the hallmark / HUID evidence mean?",
};

/** Offered only when the record actually carries certification guidance. */
const CERTIFICATION_PROMPT: { code: CopilotCapability; label: string } = {
  code: "EXPLAIN_CERTIFICATION",
  label: "What certification applies to this product?",
};

const WITHHELD_LABEL: Record<string, string> = {
  FABRICATED_STANDARD: "cited a standard that is not in this record",
  FABRICATED_HUID: "contained a HUID that is not in this record",
  FABRICATED_SOURCE: "cited a source that is not in this record",
  AUTHENTICATION_CLAIM: "claimed an authentication MetrIQ cannot establish",
  CONTRADICTS_SYSTEM_RESULT: "stated a result other than the deterministic one",
  LABORATORY_STATUS_CLAIM: "claimed a laboratory status a dated snapshot cannot establish",
  LABORATORY_RANKING_CLAIM: "ranked or recommended a laboratory, which MetrIQ does not do",
  FABRICATED_AMOUNT: "stated a fee or amount that is not in the evidence",
};

/**
 * `inspectionId` explains a saved record (the officer path), `analysis` the
 * inspection currently on screen, and `context` a feature page's own
 * deterministic result (Milestone 20). Exactly one of them is given.
 */
export function CopilotPanel({
  inspectionId,
  analysis,
  context,
  systemResult,
  hasHallmark,
  language,
}: {
  inspectionId?: string;
  analysis?: InspectionAnalysis;
  context?: CopilotFeatureContext;
  systemResult?: SystemResult;
  hasHallmark?: boolean;
  language?: LanguageChoice;
}) {
  const status = useOnMount(api.copilotStatus);
  const task = useAsyncTask(api.copilotExplain);
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState<string>("");
  // The free budget as of the last answer, so the footer stays honest.
  const [used, setUsed] = useState<{ daily_remaining: number; daily_limit: number } | null>(null);

  const feature = context?.feature;
  let prompts: Prompt[];
  if (feature) {
    prompts = FEATURE_PROMPTS[feature];
  } else {
    const base = hasHallmark
      ? [PACKAGE_PROMPTS[0], HALLMARK_PROMPT, ...PACKAGE_PROMPTS.slice(1)]
      : PACKAGE_PROMPTS;
    prompts = analysis?.certification ? [...base, CERTIFICATION_PROMPT] : base;
    if (analysis?.laboratories?.length) prompts = [...prompts, LABORATORY_PROMPT];
  }
  const configured = status.data?.configured ?? true;
  const budget = status.data;
  const remaining = used?.daily_remaining ?? budget?.daily_remaining ?? 0;
  const limit = used?.daily_limit ?? budget?.daily_limit ?? 0;
  const exhausted = budget ? remaining <= 0 : false;

  function ask(capability: CopilotCapability, text = "") {
    const body: CopilotInput = { capability, ...(text ? { question: text } : {}) };
    if (language) body.language = language;
    if (context) body.context = context;
    else if (inspectionId) body.inspection_id = inspectionId;
    else if (analysis) body.analysis = analysis;
    setAsked(text || prompts.find((p) => p.code === capability)?.label || "");
    task
      .run(body)
      .then((answer) => {
        const usage = answer.usage as { daily_remaining?: number; daily_limit?: number };
        if (typeof usage?.daily_remaining === "number" && typeof usage.daily_limit === "number") {
          setUsed({ daily_remaining: usage.daily_remaining, daily_limit: usage.daily_limit });
        }
      })
      .catch(() => {});
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const text = question.trim();
    if (!text) return;
    ask("QUESTION", text);
    setQuestion("");
  }

  const answer = task.data;

  return (
    <Panel flush>
      <PanelHeader
        title="MetrIQ Copilot"
        meta={
          <span className="inline-flex items-center gap-2">
            <Mono muted className="text-[10px] uppercase tracking-[0.16em]">
              {feature ? "Grounded in the retrieved evidence" : "Grounded in this inspection"}
            </Mono>
          </span>
        }
      />

      <div className="border-b border-line px-5 py-3 sm:px-6">
        <p className="text-[12px] leading-relaxed text-ink-soft">
          {feature ? (
            FEATURE_BLURB[feature]
          ) : (
            <>
              Explains the evidence on this page in plain language. It reads the record only — it does
              not retrieve standards, run checks, or change the system result
              {systemResult && (
                <>
                  , which stays <StatusBadge status={systemResult} size="sm" />
                </>
              )}{" "}
              whatever the explanation says.
            </>
          )}
        </p>
      </div>

      {!configured ? (
        <p className="px-5 py-4 text-[12px] leading-relaxed text-ink-soft sm:px-6">
          No explanation service is configured on this server. Every inspection result, check and source
          on this page remains available.
        </p>
      ) : (
        <>
          <div className="flex flex-wrap gap-2 px-5 py-4 sm:px-6">
            {prompts.map((prompt, index) => (
              <button
                key={prompt.code}
                type="button"
                disabled={task.loading || exhausted}
                onClick={() => ask(prompt.code)}
                className={cn(
                  "rounded-sm border px-3 py-1.5 text-left text-[12px] transition-colors disabled:opacity-45",
                  index === 0
                    ? "border-accent bg-accent-soft text-accent hover:border-accent-hover"
                    : "border-line-strong text-ink-soft hover:border-ink hover:text-ink",
                )}
              >
                {prompt.label}
              </button>
            ))}
          </div>

          <form onSubmit={submit} className="flex gap-2 border-t border-line px-5 py-3 sm:px-6">
            <TextInput
              value={question}
              maxLength={400}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder={feature ? FEATURE_PLACEHOLDER[feature] : "Ask about the evidence in this inspection…"}
              aria-label="Ask about the evidence on this page"
            />
            <Button type="submit" size="sm" variant="secondary" disabled={task.loading || !question.trim() || exhausted}>
              <MessageSquareText className="h-3.5 w-3.5" />
              Ask
            </Button>
          </form>

          {task.loading && (
            <div className="flex items-center gap-2 border-t border-line px-5 py-4 text-[12px] text-ink-soft sm:px-6">
              <Spinner className="h-3.5 w-3.5" />
              {feature ? "Reading the retrieved evidence…" : "Reading the inspection record…"}
            </div>
          )}

          {task.error != null && !task.loading && <ErrorLine error={task.error} />}

          {answer && !task.loading && <Answer answer={answer} asked={asked} />}

          {budget && (
            <p className="border-t border-line px-5 py-2.5 text-[11px] text-ink-faint sm:px-6">
              <Mono muted className="text-[10px]">
                {budget.model}
              </Mono>{" "}
              · explanations are generated only when you ask · {remaining} of {limit} left today
            </p>
          )}
        </>
      )}
    </Panel>
  );
}

/* ----------------------------------------------------------------- answer --- */

function Answer({ answer, asked }: { answer: CopilotAnswer; asked: string }) {
  return (
    <div className="border-t border-line">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-2.5 sm:px-6">
        <Mono muted className="text-[10px] uppercase tracking-[0.16em]">
          {answer.withheld ? "Explanation withheld" : "Grounded in MetrIQ evidence"}
        </Mono>
        {answer.system_result ? (
          <span className="inline-flex items-center gap-2 text-[11px] text-ink-faint">
            System result
            <StatusBadge status={answer.system_result} size="sm" />
          </span>
        ) : (
          <Mono muted className="text-[10px] uppercase tracking-[0.16em]">
            {answer.context_type} evidence
          </Mono>
        )}
      </div>

      <div className="px-5 py-4 sm:px-6">
        {asked && (
          <p className="mb-3 text-[12px] italic text-ink-faint">{asked}</p>
        )}

        {answer.withheld && (
          <div className="mb-3 flex gap-3 border border-review-line bg-review-soft p-3 text-[12px] leading-relaxed">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-review" />
            <div>
              <span className="font-medium text-ink">MetrIQ rejected the generated explanation</span> — it{" "}
              {WITHHELD_LABEL[answer.withheld_reason] ?? "did not match MetrIQ's own evidence"}. The
              deterministic evidence on this page is unaffected.
            </div>
          </div>
        )}

        {answer.answer.split(/\n{2,}/).map((paragraph, i) => (
          <p key={i} className="mb-3 text-[13.5px] leading-relaxed text-ink last:mb-0">
            {paragraph}
          </p>
        ))}

        {answer.evidence.length > 0 && (
          <div className="mt-4">
            <div className="kicker mb-2">Evidence used</div>
            <ul className="space-y-1.5">
              {answer.evidence.map((item, i) => (
                <li key={i} className="flex flex-wrap gap-x-2 text-[12px] leading-relaxed text-ink-soft">
                  <span className="min-w-0">{item.claim}</span>
                  {item.source && (
                    <Mono muted className="text-[10px]">
                      {item.source}
                    </Mono>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {answer.limitations.length > 0 && (
          <div className="mt-4">
            <div className="kicker mb-2">What this cannot establish</div>
            <ul className="space-y-1.5">
              {answer.limitations.map((item, i) => (
                <li key={i} className="text-[12px] leading-relaxed text-ink-soft">
                  {item}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {answer.sources.length > 0 && (
        <div className="border-t border-line px-5 py-4 sm:px-6">
          <div className="kicker mb-2">Sources stored with this evidence</div>
          <ul className="space-y-2.5">
            {answer.sources.map((source, i) => (
              <li key={i} className="text-[12px] leading-relaxed">
                <div className="flex flex-wrap items-baseline gap-2">
                  <Mono muted className="text-[10px] uppercase tracking-[0.1em]">
                    {source.authority === "LEGAL_METROLOGY" ? "Legal Metrology" : "BIS"}
                  </Mono>
                  <span className="text-ink">{source.title}</span>
                  {source.reference && <Mono muted className="text-[10px]">{source.reference}</Mono>}
                </div>
                {source.quote && (
                  <p className="mt-1 border-l border-line pl-3 text-ink-soft">“{source.quote}”</p>
                )}
                {source.source_url && (
                  <a
                    href={source.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 inline-flex items-center gap-1 text-[11px] text-accent hover:text-accent-hover"
                  >
                    <ExternalLink className="h-3 w-3" />
                    Official source
                  </a>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ErrorLine({ error }: { error: unknown }) {
  const detail =
    error instanceof ApiError
      ? error.detail
      : "The explanation service is temporarily unavailable. The underlying MetrIQ inspection remains available.";
  return (
    <p className="border-t border-line px-5 py-4 text-[12px] leading-relaxed text-ink-soft sm:px-6">
      {detail}
    </p>
  );
}
