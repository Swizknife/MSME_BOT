import { useRef, useState } from "react";
import "./App.css";
import type { ArchMode } from "./api/chat";
import { ChatApiError, sendMessage } from "./api/chat";
import { ChatInput } from "./components/ChatInput";
import { ChatMessage } from "./components/ChatMessage";
import { ModeToggle } from "./components/ModeToggle";
import { StarterQuestions } from "./components/StarterQuestions";
import type { ChatTurn } from "./types/chat";

let nextId = 0;
const newId = () => String(nextId++);

function App() {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [loading, setLoading] = useState(false);
  const [language, setLanguage] = useState<"en" | "hi">("en");
  // Deliberately NOT reset when mode changes, and the conversation is not
  // cleared either -- the comparison this exists for lands hardest when the
  // user asks the same question twice with the toggle flipped and both
  // answers sit adjacent in one transcript, not in two separate sessions.
  const [mode, setMode] = useState<ArchMode>("okf_rag");
  const conversationId = useRef(crypto.randomUUID());

  const handleSend = async (text: string) => {
    const userTurn: ChatTurn = { id: newId(), role: "user", text };
    setTurns((prev) => [...prev, userTurn]);
    setLoading(true);

    try {
      const res = await sendMessage(text, conversationId.current, mode);
      setTurns((prev) => [
        ...prev,
        {
          id: newId(),
          role: "assistant",
          text: res.answer,
          tier: res.tier,
          mode: res.mode,
          language: res.language,
          sources: res.sources,
          lowConfidence: res.low_confidence,
          ambiguityIds: res.ambiguity_ids,
          graphPath: res.graph_path,
          graphMissing: res.graph_missing,
          timingMs: res.timing_ms,
        },
      ]);
      if (res.language === "hi" || res.language === "en") {
        setLanguage(res.language as "en" | "hi");
      }
    } catch (err) {
      const message =
        err instanceof ChatApiError
          ? err.message
          : "Something went wrong reaching the assistant. Please try again.";
      setTurns((prev) => [
        ...prev,
        { id: newId(), role: "assistant", text: message, error: true },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-header__title">
          <h1>Bihar MSME Policy 2026 — Assistant</h1>
          <p className="app-header__subtitle">
            {language === "hi"
              ? "बिहार एमएसएमई नीति 2026 के बारे में सवाल पूछें"
              : "Ask questions about the Bihar MSME Policy 2026"}
          </p>
        </div>
        <div className="app-header__controls">
          <ModeToggle mode={mode} onChange={setMode} language={language} />
          <div className="lang-toggle" role="group" aria-label="Language">
            <button
              type="button"
              className={"lang-toggle__btn" + (language === "en" ? " lang-toggle__btn--active" : "")}
              onClick={() => setLanguage("en")}
            >
              EN
            </button>
            <button
              type="button"
              className={"lang-toggle__btn" + (language === "hi" ? " lang-toggle__btn--active" : "")}
              onClick={() => setLanguage("hi")}
            >
              हिं
            </button>
          </div>
        </div>
      </header>

      <div className="draft-banner">
        {language === "hi"
          ? "यह नीति अभी प्रारूप (draft) है और सरकार द्वारा अभी अधिसूचित नहीं हुई है। यह सहायक केवल इस दस्तावेज़ से उत्तर देता है और राशियों की गणना नहीं करता — केवल दर और सीमा बताता है।"
          : "This policy is still a DRAFT and has not been notified by the Government of Bihar. This assistant answers only from this document and does not compute amounts — it quotes rates and caps as written."}
      </div>

      <main className="chat-area">
        {turns.length === 0 ? (
          <StarterQuestions language={language} onPick={handleSend} />
        ) : (
          <div className="message-list">
            {turns.map((t) => (
              <ChatMessage key={t.id} turn={t} />
            ))}
            {loading && (
              <div className="message message--assistant">
                <div className="message__bubble message__bubble--loading">
                  {language === "hi" ? "सोच रहा हूँ…" : "Thinking…"}
                </div>
              </div>
            )}
          </div>
        )}
      </main>

      <footer className="app-footer">
        <ChatInput onSend={handleSend} disabled={loading} language={language} />
      </footer>
    </div>
  );
}

export default App;
