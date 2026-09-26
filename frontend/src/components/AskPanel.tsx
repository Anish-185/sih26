import { type FormEvent, useState } from "react";
import { api, type Confidence, type ConversationContext, type LanguageChoice } from "@/lib/api";
import { useAsyncTask } from "@/lib/hooks";
import { ArrowLink, Button, Chip, InlineLoading, TextArea } from "@/components/ui";
import { Annotation, BlueprintField, Bracket } from "@/components/decor";
import { GroundedAnswer } from "@/components/GroundedAnswer";
import { LanguagePicker } from "@/components/LanguagePicker";
import { ErrorNote } from "@/features/StandardsView";

/**
 * The grounded BIS Q&A surface (POST /ask): question in any of the three
 * supported languages, the answer, and every verified BIS record behind it.
 *
 * Shared by the Ask page and the Hallmarking page, which differ only in their
 * examples and their empty-state copy — the retrieval, the evidence and the
 * trust boundary are identical, so they are not written twice.
 */
export function AskPanel({
  examples,
  placeholder,
  emptyHint,
  abstentionMessage = "The available BIS knowledge base does not contain enough verified information to answer this reliably.",
}: {
  examples: string[];
  placeholder: string;
  emptyHint: string;
  abstentionMessage?: string;
}) {
  const [question, setQuestion] = useState("");
  // Milestone 17: the answer language. Evidence and sources are identical in
  // every language — only the prose changes.
  const [language, setLanguage] = useState<LanguageChoice>("auto");
  const task = useAsyncTask(api.ask);
  // Phase 6: the previous answer's context, sent with the next question so a
  // follow-up ("is it mandatory?") can refer back. Nothing is stored server-side.
  const [context, setContext] = useState<ConversationContext | null>(null);

  function ask(q: string) {
    task
      .run(q, language, context)
      .then((r) => setContext(r.context))
      .catch(() => {});
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (q) ask(q);
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
      <div className="relative border border-line bg-raised">
        <Bracket tone="accent" />
        <form onSubmit={submit} className="space-y-4 p-5 sm:p-6">
          <label className="kicker mb-2 block">Question</label>
          <TextArea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder={placeholder}
            rows={3}
          />
          {context && (
            <div className="flex flex-wrap items-center gap-2 text-[12px] text-ink-soft">
              <span>Follow-up questions can refer to</span>
              <Chip>{context.product}</Chip>
              <button
                type="button"
                onClick={() => setContext(null)}
                className="text-ink-faint underline-offset-2 transition-colors hover:text-accent hover:underline"
              >
                Clear
              </button>
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <LanguagePicker value={language} onChange={setLanguage} />
            <Button type="submit" size="lg" disabled={task.loading || !question.trim()}>
              {task.loading ? <InlineLoading label="Reasoning" /> : "Ask"}
            </Button>
          </div>
        </form>
        <div className="flex flex-col gap-1.5 border-t border-line px-5 py-3 sm:px-6">
          <span className="kicker">Examples</span>
          {examples.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => {
                setQuestion(ex);
                ask(ex);
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

      {res?.context && (
        <div className="-mb-8 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-ink-soft">
          {res.inherited && (
            <p>
              Answering about <span className="font-medium text-ink">{res.inherited}</span>, from
              your previous question.
            </p>
          )}
          {/* One standard: link it exactly as stored. Several: the product
              query, so MetrIQ never picks one on the user's behalf. */}
          <ArrowLink
            to={
              res.context.standard_numbers.length === 1
                ? `/laboratories?standard=${encodeURIComponent(res.context.standard_numbers[0])}`
                : `/laboratories?q=${encodeURIComponent(res.context.product)}`
            }
          >
            {res.context.standard_numbers.length === 1
              ? `Testing laboratories for ${res.context.standard_numbers[0]}`
              : `Testing laboratories for ${res.context.product}`}
          </ArrowLink>
        </div>
      )}
      {res && (
        <GroundedAnswer
          question={res.question}
          answer={res.answer}
          grounded={res.grounded}
          confidence={confidence}
          note=""
          sources={res.sources}
          context={null}
          abstentionMessage={abstentionMessage}
          explained={res.explained}
          boundary={res.boundary}
          clauses={res.clauses ?? []}
          fallbackReason={res.fallback_reason}
        />
      )}

      {!res && task.error == null && !task.loading && (
        <div className="relative border border-dashed border-line-strong bg-surface p-10">
          <BlueprintField fade="radial" />
          <div className="relative max-w-md">
            <Annotation className="mb-3 inline-flex">Awaiting question</Annotation>
            <div className="text-[15px] font-medium">No question asked yet</div>
            <p className="mt-2 text-[13px] leading-relaxed text-ink-soft">{emptyHint}</p>
          </div>
        </div>
      )}
    </div>
  );
}
