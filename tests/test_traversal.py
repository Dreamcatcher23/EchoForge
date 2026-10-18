"""EchoForge — Unit tests for db.traversal (graph traversal engine).

Structural tests pass without a live DB — they verify return types and dict
shapes using mock or stub graph objects.  Tests that issue real Cypher queries
are skipped when FalkorDB is unavailable.

Run with::

    pytest tests/test_traversal.py -v
"""

from __future__ import annotations

import pytest

from db.traversal import (
    get_affected_entities,
    get_dependency_path,
    get_impact_summary,
    compare_traversals,
    get_evidence_chain,
    _safe_depth,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_graph():
    """Return a live FalkorDB graph or skip the test."""
    try:
        from db.connection import get_graph
        graph = get_graph()
        graph.query("RETURN 1 AS ping")
        return graph
    except Exception as exc:
        pytest.skip(f"FalkorDB not available: {exc}")


class _EmptyResult:
    """Stub FalkorDB result that returns no rows."""
    result_set: list = []
    header: list = []


class _EmptyGraph:
    """Stub graph whose queries always return empty results."""
    def query(self, cypher, params=None):
        return _EmptyResult()


# ---------------------------------------------------------------------------
# _safe_depth helper
# ---------------------------------------------------------------------------

class TestSafeDepth:
    def test_clamps_below_1(self):
        assert _safe_depth(0) == 1

    def test_clamps_above_10(self):
        assert _safe_depth(99) == 10

    def test_accepts_valid_value(self):
        assert _safe_depth(5) == 5

    def test_rejects_non_int(self):
        with pytest.raises(TypeError):
            _safe_depth("five")


# ---------------------------------------------------------------------------
# get_affected_entities — structural tests (no live DB)
# ---------------------------------------------------------------------------

class TestGetAffectedEntitiesStructure:
    """Tests that verify the return type without a real DB."""

    def test_returns_list(self):
        """get_affected_entities returns a list."""
        graph = _EmptyGraph()
        result = get_affected_entities(graph, "DEC-FAKE-001")
        assert isinstance(result, list)

    def test_empty_when_no_matches(self):
        """Returns empty list when no AFFECTS relationships exist."""
        graph = _EmptyGraph()
        result = get_affected_entities(graph, "DEC-NONEXISTENT")
        assert result == []

    def test_max_depth_clamping(self):
        """Extreme max_depth values don't raise errors."""
        graph = _EmptyGraph()
        # 0 should clamp to 1, 999 should clamp to 10
        assert get_affected_entities(graph, "X", max_depth=0) == []
        assert get_affected_entities(graph, "X", max_depth=999) == []


# ---------------------------------------------------------------------------
# get_impact_summary — structural tests
# ---------------------------------------------------------------------------

class TestImpactSummaryStructure:
    """Verify the required keys exist in the summary dict."""

    REQUIRED_KEYS = {
        "decision_id",
        "directly_affected_projects",
        "directly_affected_people",
        "total_affected_count",
        "max_depth_reached",
        "dependency_chain",
    }

    def test_has_required_keys(self):
        """Impact summary dict contains all required keys."""
        graph = _EmptyGraph()
        summary = get_impact_summary(graph, "DEC-FAKE-001")
        assert self.REQUIRED_KEYS <= summary.keys(), (
            f"Missing keys: {self.REQUIRED_KEYS - summary.keys()}"
        )

    def test_decision_id_in_summary(self):
        """Summary reflects the requested decision_id."""
        graph = _EmptyGraph()
        summary = get_impact_summary(graph, "DEC-CHECK-001")
        assert summary["decision_id"] == "DEC-CHECK-001"

    def test_empty_db_gives_zero_counts(self):
        """Empty DB gives zeroed counters."""
        graph = _EmptyGraph()
        summary = get_impact_summary(graph, "DEC-FAKE")
        assert summary["total_affected_count"] == 0
        assert summary["max_depth_reached"] == 0
        assert summary["directly_affected_projects"] == []
        assert summary["directly_affected_people"] == []
        assert summary["dependency_chain"] == []

    def test_lists_are_list_type(self):
        """All list fields actually are lists."""
        graph = _EmptyGraph()
        summary = get_impact_summary(graph, "DEC-FAKE")
        list_fields = [
            "directly_affected_projects",
            "directly_affected_people",
            "dependency_chain",
        ]
        for field in list_fields:
            assert isinstance(summary[field], list), (
                f"Expected list for '{field}', got {type(summary[field])}"
            )


# ---------------------------------------------------------------------------
# compare_traversals — structural tests
# ---------------------------------------------------------------------------

class TestCompareTraversalsStructure:
    """Verify the comparison dict has the required five keys."""

    REQUIRED_KEYS = {
        "actual_affected",
        "hypothetical_affected",
        "added_impacts",
        "removed_impacts",
        "common_impacts",
    }

    def test_has_required_keys(self):
        """Comparison dict has all five required keys."""
        graph = _EmptyGraph()
        result = compare_traversals(graph, "DEC-FAKE-001", "BRANCH-FAKE")
        assert self.REQUIRED_KEYS <= result.keys(), (
            f"Missing keys: {self.REQUIRED_KEYS - result.keys()}"
        )

    def test_all_values_are_lists(self):
        """All values in the comparison result are lists."""
        graph = _EmptyGraph()
        result = compare_traversals(graph, "DEC-FAKE-001", "BRANCH-FAKE")
        for key in self.REQUIRED_KEYS:
            assert isinstance(result[key], list), (
                f"Expected list for '{key}', got {type(result[key])}"
            )

    def test_empty_db_gives_empty_lists(self):
        """All lists are empty when the graph has no data."""
        graph = _EmptyGraph()
        result = compare_traversals(graph, "DEC-FAKE", "BRANCH-FAKE")
        for key in self.REQUIRED_KEYS:
            assert result[key] == [], f"Expected [] for '{key}'"


# ---------------------------------------------------------------------------
# get_dependency_path — structural tests
# ---------------------------------------------------------------------------

class TestDependencyPathStructure:
    """Verify path result type without a live DB."""

    def test_returns_list(self):
        """get_dependency_path returns a list."""
        graph = _EmptyGraph()
        result = get_dependency_path(graph, "A", "B")
        assert isinstance(result, list)

    def test_empty_when_no_path(self):
        """Returns [] when no path exists (empty DB)."""
        graph = _EmptyGraph()
        result = get_dependency_path(graph, "NODE-A", "NODE-B")
        assert result == []


# ---------------------------------------------------------------------------
# get_evidence_chain — structural tests
# ---------------------------------------------------------------------------

class TestEvidenceChainStructure:
    def test_returns_list(self):
        graph = _EmptyGraph()
        result = get_evidence_chain(graph, "DEC-FAKE")
        assert isinstance(result, list)

    def test_empty_when_no_evidence(self):
        graph = _EmptyGraph()
        result = get_evidence_chain(graph, "DEC-FAKE")
        assert result == []


# ---------------------------------------------------------------------------
# Live DB integration tests — skipped without FalkorDB
# ---------------------------------------------------------------------------

class TestLiveTraversal:
    """Integration tests requiring a running FalkorDB."""

    def test_get_affected_entities_live(self):
        """Live: get_affected_entities returns a list of dicts."""
        graph = _get_graph()
        from db.queries import get_all_decisions
        decisions = get_all_decisions(graph)
        if not decisions:
            pytest.skip("No decisions in DB.")
        decision_id = decisions[0]["id"]
        result = get_affected_entities(graph, decision_id)
        assert isinstance(result, list)
        # If any entities, check required keys
        for entity in result:
            assert "id" in entity
            assert "label" in entity
            assert "depth" in entity

    def test_impact_summary_live(self):
        """Live: impact summary has correct structure and types."""
        graph = _get_graph()
        from db.queries import get_all_decisions
        decisions = get_all_decisions(graph)
        if not decisions:
            pytest.skip("No decisions in DB.")
        decision_id = decisions[0]["id"]
        summary = get_impact_summary(graph, decision_id)
        required = {
            "decision_id",
            "directly_affected_projects",
            "directly_affected_people",
            "total_affected_count",
            "max_depth_reached",
            "dependency_chain",
        }
        assert required <= summary.keys()
        assert isinstance(summary["total_affected_count"], int)
        assert isinstance(summary["dependency_chain"], list)

    def test_compare_traversals_live(self):
        """Live: compare_traversals returns all five keys as lists."""
        graph = _get_graph()
        from db.history import get_actual_decisions
        from db.branch_service import create_branch

        decisions = get_actual_decisions(graph)
        if not decisions:
            pytest.skip("No actual decisions in DB.")
        source_id = decisions[0]["id"]

        branch_detail = create_branch(
            graph,
            source_decision_id=source_id,
            branch_name="Traversal compare test",
            description="Testing compare_traversals live",
            changed_assumptions=[
                {"field": "timeline", "original_value": "Q1", "new_value": "Q3"}
            ],
        )
        branch_id = branch_detail["branch"]["id"]

        result = compare_traversals(graph, source_id, branch_id)
        for key in ("actual_affected", "hypothetical_affected",
                    "added_impacts", "removed_impacts", "common_impacts"):
            assert isinstance(result[key], list), f"'{key}' must be a list"

    def test_evidence_chain_live(self):
        """Live: get_evidence_chain returns a list."""
        graph = _get_graph()
        from db.history import get_actual_decisions
        decisions = get_actual_decisions(graph)
        if not decisions:
            pytest.skip("No decisions in DB.")
        decision_id = decisions[0]["id"]
        chain = get_evidence_chain(graph, decision_id)
        assert isinstance(chain, list)
        for evidence in chain:
            assert "id" in evidence
            assert "via" in evidence
