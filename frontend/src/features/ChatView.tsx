import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  ApiError,
  type AskResponse,
  type Confidence,
  type ConversationContext,
  type LanguageChoice,
  type ProductStandardResult,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { passportByNumber } from "@/lib/format";
import { ArrowLink, Button, Callout, Chip, ConfidenceMeter, Mono, TextArea } from "@/components/ui";
import { Prose, SourceRow } from "@/components/GroundedAnswer";
import { CoverageBoundaryPanel } from "@/components/CoverageBoundary";
import { ClauseList } from "@/components/ClauseText";
import { QcoStatus } from "@/components/QcoStatus";
import { ListingOrders } from "@/components/ListingOrders";
import { LanguagePicker } from "@/components/LanguagePicker";

/**
 * Phase UI-1 — the one place to ask MetrIQ a question: a conversation on the
 * left, the evidence behind the SELECTED answer on the right, always open.
 *
 * Nothing new on the server. Every turn is one POST /ask; the previous answer's
 * Phase 6 context object is sent back with the next question exactly as the Ask
 * panel's follow-up chip always did, and the thread lives only in this page's
 * state. Why-this-result, QCO status and listing orders are not part of /ask's
 * response, so they come from the existing read-only POST /product-standard for
 * the product and the standards that answer's context already named.
 */

const EXAMPLES = [
  "which standard applies to packaged drinking water?",
  "which standard applies to my LED bulb?",
  "what is HUID?",
  "shampoo",
];

interface Turn {
  id: number;
  question: string;
  language: LanguageChoice;
  /** The context sent WITH this question — reused verbatim on retry. */
  sentContext: ConversationContext | null;
  state: "pending" | "done" | "error";
  response?: AskResponse;
  error?: unknown;
  /** Product -> Standard results for the standards this answer's context named. */
  why?: { state: "loading" | "done" | "error"; results: ProductStandardResult[] };
}

