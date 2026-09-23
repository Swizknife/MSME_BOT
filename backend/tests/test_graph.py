"""OKF concept-graph traversal.

These tests care most about the two ways a graph retriever fails silently:
returning far too much (a hub swamping the evidence set, so every answer
cites the whole policy) and returning nothing while appearing to work.
"""

from __future__ import annotations

import pytest

from app.okf import graph


@pytest.fixture(scope="module")
def g():
    assert graph.is_available(), (
        "graph.json missing -- run `python -m app.okf.compile` first"
    )
    return graph._graph()


def test_graph_loads_with_nodes_and_edges(g):
    assert len(g.nodes) > 200
    assert sum(len(v) for v in g.out_edges.values()) > 200


def test_missing_graph_degrades_to_empty_and_never_raises(monkeypatch, tmp_path):
    """Same doctrine as store.py: no graph means fall back to RAG, not a 500."""
    monkeypatch.setattr(graph, "GRAPH_JSON", tmp_path / "nope.json")
    graph._graph.cache_clear()
    try:
        assert graph._graph().nodes == {}
        assert graph.is_available() is False
        assert graph.walk("anything").nodes == []
    finally:
        graph._graph.cache_clear()


def test_entry_points_resolve_by_alias(g):
    points = graph.resolve_entry_points("what is the capital subsidy for a micro unit")
    assert any("CAPITAL" in p.upper() or "ITEM1" in p.upper() for p in points), points


def test_entry_points_ignore_stopword_only_aliases(g):
    """A query of pure filler must not match every scheme in the bundle."""
    assert graph.resolve_entry_points("the and for with") == []


def test_seed_entity_ids_add_entry_points_the_query_never_named(g):
    """This is what makes hybrid mode more than the union of the pure modes.

    Vector retrieval finds a chunk whose concept the query's own wording
    does not name; the graph then walks outward from it.
    """
    seeded = graph.resolve_entry_points(
        "how much do I get", seed_entity_ids=["BIHAR_MSME_2026-S7.9-ITEM1"]
    )
    assert "incentives/BIHAR_MSME_2026-S7.9-ITEM1" in seeded


def test_unknown_seed_ids_are_ignored_not_fatal(g):
    assert graph.resolve_entry_points("x", seed_entity_ids=["NO-SUCH-ENTITY"]) == []


def test_hub_suppression_stops_a_scheme_swamping_the_evidence(g):
    """A Scheme is pointed at by 150+ concepts. Entering one must not return them all."""
    evidence = graph.traverse(["schemes/BIHAR_MSME_2026"])
    assert len(evidence.nodes) <= graph._config()["max_nodes"]
    # And it must not be dominated by membership lists.
    sectors = [n for n in evidence.nodes if n.type == "Sector"]
    assert len(sectors) < 10, f"hub expanded into {len(sectors)} sectors"


def test_traversal_respects_the_node_ceiling(g):
    evidence = graph.traverse(["schemes/BIHAR_MSME_2026"], max_nodes=5)
    assert len(evidence.nodes) <= 5


def test_hop_limit_is_respected(g):
    evidence = graph.traverse(["sectors/FOOD-PROCESSING-HIGH_PRIORITY"], max_hops=1)
    assert evidence.nodes
    assert max(n.hop for n in evidence.nodes) <= 1


def test_entry_points_are_hop_zero_and_score_one(g):
    evidence = graph.traverse(["districts/ARARIA"])
    entry = [n for n in evidence.nodes if n.concept_id == "districts/ARARIA"]
    assert entry and entry[0].hop == 0 and entry[0].score == pytest.approx(1.0)
    assert entry[0].via is None


def test_araria_gap_is_reported_as_missing_not_as_an_error(g):
    """"The policy never classified Araria" is the answer, not a failure.

    Araria is the one district of 38 with no classification, so it has no
    edges at all. A traversal reaching it must still carry the compile-time
    completeness finding that explains why, or the bot has nothing to say.
    """
    evidence = graph.traverse(["districts/ARARIA"])
    assert evidence.missing, "Araria's completeness finding did not surface"
    assert any("Araria" in m for m in evidence.missing)
    assert any("COMPLETENESS" in f for f in evidence.finding_ids)


def test_a_classified_district_reports_no_gap(g):
    """The control for the test above: the gap must be specific to Araria."""
    evidence = graph.traverse(["districts/PATNA"])
    assert not evidence.missing, evidence.missing


def test_multi_hop_assembly_reaches_a_rate_from_district_and_sector(g):
    """The motivating query: no single chunk contains this path."""
    evidence = graph.walk(
        "is a micro food processing unit in Araria eligible and for how much"
    )
    assert len(evidence.entry_points) >= 2
    titles = {n.title for n in evidence.nodes}
    assert "Araria" in titles
    assert "Food Processing" in titles
    assert any(n.type == "Incentive" for n in evidence.nodes), (
        "traversal never reached an Incentive, so the answer can carry no rate"
    )
    assert evidence.chunk_ids, "no citable chunks -- the evidence cannot be quoted"


def test_traversed_nodes_carry_citable_chunks(g):
    evidence = graph.traverse(["incentives/BIHAR_MSME_2026-S7.9-ITEM1"])
    assert evidence.chunk_ids
    assert all(isinstance(c, str) and c for c in evidence.chunk_ids)


def test_ambiguity_flags_reached_are_collected_for_disclosure(g):
    """Reaching a flagged concept must surface the flag, or disclosure dies."""
    evidence = graph.traverse(["incentives/BIHAR_MSME_2026-S7.9-ITEM1"])
    assert evidence.ambiguity_ids, "no ambiguity ids collected from a flagged incentive"
    assert all(a.startswith("BIHAR_MSME_2026-AMB") for a in evidence.ambiguity_ids)


def test_empty_entry_points_yield_empty_evidence(g):
    evidence = graph.traverse([])
    assert not evidence
    assert evidence.nodes == [] and evidence.chunk_ids == []
