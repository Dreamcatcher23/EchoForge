"""EchoForge — Basic connectivity placeholder tests.

These tests serve as structural placeholders for Phase 1.  A live FalkorDB
instance is required for the integration assertions; the unit-level checks
validate import paths and module structure without requiring a running server.

Run with::

    pytest tests/test_connection.py -v

To run against a live FalkorDB instance set FALKORDB_HOST / FALKORDB_PORT in
your environment or .env file before running pytest.
"""

import importlib
import os

import pytest


# ---------------------------------------------------------------------------
# Module import checks (no live DB required)
# ---------------------------------------------------------------------------

def test_connection_module_importable():
    """``db.connection`` must be importable without a running FalkorDB."""
    mod = importlib.import_module("db.connection")
    assert hasattr(mod, "get_graph"), "get_graph not found in db.connection"
    assert hasattr(mod, "test_connection"), "test_connection not found in db.connection"


def test_schema_module_importable():
    """``db.schema`` must be importable."""
    mod = importlib.import_module("db.schema")
    assert hasattr(mod, "create_schema"), "create_schema not found in db.schema"


def test_seed_module_importable():
    """``db.seed`` must be importable."""
    mod = importlib.import_module("db.seed")
    assert hasattr(mod, "seed_database"), "seed_database not found in db.seed"


def test_queries_module_importable():
    """``db.queries`` must be importable and expose required functions."""
    mod = importlib.import_module("db.queries")
    expected_functions = [
        "get_all_decisions",
        "get_decision_by_id",
        "get_decision_evidence",
        "get_affected_entities",
        "get_scenario_branches",
        "get_branch_by_id",
        "create_scenario_branch",
        "get_dependency_path",
        "get_predictions_for_branch",
        "get_outcomes",
        "get_agent_runs",
    ]
    for fn_name in expected_functions:
        assert hasattr(mod, fn_name), f"{fn_name} not found in db.queries"


def test_agents_package_importable():
    """``agents`` package must be importable."""
    importlib.import_module("agents")


# ---------------------------------------------------------------------------
# Live connectivity test (skipped when FalkorDB is unavailable)
# ---------------------------------------------------------------------------

_SKIP_LIVE = pytest.mark.skipif(
    os.getenv("FALKORDB_HOST") is None and os.getenv("CI") is None,
    reason="FALKORDB_HOST not set; skipping live connectivity test",
)


@_SKIP_LIVE
def test_live_connection():
    """Verify that test_connection() returns True against a live FalkorDB."""
    from db.connection import test_connection

    result = test_connection()
    assert result is True, "test_connection() returned False — check FalkorDB availability"


@_SKIP_LIVE
def test_live_get_graph_returns_object():
    """Verify that get_graph() returns a graph object (not None)."""
    from db.connection import get_graph

    graph = get_graph()
    assert graph is not None, "get_graph() returned None"
