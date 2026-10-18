"""EchoForge — Integration tests.

Tests in this module require a live FalkorDB instance.  Each test class uses
``pytest.mark.skipif`` or inline ``pytest.skip()`` calls to gracefully skip
when FalkorDB is unavailable so the suite still passes in CI without a DB.

Run all tests:
    pytest tests/ -v

Run only integration tests with a live DB:
    pytest tests/test_integration.py -v --tb=short
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------


def _try_get_graph():
    """Return (graph, True) if FalkorDB is reachable, else (None, False)."""
    try:
        from db.connection import get_graph, test_connection

        graph = get_graph()
        if test_connection():
            return graph, True
        return None, False
    except Exception:
        return None, False


def _skip_if_no_db():
    """Call pytest.skip() when FalkorDB is not available."""
    _, ok = _try_get_graph()
    if not ok:
        pytest.skip("FalkorDB not available — skipping integration test.")


def _unique_id(prefix: str = "TEST") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# TestBranchIsolation
# ---------------------------------------------------------------------------


class TestBranchIsolation:
    """Verify that creating a branch never mutates actual-history Decision nodes."""

    def test_branch_creation_does_not_modify_actual_decision(self):
        """CRITICAL: DEC-001.is_actual must remain True after branch creation.

        After creating a branch from DEC-001, verify that DEC-001.is_actual
        is still True and all original properties are unchanged.
        """
        _skip_if_no_db()
        graph, _ = _try_get_graph()

        # Seed and ensure DEC-001 exists
        from db.schema import create_schema
        from db.seed import seed_database

        create_schema(graph)
        seed_database(graph)

        # Read DEC-001 BEFORE branch creation
        from db.queries import get_decision_by_id

        before = get_decision_by_id(graph, "DEC-001")
        assert before is not None, "DEC-001 must exist after seeding"
        assert before.get("is_actual") is True, "DEC-001 must be actual before branch"

        # Create a branch from DEC-001
        from db.branch_service import create_branch

        branch_data = create_branch(
            graph,
            source_decision_id="DEC-001",
            branch_name="Isolation Test Branch",
            description="Tests that DEC-001 is not mutated.",
            changed_assumptions=[
                {"field": "budget", "original_value": "500K", "new_value": "250K"}
            ],
        )

        # Read DEC-001 AFTER branch creation
        after = get_decision_by_id(graph, "DEC-001")
        assert after is not None, "DEC-001 must still exist after branch"
        assert after.get("is_actual") is True, "DEC-001.is_actual must still be True"
        assert after.get("title") == before.get("title"), "title must not change"
        assert after.get("description") == before.get("description"), "description must not change"
        assert after.get("made_at") == before.get("made_at"), "made_at must not change"

    def test_hypothetical_decision_has_is_actual_false(self):
        """Hypothetical Decision nodes created in branches must have is_actual=False."""
        _skip_if_no_db()
        graph, _ = _try_get_graph()

        from db.schema import create_schema
        from db.seed import seed_database

        create_schema(graph)
        seed_database(graph)

        from db.branch_service import create_branch, get_branch_detail

        branch = create_branch(
            graph,
            source_decision_id="DEC-001",
            branch_name="Hyp is_actual Test",
            description="Verifies hypothetical Decision is_actual=False",
            changed_assumptions=[
                {"field": "timeline", "original_value": "Q1", "new_value": "Q3"}
            ],
        )

        branch_id = branch.get("branch", {}).get("id")
        assert branch_id is not None, "Branch ID must be returned"

        detail = get_branch_detail(graph, branch_id)
        hyp_decisions = detail.get("hypothetical_decisions", [])
        assert len(hyp_decisions) > 0, "At least one hypothetical Decision must be created"

        for hd in hyp_decisions:
            assert hd.get("is_actual") is False, (
                f"Hypothetical Decision {hd.get('id')} must have is_actual=False"
            )

    def test_actual_outcomes_not_overwritten(self):
        """record_actual_outcome() with an existing id must not overwrite description (ON CREATE SET semantics)."""
        _skip_if_no_db()
        graph, _ = _try_get_graph()

        from db.history import record_actual_outcome

        original_desc = "Original outcome description — must not be overwritten"
        out_id = _unique_id("OUT")

        # First write
        saved = record_actual_outcome(
            graph,
            {"id": out_id, "description": original_desc, "observed_at": _now_iso()},
        )
        assert saved.get("id") == out_id
        assert saved.get("description") == original_desc

        # Attempt overwrite — ON CREATE SET ensures this is a no-op
        record_actual_outcome(
            graph,
            {
                "id": out_id,
                "description": "OVERWRITTEN — this must NOT appear",
                "observed_at": _now_iso(),
            },
        )

        # Read back and verify
        cypher = "MATCH (o:Outcome {id: $id}) RETURN o.description AS desc"
        result = graph.query(cypher, {"id": out_id})
        rows = list(result.result_set) if result.result_set else []
        assert rows, "Outcome must exist after second write"
        desc_in_db = rows[0][0]
        assert desc_in_db == original_desc, (
            f"Expected original description but got: {desc_in_db!r}"
        )


# ---------------------------------------------------------------------------
# TestOutcomeEvaluation
# ---------------------------------------------------------------------------


class TestOutcomeEvaluation:
    """Tests for prediction-outcome evaluation mechanics."""

    def test_evaluation_stores_status_in_db(self):
        """link_prediction_to_outcome() creates EVALUATED_AGAINST rel with status property."""
        _skip_if_no_db()
        graph, _ = _try_get_graph()

        from db.schema import create_schema
        from db.seed import seed_database

        create_schema(graph)
        seed_database(graph)

        from db.branch_service import create_branch
        from db.queries import create_prediction, create_outcome, link_prediction_to_outcome

        # Create a branch
        branch = create_branch(
            graph,
            source_decision_id="DEC-001",
            branch_name="Eval Status Test",
            description="Tests EVALUATED_AGAINST relationship.",
            changed_assumptions=[{"field": "scope", "original_value": "national", "new_value": "regional"}],
        )
        branch_id = branch.get("branch", {}).get("id")
        assert branch_id is not None

        # Create a prediction for that branch
        pred = create_prediction(graph, {
            "content": "Integration test prediction",
            "confidence": 0.72,
            "branch_id": branch_id,
        })
        pred_id = pred.get("id")
        assert pred_id is not None

        # Create an outcome
        outcome = create_outcome(graph, {
            "description": "Integration test outcome",
            "branch_id": branch_id,
        })
        out_id = outcome.get("id")
        assert out_id is not None

        # Link with status
        result = link_prediction_to_outcome(graph, pred_id, out_id, "supported")
        assert result is True

        # Verify the relationship and status in the graph
        verify_cypher = (
            "MATCH (p:Prediction {id: $pred_id})-[r:EVALUATED_AGAINST]->(o:Outcome {id: $out_id}) "
            "RETURN r.status AS status"
        )
        vr = graph.query(verify_cypher, {"pred_id": pred_id, "out_id": out_id})
        rows = list(vr.result_set) if vr.result_set else []
        assert rows, "EVALUATED_AGAINST relationship must exist"
        assert rows[0][0] == "supported", f"status must be 'supported', got {rows[0][0]!r}"

    def test_evaluation_status_values(self):
        """Only 'supported', 'contradicted', 'inconclusive' are accepted."""
        _skip_if_no_db()
        graph, _ = _try_get_graph()

        from db.schema import create_schema
        from db.seed import seed_database

        create_schema(graph)
        seed_database(graph)

        from db.branch_service import create_branch
        from db.queries import create_prediction, create_outcome, link_prediction_to_outcome

        branch = create_branch(
            graph,
            source_decision_id="DEC-001",
            branch_name="Status Validation Test",
            description="Tests status enum validation.",
            changed_assumptions=[{"field": "risk", "original_value": "low", "new_value": "high"}],
        )
        branch_id = branch.get("branch", {}).get("id")

        pred = create_prediction(graph, {"content": "Status test pred", "confidence": 0.5, "branch_id": branch_id})
        outcome = create_outcome(graph, {"description": "Status test outcome", "branch_id": branch_id})

        valid_statuses = ["supported", "contradicted", "inconclusive"]
        for status in valid_statuses:
            # Create separate prediction + outcome for each status
            p2 = create_prediction(graph, {"content": f"pred for {status}", "confidence": 0.5, "branch_id": branch_id})
            o2 = create_outcome(graph, {"description": f"outcome for {status}", "branch_id": branch_id})
            result = link_prediction_to_outcome(graph, p2.get("id"), o2.get("id"), status)
            assert result is True, f"Status '{status}' must be accepted"

        # Invalid status must raise ValueError
        with pytest.raises(ValueError, match="evaluation_status must be one of"):
            link_prediction_to_outcome(graph, pred.get("id"), outcome.get("id"), "invalid_status")


# ---------------------------------------------------------------------------
# TestEndToEndSmoke
# ---------------------------------------------------------------------------


class TestEndToEndSmoke:
    """End-to-end smoke tests running the full pipeline without real LLM calls."""

    def test_full_pipeline_without_llm(self):
        """seed → create branch → run_scenario_pipeline → run_evaluation_pipeline → AgentRun nodes exist."""
        _skip_if_no_db()
        graph, _ = _try_get_graph()

        from db.schema import create_schema
        from db.seed import seed_database

        create_schema(graph)
        seed_database(graph)

        # Create branch
        from db.branch_service import create_branch

        branch = create_branch(
            graph,
            source_decision_id="DEC-001",
            branch_name="E2E Smoke Branch",
            description="End-to-end smoke test branch.",
            changed_assumptions=[
                {"field": "headcount", "original_value": "50", "new_value": "30"}
            ],
        )
        branch_id = branch.get("branch", {}).get("id")
        assert branch_id is not None, "Branch must be created"

        # Run scenario pipeline (uses deterministic fallback when no LLM key)
        from agents.coordinator import run_scenario_pipeline

        scenario_result = run_scenario_pipeline(graph, branch_id, "DEC-001")
        # Pipeline either succeeds or fails gracefully — both produce a coordinator_run_id
        assert "coordinator_run_id" in scenario_result

        # Run evaluation pipeline
        from agents.coordinator import run_evaluation_pipeline

        eval_result = run_evaluation_pipeline(
            graph,
            branch_id=branch_id,
            decision_id="DEC-001",
            observed_outcome="Headcount reduction led to project delays.",
        )
        assert "coordinator_run_id" in eval_result

        # Verify AgentRun nodes exist in DB
        from db.queries import get_agent_runs

        runs = get_agent_runs(graph)
        assert len(runs) > 0, "At least one AgentRun node must exist after pipeline run"

        run_ids = {r.get("id") for r in runs}
        assert scenario_result.get("coordinator_run_id") in run_ids, (
            "Coordinator run must be persisted in FalkorDB"
        )

    def test_comparison_structure(self):
        """compare_decision_to_branch returns dict with actual, hypothetical, diff keys."""
        _skip_if_no_db()
        graph, _ = _try_get_graph()

        from db.schema import create_schema
        from db.seed import seed_database

        create_schema(graph)
        seed_database(graph)

        from db.branch_service import create_branch
        from core.comparison import compare_decision_to_branch

        branch = create_branch(
            graph,
            source_decision_id="DEC-001",
            branch_name="Comparison Structure Test",
            description="Tests the structure of compare_decision_to_branch output.",
            changed_assumptions=[
                {"field": "vendor", "original_value": "TechCorp", "new_value": "StartupX"}
            ],
        )
        branch_id = branch.get("branch", {}).get("id")

        comparison = compare_decision_to_branch(graph, "DEC-001", branch_id)

        # Must have top-level keys
        assert "actual" in comparison, "comparison must have 'actual' key"
        assert "hypothetical" in comparison, "comparison must have 'hypothetical' key"
        assert "diff" in comparison, "comparison must have 'diff' key"

        # actual section
        actual = comparison["actual"]
        assert "decision" in actual
        assert "evidence" in actual
        assert "affected_entities" in actual
        assert "outcome" in actual

        # hypothetical section
        hyp = comparison["hypothetical"]
        assert "branch" in hyp
        assert "changed_assumptions" in hyp
        assert "affected_entities" in hyp
        assert "predictions" in hyp

        # diff section
        diff = comparison["diff"]
        assert "added_impacts" in diff
        assert "removed_impacts" in diff
        assert "assumption_changes" in diff
        assert "evidence_gaps" in diff

        # Values must be lists (may be empty)
        assert isinstance(diff["added_impacts"], list)
        assert isinstance(diff["removed_impacts"], list)
        assert isinstance(diff["assumption_changes"], list)


# ---------------------------------------------------------------------------
# Pure-unit tests (no DB required)
# ---------------------------------------------------------------------------


class TestUnitHelpers:
    """Pure unit tests that run without a FalkorDB connection."""

    def test_status_badge_known_statuses(self):
        """status_badge() returns non-empty HTML for known statuses."""
        from app.components.ui_helpers import status_badge

        for s in ["active", "archived", "completed", "failed", "supported", "contradicted", "inconclusive"]:
            badge = status_badge(s)
            assert isinstance(badge, str) and len(badge) > 10, f"Badge for '{s}' is empty"
            assert s.upper() in badge, f"Status text '{s}' missing from badge"

    def test_status_badge_unknown_status(self):
        """status_badge() returns a fallback for unknown statuses."""
        from app.components.ui_helpers import status_badge

        badge = status_badge("unknown_xyz")
        assert "UNKNOWN_XYZ" in badge

    def test_format_datetime_iso(self):
        """format_datetime() parses ISO-8601 strings correctly."""
        from app.components.ui_helpers import format_datetime

        result = format_datetime("2024-03-15T10:30:00+00:00")
        assert "2024" in result
        assert "Mar" in result

    def test_format_datetime_empty(self):
        """format_datetime() returns '—' for empty/None input."""
        from app.components.ui_helpers import format_datetime

        assert format_datetime(None) == "—"
        assert format_datetime("") == "—"

    def test_comparison_format_for_display(self):
        """format_comparison_for_display() transforms raw comparison correctly."""
        from core.comparison import format_comparison_for_display

        raw = {
            "actual": {
                "decision": {"id": "DEC-001", "title": "Test", "description": "Desc", "made_at": "2024-01-01"},
                "evidence": [{"id": "EV-1", "content": "Some evidence", "source": "src", "created_at": "2024-01-01"}],
                "affected_entities": [{"id": "PROJ-1", "label": "Project", "name": "Alpha", "depth": 1}],
                "outcome": None,
            },
            "hypothetical": {
                "branch": {"id": "BR-1", "name": "Test Branch", "description": "Desc", "created_at": "2024-01-02", "status": "active"},
                "changed_assumptions": [{"field": "budget", "original_value": "100K", "new_value": "50K"}],
                "affected_entities": [],
                "predictions": [{"id": "P-1", "content": "Pred text", "confidence": 0.75, "created_at": "2024-01-02", "status": "pending"}],
            },
            "diff": {
                "added_impacts": [],
                "removed_impacts": [{"id": "PROJ-1", "label": "Project", "name": "Alpha", "depth": 1}],
                "assumption_changes": [{"field": "budget", "original_value": "100K", "new_value": "50K"}],
                "evidence_gaps": [],
            },
        }

        display = format_comparison_for_display(raw)
        assert "actual_panel" in display
        assert "hypothetical_panel" in display
        assert "diff_panel" in display

        assert display["actual_panel"]["decision_id"] == "DEC-001"
        assert display["hypothetical_panel"]["branch_name"] == "Test Branch"
        assert len(display["diff_panel"]["removed_impacts"]) == 1
        assert display["diff_panel"]["net_impact_delta"] == -1

    def test_history_violation_error(self):
        """assert_not_actual() raises HistoryViolationError for actual nodes."""
        from db.history import assert_not_actual, HistoryViolationError

        with pytest.raises(HistoryViolationError):
            assert_not_actual({"id": "DEC-001", "is_actual": True}, operation="delete")

    def test_assert_not_actual_passes_for_hypothetical(self):
        """assert_not_actual() does not raise for is_actual=False nodes."""
        from db.history import assert_not_actual

        # Should not raise
        assert_not_actual({"id": "HYP-DEC-001", "is_actual": False}, operation="modify")

    def test_link_prediction_invalid_status_raises(self):
        """link_prediction_to_outcome() raises ValueError for invalid status without DB."""
        from db.queries import link_prediction_to_outcome

        # Without DB, this should fail early on the status validation
        with pytest.raises(ValueError, match="evaluation_status must be one of"):
            link_prediction_to_outcome(None, "PRED-1", "OUT-1", "nonsense_status")
