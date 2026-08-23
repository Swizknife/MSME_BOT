"""
Cross-encoder reranking with BAAI/bge-reranker-v2-m3.

Per docs/RAG_IMPLEMENTATION.md sections 4.2 and 5.1: the reranker is the
largest single quality lever in the pipeline (bi-encoders like BGE-M3 must
compress a passage into a vector before ever seeing the query; a
cross-encoder reads query and passage together and is far more accurate,
but is O(n) per candidate so it only runs on the ~12-candidate shortlist
hybrid.py produces). Its calibrated score is also what makes the Coverage
Gate (coverage_gate.py) trustworthy -- raw cosine similarity compresses into
a narrow band and is not reliably thresholdable; cross-encoder logits
separate relevant from irrelevant by a wide, stable margin.

Loaded with plain `transformers` (AutoTokenizer + AutoModelForSequenceClass-
ification) rather than FlagEmbedding's FlagReranker wrapper -- this is
actually the model card's own documented usage pattern for bge-reranker
models, and it sidesteps a real bug: FlagEmbedding 1.4.0's reranker path
calls `tokenizer.prepare_for_model`, a method the installed transformers
5.15.1 no longer exposes on the slow XLMRobertaTokenizer BGE-M3-family
models load (`AttributeError: XLMRobertaTokenizer has no attribute
prepare_for_model`, confirmed against this exact model+library combination).
Downgrading transformers to work around it was tried and rejected: it broke
BGEM3FlagModel's own working load path and, at one candidate downgrade
version, dragged in an unrelated TensorFlow/Keras-3 import failure this
environment has no need for. The embedder (embedder.py, embed_index.py)
still uses FlagEmbedding/BGEM3FlagModel directly -- that path loads and
scores correctly today; only the reranker's tokenizer call is broken.

Runs on CPU (torch inference_mode, no grad). The architecture doc calls for
an ONNX int8 export for ~3-4x CPU speedup; that is a follow-up optimization
once the pipeline is correctness-verified end to end, tracked as a TODO
rather than done blind before there is a correctness baseline to measure it
against.
"""

from __future__ import annotations

import threading

import torch

_tokenizer = None
_model = None
_lock = threading.Lock()

RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
MAX_LENGTH = 512  # architecture doc calls for a 384-token cap once ONNX'd;
                   # 512 (the model's trained default) is used for the
                   # torch-backend baseline to avoid truncation artifacts
                   # before that optimization pass.


def get_reranker():
    global _tokenizer, _model
    if _model is not None:
        return _tokenizer, _model
    with _lock:
        if _model is None:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            from app.ingestion.model_cache import resolve_local_path

            path = resolve_local_path(RERANKER_MODEL)
            _tokenizer = AutoTokenizer.from_pretrained(path)
            _model = AutoModelForSequenceClassification.from_pretrained(path)
            _model.eval()
    return _tokenizer, _model


def rerank(query: str, candidates: list) -> list[tuple[object, float]]:
    """
    candidates: list of RetrievedChunk (from hybrid.py) or anything with a
    `.payload["text"]` field. Returns [(candidate, score), ...] sorted
    descending by reranker score. Scores are sigmoid-normalized to [0,1] so
    they are directly comparable to the Coverage Gate thresholds in
    coverage_gate.py.
    """
    if not candidates:
        return []
    tokenizer, model = get_reranker()
    pairs = [(query, c.payload["text"]) for c in candidates]

    with torch.inference_mode():
        inputs = tokenizer(
            pairs, padding=True, truncation=True, max_length=MAX_LENGTH, return_tensors="pt",
        )
        logits = model(**inputs, return_dict=True).logits.view(-1).float()
        scores = torch.sigmoid(logits)

    scored = list(zip(candidates, scores.tolist()))
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored
