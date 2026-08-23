"""
Shared Qdrant connection helper.

Local mode (on-disk, in-process, no server) is used throughout this project
-- see app/ingestion/embed_index.py's module docstring for why: Docker
Desktop was not running when this was built, and at this corpus size
(~85-400 vectors) local mode is strictly simpler and equally correct.

To move to a real Qdrant server later (e.g. alongside the DGX Spark
deployment), change QDRANT_MODE to "server" and set QDRANT_URL -- nothing
else in the retrieval pipeline needs to change, since both modes expose the
identical qdrant_client.QdrantClient API.

IMPORTANT operational constraint of local mode: the on-disk collection is
file-locked by whichever process opens it first. Only one process (the
ingestion script OR the API server, never both at once) may hold it open at
a time -- run `python -m app.ingestion.embed_index` to completion and let it
exit before starting the FastAPI server.
"""

from __future__ import annotations

import os
from pathlib import Path

from qdrant_client import QdrantClient

REPO_ROOT = Path(__file__).resolve().parents[3]
QDRANT_LOCAL_PATH = REPO_ROOT / "data" / "qdrant_local"

QDRANT_MODE = os.environ.get("QDRANT_MODE", "local")  # "local" | "server"
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")

COLLECTION_NAME = "msme_policy"
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"

_client: QdrantClient | None = None


def get_client() -> QdrantClient:
    global _client
    if _client is not None:
        return _client
    if QDRANT_MODE == "server":
        _client = QdrantClient(url=QDRANT_URL)
    else:
        _client = QdrantClient(path=str(QDRANT_LOCAL_PATH))
    return _client
