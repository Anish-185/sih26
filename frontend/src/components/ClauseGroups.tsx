import { useEffect, useState } from "react";
import { api, type AnswerLanguage, type ClauseGroups as Groups } from "@/lib/api";
import { ClauseText } from "@/components/ClauseText";
import { Callout, Mono, Spinner } from "@/components/ui";

/**
 * Phase 10 — a standard's sampling, conformity and test-method clauses, QUOTED.
 *
 * Standalone on purpose: it takes a standard number exactly as stored and fetches
 * GET /standard-clauses itself, so the Standard Passport (Phase 11) can drop it in
 * unchanged. It loads only when opened, so a page of result cards makes no requests.
 * Every sentence comes from the backend; every clause is shown through ClauseText,
 * which carries the OCR label and the stored reference. An IDENTITY_ONLY standard
 * shows MetrIQ's one honest sentence — never substitute prose.
 */
export function ClauseGroups({
  standardNumber,
  language = "en",
  className,
  defaultOpen = false,
}: {
  standardNumber: string;
  language?: AnswerLanguage;
  className?: string;
  /** Open (and loaded) on arrival — the Passport shows it expanded. */
  defaultOpen?: boolean;
}) {
  const [data, setData] = useState<Groups | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = () => {
    if (data || loading) return;
    setLoading(true);
    api
      .standardClauses(standardNumber, language)
      .then(setData)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Could not load the clauses."))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (defaultOpen) load();
    // Once, on arrival; load() itself refuses to run twice.
  }, [defaultOpen, standardNumber]);

  return (
    <details
      className={className}
      open={defaultOpen || undefined}
      onToggle={(e) => {
        if ((e.currentTarget as HTMLDetailsElement).open) load();
      }}
    >
      <summary className="kicker cursor-pointer select-none">Sampling, conformity and test methods</summary>
      <div className="mt-3 space-y-4">
        {loading && <Spinner className="h-4 w-4" />}
        {error && <Callout tone="abstain">{error}</Callout>}
        {data && data.status !== "CLAUSE_TEXT" && <Callout>{data.message}</Callout>}
        {data && data.status === "CLAUSE_TEXT" && (
          <>
            <p className="max-w-2xl text-[12px] leading-relaxed text-ink-soft">{data.message}</p>
            <p className="max-w-2xl text-[12px] leading-relaxed text-review">{data.completeness}</p>
            {data.withheld_clauses.length > 0 && (
              <p className="max-w-2xl text-[11px] leading-relaxed text-ink-faint">
                Withheld:{" "}
                {data.withheld_clauses.map((w) => `clause ${w.clause} (${w.reason})`).join(", ")}
              </p>
            )}
            {data.groups.map((group) => (
              <section key={group.group}>
                <div className="kicker mb-2">
                  {group.title} <Mono muted>({group.clauses.length})</Mono>
                </div>
                {group.clauses.length === 0 ? (
                  <p className="text-[12px] text-ink-faint">{group.empty_note}</p>
                ) : (
                  <ul className="space-y-4">
                    {group.clauses.map((g) => (
                      <li key={`${group.group}-${g.clause.id}`}>
                        <Mono muted className="mb-1 block text-[10px] uppercase tracking-[0.1em]">
                          In this group by {g.matched.join("; ")}
                        </Mono>
                        <ClauseText clause={g.clause} />
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            ))}
          </>
        )}
      </div>
    </details>
  );
}
