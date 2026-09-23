"""OKF (Open Knowledge Framework) package.

This package will eventually hold:
  - schemas.py   Pydantic models for every OKF entity type (this file exists now)
  - compiler.py  parses data/okf_vault/*.md, validates against schemas.py,
                 cross-checks facts against staged raw sources, and emits
                 data/okf_compiled/<entity_type>/<id>.json plus RAG chunks
                 fed into backend/app/ingestion/chunk.py  (Phase 1 -- not built yet)
  - store.py     read accessor for compiled OKF records, used by the query-time
                 router (backend/app/policy/intents.py) and the guards in
                 backend/app/generation/guards.py  (Phase 1 -- not built yet)

See docs/OKF_RAG_IMPLEMENTATION.md for the architecture and HANDOFF.md for
current build-phase status.
"""
