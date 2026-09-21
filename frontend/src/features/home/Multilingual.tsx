import { useId, useState } from "react";
import { Link } from "react-router-dom";
import { api, type AnswerLanguage, type AskResponse } from "@/lib/api";
import { useAsyncTask } from "@/lib/hooks";
import { cn } from "@/lib/cn";
import { InlineLoading, Mono } from "@/components/ui";
import { Prose } from "@/components/GroundedAnswer";

/**
 * The multilingual claim, demonstrated with the real endpoint rather than a
 * canned translation: picking a language calls POST /ask exactly as the
 * Hallmarking page does, and shows the answer that comes back.
 *
 * Nothing runs until the reader asks for it — one request per click, never on
 * page load, so simply visiting the home page costs no model quota.
 */
const QUESTION = "What is HUID?";

const LANGS: { code: AnswerLanguage; label: string; native: string }[] = [
  { code: "en", label: "English", native: "English" },
  { code: "hi", label: "Hindi", native: "हिन्दी" },
  { code: "te", label: "Telugu", native: "తెలుగు" },
];

export function Multilingual() {
  const [lang, setLang] = useState<AnswerLanguage>("en");
  const ask = useAsyncTask((code: AnswerLanguage) => api.ask(QUESTION, code));
  const answer: AskResponse | null = ask.data;
  const headingId = useId();

  const run = (code: AnswerLanguage) => {
    setLang(code);
    void ask.run(code);
  };

  return (
    <section aria-labelledby={headingId} className="grid gap-x-12 gap-y-8 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1fr)]">
      <div>
        <span className="eyebrow">Ask in your language</span>
        <h2 id={headingId} className="display mt-4 text-[1.8rem] sm:text-[2.4rem]">
          The answer changes language.{" "}
          <span className="mt-1 block text-ink-faint">The evidence does not.</span>
        </h2>
        <p className="mt-6 max-w-md text-[14px] leading-relaxed text-ink-soft">
          A question in English, Hindi or Telugu reaches the same verified records
          and returns the same standard numbers, document titles and source URLs.
          Only the prose around them changes.
        </p>
        <p className="mt-5 max-w-md text-[12px] leading-relaxed text-ink-faint">
          This runs the real endpoint. Pick a language to send the question.
        </p>
      </div>

      <div className="border border-line bg-surface">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3.5">
          <Mono muted className="text-[12px]">“{QUESTION}”</Mono>
          <div className="flex" role="group" aria-label="Answer language">
            {LANGS.map((l) => (
              <button
                key={l.code}
                type="button"
                lang={l.code}
                onClick={() => run(l.code)}
                aria-pressed={lang === l.code && answer != null}
                className={cn(
                  "border border-line-strong px-3 py-1 text-[12px] transition-colors -ml-px first:ml-0",
                  lang === l.code
                    ? "border-ink bg-ink text-paper"
                    : "text-ink-soft hover:bg-raised hover:text-ink",
                )}
              >
                {l.native}
              </button>
            ))}
          </div>
        </div>

        <div className="min-h-[220px] px-5 py-5">
          {ask.loading && <InlineLoading label="Asking MetrIQ" />}

          {!ask.loading && ask.error != null && (
            <p className="text-[13px] leading-relaxed text-review">
              The answer service did not respond. Every deterministic result on this
              site is unaffected — explanations are the only optional layer.
            </p>
          )}

          {!ask.loading && ask.error == null && answer == null && (
            <p className="text-[13px] leading-relaxed text-ink-faint">
              Choose a language above and MetrIQ will answer from its verified
              BIS records.
            </p>
          )}

          {!ask.loading && answer != null && (
            <div className="ink-in">
              {/* Reuses the renderer the grounded views use, so the light
                  markdown the model emits is handled in exactly one place. */}
              <div lang={answer.language}>
                <Prose text={answer.answer} />
              </div>
              {answer.sources.length > 0 && (
                <div className="mt-5 border-t border-line pt-4">
                  <div className="kicker mb-2">
                    Grounded in {answer.source_count} verified record
                    {answer.source_count === 1 ? "" : "s"}
                  </div>
                  <ul className="space-y-1">
                    {answer.sources.slice(0, 3).map((src) => (
                      <li key={src.id} className="truncate text-[12px] text-ink-soft">
                        {src.standard_number && (
                          <Mono className="mr-2 text-[11px] !text-accent">
                            {src.standard_number}
                          </Mono>
                        )}
                        {src.title}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-4 border-t border-line px-5 py-3">
          <span className="annotation">Same records in every language</span>
          <Link
            to="/hallmarking"
            className="font-mono text-[11px] uppercase tracking-[0.16em] text-accent hover:text-accent-hover"
          >
            Ask your own
          </Link>
        </div>
      </div>
    </section>
  );
}
