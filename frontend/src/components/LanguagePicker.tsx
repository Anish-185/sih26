import type { LanguageChoice } from "@/lib/api";
import { cn } from "@/lib/cn";

/**
 * Milestone 17 — the assistant's answer language.
 *
 * It changes the language of the ANSWER only. Retrieval, the verified evidence,
 * standard numbers and source URLs are identical in every language, so this is
 * a small inline control, not a mode switch.
 */
const OPTIONS: { value: LanguageChoice; label: string; title: string }[] = [
  { value: "auto", label: "Auto", title: "Detect the language from your question" },
  { value: "en", label: "English", title: "Answer in English" },
  { value: "hi", label: "हिन्दी", title: "Answer in Hindi" },
  { value: "te", label: "తెలుగు", title: "Answer in Telugu" },
];

export function LanguagePicker({
  value,
  onChange,
  className,
}: {
  value: LanguageChoice;
  onChange: (value: LanguageChoice) => void;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      <span className="kicker mr-1">Answer in</span>
      <div className="flex items-center border border-line-strong" role="group" aria-label="Answer language">
        {OPTIONS.map((option) => {
          const active = option.value === value;
          return (
            <button
              key={option.value}
              type="button"
              title={option.title}
              aria-pressed={active}
              onClick={() => onChange(option.value)}
              className={cn(
                "px-2.5 py-1 text-[12px] transition-colors",
                "border-r border-line-strong last:border-r-0",
                active
                  ? "bg-ink text-paper"
                  : "bg-transparent text-ink-soft hover:bg-surface hover:text-ink",
              )}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
