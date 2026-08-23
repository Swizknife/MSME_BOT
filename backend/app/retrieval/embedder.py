"""
Query-time BGE-M3 wrapper. Loaded once as a process-wide singleton so the
~2.3GB model is not re-loaded per request.

Same "no instruction prefix" rule as ingestion time (see
app/ingestion/embed_index.py and tests/test_embedder.py) -- BGE-M3 is
symmetric, so a query is encoded exactly like a passage, no prefix.
"""

from __future__ import annotations

import threading

_model = None
_lock = threading.Lock()


def get_model():
    global _model
    if _model is not None:
        return _model
    with _lock:
        if _model is None:
            from FlagEmbedding import BGEM3FlagModel

            from app.ingestion.model_cache import resolve_local_path

            _model = BGEM3FlagModel(resolve_local_path("BAAI/bge-m3"), use_fp16=False, devices="cpu")
    return _model


def encode_query(text: str) -> tuple[list[float], dict[str, float]]:
    """Returns (dense_vector, sparse_weights) for a single query string."""
    model = get_model()
    out = model.encode(
        [text],
        max_length=512,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    dense = out["dense_vecs"][0]
    sparse = out["lexical_weights"][0]
    dense_list = dense.tolist() if hasattr(dense, "tolist") else list(dense)
    return dense_list, sparse