export function ChatView() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [language, setLanguage] = useState<LanguageChoice>("auto");
  // Phase 6: the context the NEXT question will carry. Null after an abstention,
  // after "Clear" and after a new conversation.
  const [context, setContext] = useState<ConversationContext | null>(null);
  const nextId = useRef(1);
  // Bumped by "New conversation" so an answer still in flight is dropped.
  const conversation = useRef(0);
  const threadEnd = useRef<HTMLDivElement>(null);

  const pending = turns.some((t) => t.state === "pending");
  const started = turns.length > 0;

  useEffect(() => {
    threadEnd.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [turns.length, pending]);

  function patch(id: number, change: Partial<Turn>) {
    setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, ...change } : t)));
  }

  function run(turn: Turn) {
    const gen = conversation.current;
    api
      .ask(turn.question, turn.language, turn.sentContext)
      .then((res) => {
        if (gen !== conversation.current) return;
        patch(turn.id, { state: "done", response: res, error: undefined });
        setContext(res.context);
        setSelectedId(turn.id);
        if (res.context) loadWhy(turn.id, res.context, turn.language, gen);
      })
      .catch((error) => {
        if (gen !== conversation.current) return;
        patch(turn.id, { state: "error", error });
      });
  }

  function loadWhy(id: number, ctx: ConversationContext, lang: LanguageChoice, gen: number) {
    patch(id, { why: { state: "loading", results: [] } });
    api
      .productStandard(ctx.product, 6, lang)
      .then((r) => {
        if (gen !== conversation.current) return;
        const results = r.results.filter((x) => ctx.standard_numbers.includes(x.standard_number));
        patch(id, { why: { state: "done", results } });
      })
      .catch(() => {
        if (gen === conversation.current) patch(id, { why: { state: "error", results: [] } });
      });
  }

  function send(text: string) {
    const question = text.trim();
    if (!question || pending) return;
    const turn: Turn = {
      id: nextId.current++,
      question,
      language,
      sentContext: context,
      state: "pending",
    };
    setTurns((ts) => [...ts, turn]);
    setInput("");
    run(turn);
  }

  function retry(turn: Turn) {
    if (pending) return;
    patch(turn.id, { state: "pending", error: undefined });
    run({ ...turn, state: "pending" });
  }

  function newConversation() {
    conversation.current++;
    setTurns([]);
    setSelectedId(null);
    setContext(null);
    setInput("");
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, Shift+Enter is a new line; never send mid-composition (Hindi / Telugu IMEs).
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send(input);
    }
  }

  const answered = turns.filter((t) => t.state === "done");
  const newestAnswered = answered[answered.length - 1];
  const selected = turns.find((t) => t.id === selectedId && t.state === "done");

  const composer = (
    <div className="border border-line bg-raised">
      <TextArea
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder={
          started
            ? "Ask a follow-up, or a new question…"
            : "Ask about Indian Standards, certification, testing, hallmarking or BIS services…"
        }
        rows={started ? 2 : 3}
        className="!border-0 !bg-transparent resize-none"
        aria-label="Question"
      />
      {context && (
        <div className="flex flex-wrap items-center gap-2 border-t border-line px-3 py-2 text-[12px] text-ink-soft">
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
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-3 py-2">
        <LanguagePicker value={language} onChange={setLanguage} />
        <div className="flex items-center gap-3">
          <Mono muted className="hidden text-[10px] sm:inline">
            Enter to send · Shift+Enter for a new line
          </Mono>
          <Button type="button" size="sm" onClick={() => send(input)} disabled={pending || !input.trim()}>
            Ask
          </Button>
        </div>
      </div>
    </div>
  );

  if (!started) {
    return (
      <div className="mx-auto max-w-2xl py-6 sm:py-14">
        <span className="eyebrow !text-ink-faint">Ask BIS</span>
        <h1 className="display mt-3 text-[1.9rem] leading-[1.1] sm:text-[2.3rem]">
          Ask about Indian Standards & BIS services
        </h1>
        <p className="mt-4 text-[14px] leading-relaxed text-ink-soft">
          MetrIQ answers from verified BIS records only — standards, certification, testing
          laboratories and hallmarking — in English, Hindi or Telugu, and shows every record
          it used beside the answer. When the evidence is not enough, it says so.
        </p>
        <div className="mt-8">{composer}</div>
        <div className="mt-5 flex flex-wrap items-center gap-2">
          <span className="kicker mr-1">Try</span>
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => send(ex)}
              className="border border-line-strong bg-surface px-2.5 py-1 text-[12px] text-ink-soft transition-colors hover:border-accent hover:text-accent"
            >
              {ex}
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="ink-in grid gap-8 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:gap-10">
      {/* conversation */}
      <section className="flex min-w-0 flex-col lg:sticky lg:top-[92px] lg:h-[calc(100vh-124px)]">
        <div className="flex items-center justify-between gap-3 border-b border-line pb-3">
          <span className="kicker">Conversation</span>
          <Button type="button" variant="ghost" size="sm" onClick={newConversation}>
            New conversation
          </Button>
        </div>

        <ol className="flex-1 space-y-6 py-6 lg:overflow-y-auto lg:pr-2">
          {turns.map((t) => (
            <li key={t.id} className="space-y-3">
              <div className="ml-auto max-w-[88%] border border-line bg-surface px-3.5 py-2.5 text-[14px] leading-relaxed text-ink">
                {t.question}
              </div>
              {t.state === "pending" && <Typing />}
              {t.state === "error" && (
                <BusyMessage error={t.error} onRetry={() => retry(t)} disabled={pending} />
              )}
              {t.state === "done" && t.response && (
                <>
                  <AnswerMessage
                    turn={t}
                    selected={t.id === selectedId}
                    onSelect={() => setSelectedId(t.id)}
                    canClear={t.id === newestAnswered?.id && context != null}
                    onClear={() => setContext(null)}
                  />
                  {/* phone width: the evidence sits directly under each answer */}
                  <details open={t.id === newestAnswered?.id} className="border border-line lg:hidden">
                    <summary className="cursor-pointer select-none px-4 py-2.5">
                      <span className="kicker">Evidence for this answer</span>
                    </summary>
                    <div className="border-t border-line">
                      <EvidencePanel turn={t} />
                    </div>
                  </details>
                </>
              )}
            </li>
          ))}
          <div ref={threadEnd} />
        </ol>

        <div className="sticky bottom-0 bg-paper pb-2 pt-1 lg:static lg:pb-0">{composer}</div>
      </section>

      {/* evidence for the selected answer — desktop */}
      <aside className="hidden min-w-0 lg:block">
        {selected ? (
          <div key={selected.id} className="ink-in border border-line bg-raised">
            <EvidencePanel turn={selected} />
          </div>
        ) : (
          <div className="border border-dashed border-line-strong bg-surface p-8 text-[13px] text-ink-soft">
            The evidence behind the answer appears here as soon as it arrives.
          </div>
        )}
      </aside>
    </div>
  );
}

/* ------------------------------------------------------------ messages --- */

function Typing() {
  return (
    <div className="flex items-center gap-2 px-1 text-[12px] text-ink-faint" aria-live="polite">
      <span className="flex gap-1">
        <span className="h-1.5 w-1.5 animate-pulse bg-accent" />
        <span className="h-1.5 w-1.5 animate-pulse bg-accent [animation-delay:150ms]" />
        <span className="h-1.5 w-1.5 animate-pulse bg-accent [animation-delay:300ms]" />
      </span>
      MetrIQ is reading the retrieved BIS records…
    </div>
  );
}

function BusyMessage({ error, onRetry, disabled }: { error: unknown; onRetry: () => void; disabled: boolean }) {
  const status = error instanceof ApiError ? error.status : -1;
  const text =
    status === 429 || status === 503 || status === 408
      ? "MetrIQ is busy right now and could not answer this question. Nothing was lost — try again in a moment."
      : status === 0
        ? "MetrIQ could not reach its backend. Check that the API is running, then try again."
        : "MetrIQ could not answer this question just now. Try again in a moment.";
  return (
    <div className="border-l-2 border-review bg-surface px-4 py-3">
      <p className="text-[13px] leading-relaxed text-ink-soft">{text}</p>
      <Button type="button" variant="secondary" size="sm" className="mt-3" onClick={onRetry} disabled={disabled}>
        Retry
      </Button>
    </div>
  );
}

function AnswerMessage({
  turn,
  selected,
  onSelect,
  canClear,
  onClear,
}: {
  turn: Turn;
  selected: boolean;
  onSelect: () => void;
  canClear: boolean;
  onClear: () => void;
}) {
  const res = turn.response!;
  return (
    <div className="space-y-1.5">
      {res.inherited && (
        <p className="px-1 text-[11px] text-ink-faint">
          Answering about <span className="text-ink-soft">{res.inherited}</span>, from your previous question.
          {canClear && (
            <button
              type="button"
              onClick={onClear}
              className="ml-2 underline-offset-2 transition-colors hover:text-accent hover:underline"
            >
              Clear
            </button>
          )}
        </p>
      )}
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        className={cn(
          "block w-full border-l-2 py-1 pl-4 pr-1 text-left transition-colors",
          selected ? "border-accent" : "border-line hover:border-line-strong",
        )}
      >
        <Mono muted className="mb-2 block text-[10px] uppercase tracking-[0.18em]">
          {!res.grounded
            ? "MetrIQ · no answer from verified records"
            : res.explained
              ? "MetrIQ · grounded answer"
              : "MetrIQ · evidence only, no AI explanation"}
          {selected && <span className="ml-2 text-accent">· evidence shown</span>}
        </Mono>
        {res.grounded ? (
          <Prose text={res.answer} />
        ) : (
          <p className="text-[14px] leading-relaxed text-ink">
            {res.boundary?.lines[1] ?? res.answer}
          </p>
        )}
      </button>
    </div>
  );
}

/* ------------------------------------------------------------ evidence --- */

function EvidencePanel({ turn }: { turn: Turn }) {
  const res = turn.response!;
  const confidence: Confidence = res.grounded
    ? ((res.sources[0]?.confidence as Confidence) ?? "medium")
    : "none";
  const standards = res.context?.standard_numbers ?? [];

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3">
        <div className="min-w-0">
          <span className="kicker block">Evidence</span>
          <p className="mt-1 truncate text-[13px] text-ink">{res.question}</p>
        </div>
        <ConfidenceMeter confidence={confidence} />
      </div>

      <div className="space-y-6 px-5 py-5">
        {!res.grounded ? (
          res.boundary ? (
            <CoverageBoundaryPanel boundary={res.boundary} />
          ) : (
            <Callout tone="abstain" title="Insufficient verified evidence">
              {res.answer}
            </Callout>
          )
        ) : (
          !res.explained && (
            <div className="border-l-2 border-review bg-surface px-4 py-3">
              <Mono muted className="text-[10px] uppercase tracking-[0.18em]">
                Evidence only — no AI explanation
              </Mono>
              <p className="mt-1.5 text-[12px] leading-relaxed text-ink-soft">
                MetrIQ retrieved these records and rendered them itself. The evidence and its sources are
                unchanged.
              </p>
            </div>
          )
        )}

        {standards.length > 0 && (
          <div>
            <span className="kicker block">
              {standards.length === 1 ? "Standard identified" : "Standards identified — none picked"}
            </span>
            <ul className="mt-2 space-y-4">
              {standards.map((n) => (
                <StandardEvidence key={n} number={n} product={res.context!.product} turn={turn} />
              ))}
            </ul>
            <div className="mt-4">
            <ArrowLink
              to={
                standards.length === 1
                  ? `/laboratories?standard=${encodeURIComponent(standards[0])}`
                  : `/laboratories?q=${encodeURIComponent(res.context!.product)}`
              }
            >
              {standards.length === 1
                ? `Testing laboratories for ${standards[0]}`
                : `Testing laboratories for ${res.context!.product}`}
            </ArrowLink>
            </div>
          </div>
        )}

        <ClauseList title="Clause text of the retrieved standards" clauses={res.clauses ?? []} />
      </div>

      {res.sources.length > 0 && (
        <div className="border-t border-line">
          <div className="flex items-center justify-between border-b border-line px-5 py-2.5">
            <Mono muted className="text-[10px] uppercase tracking-[0.18em]">
              Sources
            </Mono>
            <Mono muted className="text-[11px]">
              {res.sources.length} verified {res.sources.length === 1 ? "record" : "records"}
            </Mono>
          </div>
          <ul>
            {res.sources.map((s, i) => (
              <li key={s.id} className={i > 0 ? "border-t border-line" : ""}>
                <SourceRow source={s} index={i + 1} />
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="border-t border-line px-5 py-2.5 text-[10px] text-ink-faint">
        <Mono muted className="text-[10px]">
          Path: {res.fallback_reason}
        </Mono>
      </p>
    </div>
  );
}

function StandardEvidence({ number, product, turn }: { number: string; product: string; turn: Turn }) {
  const why = turn.why;
  const result = why?.results.find((r) => r.standard_number === number);
  return (
    <li className="border-l-2 border-line-strong pl-3">
      <Link to={passportByNumber(number)} className="hover:underline">
        <Mono className="text-[13px] font-medium">{number}</Mono>
      </Link>
      <Link
        to={passportByNumber(number)}
        className="ml-3 text-[12px] font-medium text-accent hover:text-accent-hover"
      >
        Standard passport
      </Link>
      {result && <div className="mt-0.5 text-[12px] text-ink-soft">{result.title}</div>}
      {why?.state === "loading" && (
        <p className="mt-1.5 text-[11px] text-ink-faint">Loading why this result…</p>
      )}
      {why?.state === "error" && (
        <p className="mt-1.5 text-[11px] text-ink-faint">Why this result could not be loaded.</p>
      )}
      {why?.state === "done" && !result && (
        <p className="mt-1.5 text-[11px] text-ink-faint">
          Product → Standard for “{product}” did not return this standard on its own, so no separate
          explanation is shown.
        </p>
      )}
      {result && (
        <div className="mt-2 space-y-3">
          <div>
            <span className="kicker block">Why this result · Product → Standard for “{product}”</span>
            <p className="mt-1 text-[12px] leading-relaxed text-ink-soft">{result.why.summary}</p>
          </div>
          <QcoStatus qco={result.qco} />
          <ListingOrders listing={result.listing_orders} />
        </div>
      )}
    </li>
  );
}
