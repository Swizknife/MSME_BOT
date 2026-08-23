import { useState, type KeyboardEvent } from "react";

export function ChatInput({
  onSend,
  disabled,
  language,
}: {
  onSend: (text: string) => void;
  disabled: boolean;
  language: "en" | "hi";
}) {
  const [value, setValue] = useState("");

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="chat-input">
      <textarea
        className="chat-input__field"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder={
          language === "hi"
            ? "बिहार एमएसएमई नीति 2026 के बारे में पूछें..."
            : "Ask about the Bihar MSME Policy 2026..."
        }
        rows={1}
        disabled={disabled}
      />
      <button
        type="button"
        className="chat-input__send"
        onClick={submit}
        disabled={disabled || !value.trim()}
      >
        {language === "hi" ? "भेजें" : "Send"}
      </button>
    </div>
  );
}
