"""EchoForge — Unit tests for db.history (immutability layer).

Tests in this module do not require a live FalkorDB instance for the first
three cases.  Tests that need a real graph connection are skipped gracefully
when FalkorDB is unavailable.

Run with::

    pytest tests/test_history.py -v
"""

from __future__ import annotations

import pytest

from db.history import (
    HistoryViolationError,
    assert_not_actual,
    record_actual_outcome,
    link_outcome_to_decision,
    get_actual_decisions,
    get_actual_outcomes,
    get_actual_evidence,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_graph():
    """Return a live FalkorDB graph or skip the test."""
    try:
        from db.connection import get_graph
        graph = get_graph()
        # Verify connection with a trivial query
        graph.query("RETURN 1 AS ping")
        return graph
    except Exception as exc:
        pytest.skip(f"FalkorDB not available: {exc}")


# ---------------------------------------------------------------------------
# assert_not_actual
# ---------------------------------------------------------------------------

class TestAssertNotActual:
    """Tests for the immutability guard function."""

    def test_raises_for_actual_node(self):
        """HistoryViolationError is raised when is_actual=True."""
        actual_node = {"id": "DEC-001", "title": "Launch Alpha", "is_actual": True}
        with pytest.raises(HistoryViolationError) as exc_info:
            assert_not_actual(actual_node, operation="delete")
        assert "DEC-001" in str(exc_info.value)
        assert "delete" in str(exc_info.value)

    def test_raises_default_operation_label(self):
        """Default operation label 'modify' appears in the error message."""
        node = {"id": "DEC-002", "is_actual": True}
        with pytest.raises(HistoryViolationError) as exc_info:
            assert_not_actual(node)
        assert "modify" in str(exc_info.value)

    def test_passes_for_hypothetical_node(self):
        """No exception when is_actual=False."""
        hyp_node = {"id": "HYP-DEC-ABCD1234", "is_actual": False}
        # Must not raise
        assert_not_actual(hyp_node, operation="overwrite") is None

    def test_passes_when_is_actual_missing(self):
        """No exception when is_actual key is absent (treated as falsy)."""
        node = {"id": "SOME-NODE"}
        # is_actual is not present → should not raise
        assert_not_actual(node) is None

    def test_passes_when_is_actual_none(self):
        """No exception when is_actual is None."""
        node = {"id": "SOME-NODE", "is_actual": None}
        assert_not_actual(node) is None


# ---------------------------------------------------------------------------
# record_actual_outcome — validation (no DB needed)
# ---------------------------------------------------------------------------

class TestRecordActualOutcomeValidation:
    """Input-validation tests for record_actual_outcome; no live DB required."""

    def _make_fake_graph(self):
        """Return a minimal fake graph that records calls without hitting DB."""
        class _FakeResult:
            result_set = None
            header = []

        class _FakeGraph:
            calls: list[tuple] = []

            def query(self, cypher, params=None):
                self.calls.append((cypher, params))
                return _FakeResult()

        return _FakeGraph()

    def test_raises_if_id_missing(self):
        """ValueError raised when 'id' is absent from outcome_data."""
        graph = self._make_fake_graph()
        with pytest.raises(ValueError, match="id"):
            record_actual_outcome(
                graph, {"description": "Good result", "observed_at": "2024-01-01"}
            )

    def test_raises_if_description_missing(self):
        """ValueError raised when 'description' is absent."""
        graph = self._make_fake_graph()
        with pytest.raises(ValueError, match="description"):
            record_actual_outcome(
                graph, {"id": "OUT-001", "observed_at": "2024-01-01"}
            )

    def test_raises_if_observed_at_missing(self):
        """ValueError raised when 'observed_at' is absent."""
        graph = self._make_fake_graph()
        with pytest.raises(ValueError, match="observed_at"):
            record_actual_outcome(
                graph, {"id": "OUT-001", "description": "Some outcome"}
            )

    def test_valid_data_calls_graph(self):
        """Valid outcome_data calls graph.query (no ValueError)."""
        graph = self._make_fake_graph()
        # Should not raise — the fake graph returns an empty result
        record_actual_outcome(
            graph,
            {
                "id": "OUT-TEST-001",
                "description": "Test outcome",
                "observed_at": "2024-06-15T00:00:00+00:00",
            },
        )
        assert len(graph.calls) == 1, "Expected exactly one graph.query call"

    def test_cypher_uses_on_create_set(self):
        """The Cypher issued by record_actual_outcome uses ON CREATE SET."""
        graph = self._make_fake_graph()
        record_actual_outcome(
            graph,
            {
                "id": "OUT-TEST-002",
                "description": "Immutable record",
                "observed_at": "2024-07-01T00:00:00+00:00",
            },
        )
        cypher_issued = graph.calls[0][0]
        assert "ON CREATE SET" in cypher_issued, (
            "record_actual_outcome must use ON CREATE SET to avoid overwriting existing data"
        )


# ---------------------------------------------------------------------------
# Live DB tests — skipped when FalkorDB unavailable
# ---------------------------------------------------------------------------

class TestLiveDB:
    """Integration tests that require a running FalkorDB instance."""

    def test_get_actual_decisions_returns_list(self):
        """get_actual_decisions returns a list."""
        graph = _get_graph()
        result = get_actual_decisions(graph)
        assert isinstance(result, list)

    def test_get_actual_outcomes_returns_list(self):
        """get_actual_outcomes returns a list."""
        graph = _get_graph()
        result = get_actual_outcomes(graph)
        assert isinstance(result, list)

    def test_get_actual_evidence_returns_list(self):
        """get_actual_evidence returns a list."""
        graph = _get_graph()
        result = get_actual_evidence(graph)
        assert isinstance(result, list)

    def test_branch_creation_does_not_modify_source_decision(self):
        """
        After create_branch(), the source Decision's is_actual remains True
        and its properties are unchanged.
        """
        from db.branch_service import create_branch
        from db.queries import get_decision_by_id

        graph = _get_graph()

        # Find an actual decision to use as the source
        decisions = get_actual_decisions(graph)
        if not decisions:
            pytest.skip("No actual decisions in DB; seed the database first.")

        source = decisions[0]
        source_id = source["id"]
        original_title = source.get("title")
        original_desc = source.get("description")
        original_made_at = source.get("made_at")

        # Create a branch from this decision
        branch = create_branch(
            graph,
            source_decision_id=source_id,
            branch_name="Immutability test branch",
            description="Verifying the source decision is not modified",
            changed_assumptions=[
                {
                    "field": "budget",
                    "original_value": "1000000",
                    "new_value": "500000",
                }
            ],
        )

        # Re-fetch the source decision and compare
        reloaded = get_decision_by_id(graph, source_id)
        assert reloaded is not None, "Source decision disappeared after branch creation!"
        assert reloaded.get("is_actual") is True, (
            "is_actual was changed on the source decision!"
        )
        assert reloaded.get("title") == original_title, (
            "title was mutated on the source decision!"
        )
        assert reloaded.get("description") == original_desc, (
            "description was mutated on the source decision!"
        )
        assert reloaded.get("made_at") == original_made_at, (
            "made_at was mutated on the source decision!"
        )

    def test_link_outcome_to_non_actual_decision_raises(self):
        """
        link_outcome_to_decision raises HistoryViolationError when the
        target decision is NOT is_actual=True.
        """
        from db.queries import create_scenario_branch, get_branch_by_id

        graph = _get_graph()

        # Create a hypothetical decision via branch_service
        from db.branch_service import create_branch

        decisions = get_actual_decisions(graph)
        if not decisions:
            pytest.skip("No actual decisions in DB.")

        source_id = decisions[0]["id"]
        branch_detail = create_branch(
            graph,
            source_decision_id=source_id,
            branch_name="Test link guard",
            description="Guard test",
            changed_assumptions=[
                {"field": "risk_level", "original_value": "low", "new_value": "high"}
            ],
        )
        hyp_decisions = branch_detail.get("hypothetical_decisions", [])
        if not hyp_decisions:
            pytest.skip("Branch created no hypothetical decisions.")

        hyp_id = hyp_decisions[0]["id"]

        # Attempt to link an outcome to a hypothetical (is_actual=False) decision
        # First, create a dummy outcome in DB
        from db.history import record_actual_outcome
        outcome = record_actual_outcome(
            graph,
            {
                "id": "OUT-GUARD-TEST-001",
                "description": "Guard test outcome",
                "observed_at": "2024-01-01T00:00:00+00:00",
            },
        )

        with pytest.raises(HistoryViolationError):
            link_outcome_to_decision(graph, outcome["id"], hyp_id)
