// Typed client for POST /api/chat. Mirrors backend/app/api/chat.py's
// ChatRequest/ChatResponse pydantic models exactly -- keep the two in sync
// by hand (no shared schema generation set up yet).

export type Tier = "cache" | "abstain" | "extractive" | "synthesis";

export interface Source {
  tag: string;
  clause_path: string;
  page_start: number;
  page_end: number;
  text: string;
}

export interface ChatResponse {
  answer: string;
  tier: Tier;
  language: string;
  sources: Source[];
  low_confidence: boolean;
  ambiguity_ids: string[];
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export class ChatApiError extends Error {
  status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "ChatApiError";
    this.status = status;
  }
}

export async function sendMessage(
  message: string,
  conversationId?: string,
): Promise<ChatResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, conversation_id: conversationId ?? null }),
    });
  } catch {
    throw new ChatApiError(
      "Could not reach the assistant backend. Is the API server running on " + API_BASE + "?",
    );
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // response wasn't JSON -- keep statusText
    }
    throw new ChatApiError(`Request failed (${res.status}): ${detail}`, res.status);
  }

  return (await res.json()) as ChatResponse;
}
