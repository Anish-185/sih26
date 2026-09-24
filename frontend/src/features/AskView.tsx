import { PageHeader, SectionHeading } from "@/components/ui";
import { HeaderMotif } from "@/components/decor";
import { AskPanel } from "@/components/AskPanel";

const EXAMPLES = [
  "What is the ISI mark and which products must carry it?",
  "How does BIS product certification work?",
  "What is the Compulsory Registration Scheme?",
  "Who can apply for a BIS licence?",
  "Where does BIS publish its certification fees?",
];

/**
 * BIS Q&A — the first of the problem statement's five features. The question
 * reaches the same deterministic retrieval every other surface uses; the model
 * only puts the retrieved records into plain language, and MetrIQ shows every
 * record it used.
 */
export function AskView() {
  return (
    <div className="space-y-12">
      <div className="relative">
        <HeaderMotif name="lotus" label="BIS · Q&A" width="w-[24%]" />
        <PageHeader
          eyebrow="Ask BIS"
          title="Ask about Indian Standards & BIS services"
          lead="Ask in plain English, Hindi or Telugu. MetrIQ retrieves verified BIS records, answers from those records alone, and shows you every one it used — including when the evidence is not enough to answer."
        />
      </div>

      <SectionHeading kicker="Grounded Q&A" title="Your question, answered from verified BIS records" />

      <AskPanel
        examples={EXAMPLES}
        placeholder="Ask about Indian Standards, certification, testing, hallmarking or BIS services…"
        emptyHint="The answer and every BIS source used will appear here. Sources come from official bis.gov.in pages — nothing else is consulted."
      />
    </div>
  );
}
