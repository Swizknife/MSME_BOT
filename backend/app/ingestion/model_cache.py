"""
Shared local-model resolution for BGE-M3 and the BGE reranker.

Both app/retrieval/embedder.py, app/ingestion/embed_index.py and
app/retrieval/rerank.py need this: calling `BGEM3FlagModel("BAAI/bge-m3")` or
`FlagReranker("BAAI/bge-reranker-v2-m3")` directly makes FlagEmbedding run
its OWN internal `snapshot_download`, which fetches the ENTIRE repo minus
only `{flax_model.msgpack, rust_model.ot, tf_model.h5}`. For BAAI/bge-m3
that includes `onnx/model.onnx_data` -- a ~2GB duplicate of the ONNX export
of the exact same weights we deliberately never use (see embed_index.py's
module docstring: BGE-M3's sparse head lives outside the ONNX graph, so an
ONNX export would silently drop sparse retrieval, which the exact-numeral
matching in this corpus depends on). Downloading it anyway roughly doubles
an already-slow transfer for zero benefit.

Fetching each repo ourselves first, with `ignore_patterns` that exclude the
files this project will never open, and handing FlagEmbedding the resulting
LOCAL DIRECTORY PATH rather than the repo id, sidesteps this: a local path
is loaded directly with no network call and no repo-completeness check.
`snapshot_download` is idempotent and resumable, so this is a no-op (an
on-disk cache check, no network) once everything relevant is already cached.
"""

from __future__ import annotations

_COMMON_IGNORE = ["*.md", ".gitattributes"]

_IGNORE_PATTERNS = {
    "BAAI/bge-m3": [*_COMMON_IGNORE, "onnx/*", "imgs/*", "long.jpg"],
    "BAAI/bge-reranker-v2-m3": [*_COMMON_IGNORE, "assets/*"],
}


def resolve_local_path(repo_id: str) -> str:
    """Ensure `repo_id` is cached locally (minus the ignored dead weight)
    and return the local snapshot directory to load from."""
    from huggingface_hub import snapshot_download

    return snapshot_download(
        repo_id=repo_id,
        ignore_patterns=_IGNORE_PATTERNS.get(repo_id, _COMMON_IGNORE),
    )
