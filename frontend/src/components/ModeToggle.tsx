import type { ArchMode } from "../api/chat";

// The comparison the user asked for, made clickable: the same question can
// be answered by three genuinely different code paths on the backend --
// see evidence.py -- not just a relabeled UI state. Modelled on the
// existing .lang-toggle markup (App.tsx) so it reads as part of the same
// control family, not a bolted-on feature.
const MODES: { value: ArchMode; label: string; title: { en: string; hi: string } }[] = [
  {
    value: "rag",
    label: "RAG only",
    title: {
      en: "Answers using only retrieved document text, like a typical search-and-summarise chatbot. No structured fact-checking.",
      hi: "केवल दस्तावेज़ से खोजे गए पाठ के आधार पर उत्तर देता है, एक सामान्य सर्च-चैटबॉट की तरह। कोई संरचित तथ्य-जांच नहीं।",
    },
  },
  {
    value: "okf",
    label: "OKF only",
    title: {
      en: "Answers using only the structured, verified fact store (Google Open Knowledge Format) and the links between its facts. No document search.",
      hi: "केवल संरचित, सत्यापित तथ्य भंडार (Google Open Knowledge Format) और उसके तथ्यों के बीच संबंधों का उपयोग करके उत्तर देता है। कोई दस्तावेज़ खोज नहीं।",
    },
  },
  {
    value: "okf_rag",
    label: "OKF + RAG",
    title: {
      en: "The full system: structured facts for exact figures, document search for context and nuance, cross-checked against each other. Default.",
      hi: "पूरी प्रणाली: सटीक आंकड़ों के लिए संरचित तथ्य, संदर्भ के लिए दस्तावेज़ खोज, और दोनों की परस्पर जांच। डिफ़ॉल्ट।",
    },
  },
];

export function ModeToggle({
  mode,
  onChange,
  language,
}: {
  mode: ArchMode;
  onChange: (mode: ArchMode) => void;
  language: "en" | "hi";
}) {
  return (
    <div className="mode-toggle" role="group" aria-label="Architecture">
      {MODES.map((m) => (
        <button
          key={m.value}
          type="button"
          className={"mode-toggle__btn" + (mode === m.value ? " mode-toggle__btn--active" : "")}
          onClick={() => onChange(m.value)}
          title={m.title[language]}
          aria-pressed={mode === m.value}
        >
          {m.label}
        </button>
      ))}
    </div>
  );
}
