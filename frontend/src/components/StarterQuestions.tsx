// Starter questions drawn from the actual incentive list (architecture doc
// section 11.1), not generic placeholders -- each maps to a real chunk in
// the corpus so a first-time user's first query always succeeds.
const STARTERS_EN = [
  "What capital subsidy does a micro enterprise get?",
  "What is the payroll subsidy for a small enterprise?",
  "Which districts are in Region A?",
  "What is the interest subsidy rate?",
];

const STARTERS_HI = [
  "सूक्ष्म उद्यम को कितनी पूंजी सब्सिडी मिलेगी?",
  "लघु उद्यम के लिए वेतन सब्सिडी क्या है?",
  "रीजन A में कौन से जिले हैं?",
  "ब्याज सब्सिडी दर क्या है?",
];

export function StarterQuestions({
  language,
  onPick,
}: {
  language: "en" | "hi";
  onPick: (text: string) => void;
}) {
  const items = language === "hi" ? STARTERS_HI : STARTERS_EN;
  return (
    <div className="starters">
      <p className="starters__label">
        {language === "hi" ? "आरंभ करने के लिए कुछ उदाहरण:" : "Try asking:"}
      </p>
      <div className="starters__chips">
        {items.map((q) => (
          <button key={q} type="button" className="starter-chip" onClick={() => onPick(q)}>
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
