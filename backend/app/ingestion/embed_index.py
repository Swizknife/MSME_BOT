"""
Step 5 of the ingestion pipeline: embed chunks with BGE-M3 and load them into
Qdrant.

Per docs/RAG_IMPLEMENTATION.md section 3.4:
  - BAAI/bge-m3, torch CPU, use_fp16=False (no GPU available on this
    machine -- verified during planning: AMD integrated graphics, no CUDA).
  - Deliberately NOT exported to ONNX. BGE-M3's sparse head is a separate
    `sparse_linear` weight outside the main graph; a standard optimum export
    yields dense-only, which would silently drop the sparse vectors this
    corpus depends on for exact-numeral matching (Rs.24,000, 300 Kw,
    section 9.1(d)). At ~85 chunks the one-time CPU encode cost (~seconds,
    not minutes) makes this a non-issue.
  - NO instruction prefix is added to any text before encoding. BGE-M3 is
    symmetric -- unlike bge-*-en-v1.5 (which wants a "Represent this
    sentence..." prefix) or E5 (which wants "query: "/"passage: "), adding
    a prefix to M3 measurably degrades retrieval. See test_embedder.py for
    the regression test.

Qdrant runs in LOCAL MODE (on-disk, in-process, no Docker/server) rather
than as a separate service. This was a deliberate substitution for the
Docker-based deployment sketched during planning: Docker Desktop is not
running on this machine, and at ~85-400 vectors a local-mode client is
strictly simpler and equally correct -- the same qdrant-client API works
against a real server later by swapping `path=` for `url=` in one place
(app/retrieval/qdrant_client.py), so nothing about the retrieval code
changes when this moves to a server deployment.

Exact search (no HNSW) is configured for both the dense and sparse vector
spaces: at this corpus size (~400 vectors after Step 4 hypothetical-question
expansion; ~85 today before that step is implemented), brute-force cosine
search over the full matrix is faster AND more accurate than an approximate
index, per docs/RAG_IMPLEMENTATION.md section 2.1.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHUNKS_JSON = REPO_ROOT / "data" / "chunks" / "msme_policy_2026.chunks.json"
QDRANT_LOCAL_PATH = REPO_ROOT / "data" / "qdrant_local"

COLLECTION_NAME = "msme_policy"
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"
DENSE_DIM = 1024
EMBED_BATCH_SIZE = 16


def load_model():
    """Load BGE-M3 on CPU. Import is local so this module can be imported
    (e.g. by tests) without paying the torch/FlagEmbedding import cost."""
    from FlagEmbedding import BGEM3FlagModel

    from app.ingestion.model_cache import resolve_local_path

    print("Loading BAAI/bge-m3 (CPU, fp32) -- first run downloads ~2.3GB from Hugging Face...")
    t0 = time.time()
    local_path = resolve_local_path("BAAI/bge-m3")
    model = BGEM3FlagModel(local_path, use_fp16=False, devices="cpu")
    print(f"Model ready in {time.time() - t0:.1f}s")
    return model


def embed_chunks(model, texts: list[str]) -> tuple[list[list[float]], list[dict]]:
    """
    Returns (dense_vectors, sparse_vectors) where each sparse vector is a
    dict {token_id_str: weight} as returned by FlagEmbedding, ready to be
    converted into Qdrant's SparseVector(indices=..., values=...).
    """
    out = model.encode(
        texts,
        batch_size=EMBED_BATCH_SIZE,
        max_length=1024,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,  # deliberately off -- see architecture doc
                                     # section 3.4 on ColBERT storage cost
    )
    dense = out["dense_vecs"]
    sparse = out["lexical_weights"]  # list[dict[str, float]]
    return dense, sparse


def build_qdrant_points(chunks: list[dict], dense_vecs, sparse_vecs) -> list:
    from qdrant_client.models import PointStruct, SparseVector

    points = []
    for i, (chunk, dvec, svec) in enumerate(zip(chunks, dense_vecs, sparse_vecs)):
        indices = [int(tok_id) for tok_id in svec.keys()]
        values = [float(w) for w in svec.values()]
        payload = {k: v for k, v in chunk.items()}
        points.append(
            PointStruct(
                id=i,
                vector={
                    DENSE_VECTOR_NAME: dvec.tolist() if hasattr(dvec, "tolist") else list(dvec),
                    SPARSE_VECTOR_NAME: SparseVector(indices=indices, values=values),
                },
                payload=payload,
            )
        )
    return points


def get_client():
    from qdrant_client import QdrantClient

    QDRANT_LOCAL_PATH.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(QDRANT_LOCAL_PATH))


def create_collection(client) -> None:
    from qdrant_client.models import Distance, SparseVectorParams, VectorParams, HnswConfigDiff

    if client.collection_exists(COLLECTION_NAME):
        client.delete_collection(COLLECTION_NAME)

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={
            # m=0 disables HNSW graph construction -> exact brute-force
            # search, which is both faster and more accurate than ANN at
            # this corpus size (docs/RAG_IMPLEMENTATION.md section 2.1).
            DENSE_VECTOR_NAME: VectorParams(
                size=DENSE_DIM, distance=Distance.COSINE,
                hnsw_config=HnswConfigDiff(m=0),
            ),
        },
        sparse_vectors_config={
            SPARSE_VECTOR_NAME: SparseVectorParams(),
        },
    )


def main() -> None:
    if not CHUNKS_JSON.exists():
        print(f"FAIL: {CHUNKS_JSON} not found -- run `python -m app.ingestion.chunk` first.")
        sys.exit(1)

    data = json.loads(CHUNKS_JSON.read_text(encoding="utf-8"))
    chunks = data["chunks"]
    texts = [c["text"] for c in chunks]
    print(f"Embedding {len(texts)} chunks...")

    model = load_model()
    t0 = time.time()
    dense_vecs, sparse_vecs = embed_chunks(model, texts)
    print(f"Encoded in {time.time() - t0:.1f}s ({(time.time()-t0)/len(texts)*1000:.0f} ms/chunk)")

    client = get_client()
    create_collection(client)
    points = build_qdrant_points(chunks, dense_vecs, sparse_vecs)
    client.upsert(collection_name=COLLECTION_NAME, points=points)

    count = client.count(COLLECTION_NAME).count
    print(f"Indexed {count} points into Qdrant collection '{COLLECTION_NAME}' at {QDRANT_LOCAL_PATH}")


if __name__ == "__main__":
    main()
