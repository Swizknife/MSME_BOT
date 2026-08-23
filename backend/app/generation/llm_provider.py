"""
LLM provider abstraction (D6/D9): generation is the one stage that stays
behind a swappable interface, because it is the one place CPU cost is
punishing on this machine (no discrete GPU -- verified during planning).
Every provider speaks the OpenAI chat-completions shape, so switching is a
config change, not a rewrite.

  - "ollama"  -> local, fully offline, correctness-testing path
                 (docs/RAG_IMPLEMENTATION.md section 5.4: realistically
                 20-60s per answer on this CPU -- usable for verification,
                 not for a live demo)
  - "hosted"  -> any OpenAI-compatible hosted endpoint, ~2-4s per answer,
                 the default "fast mode" for demos and UX validation
  - "vllm"    -> reserved for the DGX Spark deployment; identical interface,
                 just a different base_url

Policy content (chunk text) is what gets sent to whichever provider is
configured -- "hosted" therefore leaves the laptop. This is a deliberate,
disclosed trade documented in config/models.yaml, not a silent default;
the RAG stack itself (embedding, retrieval, reranking) always stays local
per D8 regardless of which generation provider is active.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterator

PROVIDER = os.environ.get("LLM_PROVIDER", "ollama")  # "ollama" | "hosted" | "vllm"

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
# gemma3:4b, not qwen2.5:3b-instruct -- this project doesn't pull a fresh
# model, it uses what's already installed on this machine. Benchmarked
# against the only other CPU-reasonable option actually available
# (llama3.2:1b, ~21 tok/s vs gemma3:4b's ~10 tok/s): the 1B model is faster
# but this system prompt carries 8 strict rules (citation tags, never do
# arithmetic, exact figure reproduction, bilingual output, ambiguity
# disclosure) that a 1B-class model follows unreliably -- and an unreliable
# answer means Numeric/citation guard retries, which cost more wall-clock
# than the slower model would have taken in the first place.
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma3:4b")

HOSTED_BASE_URL = os.environ.get("HOSTED_LLM_BASE_URL", "")
HOSTED_API_KEY = os.environ.get("HOSTED_LLM_API_KEY", "")
HOSTED_MODEL = os.environ.get("HOSTED_LLM_MODEL", "")

# Kept tight per architecture doc section 5.4 -- an oversized context window
# allocates KV cache and slows every token on CPU; this corpus never needs
# more than a few hundred tokens of retrieved context.
NUM_CTX = int(os.environ.get("LLM_NUM_CTX", "2048"))


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


def _client_for(provider: str):
    from openai import OpenAI

    if provider == "ollama":
        return OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama"), OLLAMA_MODEL
    if provider == "hosted":
        if not HOSTED_BASE_URL or not HOSTED_MODEL:
            raise RuntimeError(
                "LLM_PROVIDER=hosted requires HOSTED_LLM_BASE_URL and HOSTED_LLM_MODEL "
                "to be set (see config/.env.example)."
            )
        return OpenAI(base_url=HOSTED_BASE_URL, api_key=HOSTED_API_KEY or "unused"), HOSTED_MODEL
    raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}")


def chat_completion(messages: list[ChatMessage], stream: bool = False, temperature: float = 0.1):
    """
    Returns the full response text if stream=False, or an iterator of text
    deltas if stream=True. temperature is kept low (0.1) since this bot's
    job is to paraphrase retrieved clauses faithfully, not to be creative --
    high temperature directly works against the Numeric Guard's job.
    """
    client, model = _client_for(PROVIDER)
    api_messages = [{"role": m.role, "content": m.content} for m in messages]

    if not stream:
        resp = client.chat.completions.create(
            model=model, messages=api_messages, temperature=temperature,
            extra_body={"num_ctx": NUM_CTX} if PROVIDER == "ollama" else None,
        )
        return resp.choices[0].message.content

    def _iter() -> Iterator[str]:
        resp = client.chat.completions.create(
            model=model, messages=api_messages, temperature=temperature, stream=True,
            extra_body={"num_ctx": NUM_CTX} if PROVIDER == "ollama" else None,
        )
        for chunk in resp:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    return _iter()
