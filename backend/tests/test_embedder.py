"""
Regression tests for app/ingestion/embed_index.py.

These are hermetic (no real model download, no network) -- they use a
recording stub in place of BGEM3FlagModel so they run in milliseconds and
still catch the specific regression the architecture doc warns about
(docs/RAG_IMPLEMENTATION.md section 4.1): BGE-M3 is symmetric and needs NO
instruction prefix, unlike bge-*-en-v1.5 ("Represent this sentence for
searching relevant passages:") or E5 ("query: "/"passage: "). Copy-pasting
an example from one of those other model families into this codebase is the
most likely way this regresses, since all three are extremely common in
RAG tutorials.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.embed_index import embed_chunks  # noqa: E402

BANNED_PREFIXES = (
    "represent this sentence",
    "represent this query",
    "query:",
    "passage:",
    "search_query:",
    "search_document:",
)


class _RecordingModel:
    """Stands in for BGEM3FlagModel: records exactly what text it was asked
    to encode, and returns well-formed but meaningless vectors."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def encode(self, sentences, **kwargs):
        self.calls.append(list(sentences))
        n = len(sentences)
        return {
            "dense_vecs": [[0.0, 0.0, 0.0, 0.0] for _ in range(n)],
            "lexical_weights": [{} for _ in range(n)],
            "colbert_vecs": None,
        }


def test_embed_chunks_passes_text_through_unmodified():
    model = _RecordingModel()
    texts = [
        "Capital Subsidy for a MICRO enterprise: 30% of Fixed Capital Investment...",
        "सूक्ष्म उद्यम को कितनी पूंजी सब्सिडी मिलेगी?",
    ]
    embed_chunks(model, texts)

    assert len(model.calls) == 1, "expected exactly one encode() call"
    sent = model.calls[0]
    assert sent == texts, (
        "embed_chunks must pass chunk text to BGE-M3 unmodified -- BGE-M3 is "
        "symmetric and needs no instruction prefix. Got a mismatch, which "
        "means something in the call path is mutating the input text."
    )


def test_embed_chunks_never_adds_a_known_instruction_prefix():
    model = _RecordingModel()
    texts = ["What capital subsidy does a micro enterprise get?", "Roof Top Solar Subsidy details"]
    embed_chunks(model, texts)

    for sent in model.calls[0]:
        lowered = sent.lower()
        for banned in BANNED_PREFIXES:
            assert not lowered.startswith(banned), (
                f"chunk text starts with {banned!r} -- this looks like an "
                "instruction prefix from bge-*-en-v1.5 or E5 was accidentally "
                "applied to a BGE-M3 call. BGE-M3 does not use prefixes."
            )


def test_load_model_does_not_request_fp16():
    """
    This machine has no discrete GPU (AMD integrated graphics, no CUDA --
    verified during planning). use_fp16=True on CPU either has no effect or
    silently degrades precision depending on torch build; the architecture
    explicitly calls for use_fp16=False on CPU. This test inspects the call
    embed_index.load_model() makes to BGEM3FlagModel without importing torch
    or downloading the real model.
    """
    import unittest.mock as mock

    captured = {}

    class _StubModel:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

    fake_module = mock.MagicMock()
    fake_module.BGEM3FlagModel = _StubModel

    with mock.patch.dict(sys.modules, {"FlagEmbedding": fake_module}):
        from app.ingestion.embed_index import load_model

        load_model()

    assert captured.get("use_fp16") is False, (
        f"expected use_fp16=False on this CPU-only machine, got {captured.get('use_fp16')!r}"
    )
