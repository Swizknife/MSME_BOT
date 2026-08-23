export interface ChatTurn {
  id: string;
  role: "user" | "assistant";
  text: string;
  tier?: import("../api/chat").Tier;
  language?: string;
  sources?: import("../api/chat").Source[];
  lowConfidence?: boolean;
  ambiguityIds?: string[];
  error?: boolean;
}
