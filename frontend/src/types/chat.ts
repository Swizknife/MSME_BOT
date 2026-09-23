export interface ChatTurn {
  id: string;
  role: "user" | "assistant";
  text: string;
  tier?: import("../api/chat").Tier;
  mode?: import("../api/chat").ArchMode;
  language?: string;
  sources?: import("../api/chat").Source[];
  lowConfidence?: boolean;
  ambiguityIds?: string[];
  graphPath?: import("../api/chat").GraphNodeRef[];
  graphMissing?: string[];
  timingMs?: number | null;
  error?: boolean;
}
