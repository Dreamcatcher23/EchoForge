"""EchoForge — Multi-agent Coordinator.

Orchestrates multi-agent pipelines:

* :func:`run_scenario_pipeline` — ScenarioAgent → CriticAgent
* :func:`run_evaluation_pipeline` — OutcomeEvaluator
* :func:`get_pipeline_history` — retrieve prior coordinator ``AgentRun`` nodes

The coordinator itself stores a master ``AgentRun`` of ``agent_type="coordinator"``
in FalkorDB referencing the sub-run IDs.  Prior coordinator runs are retrieved
from FalkorDB before each pipeline starts, giving agents awareness of previous
simulations.

Design rules
------------
* Agents coordinate through FalkorDB — no shared mutable Python state.
* Variable data travels via Cypher ``params`` dicts — no f-string injection.
* ``load_dotenv()`` is called at module import time.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

import db.queries as queries
from agents.critic_agent import CriticAgent
from agents.outcome_evaluator import OutcomeEvaluator
from agents.scenario_agent import ScenarioAgent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _make_coordinator_run_id() -> str:
    """Generate a unique coordinator run ID."""
    return f"COORD-{uuid.uuid4().hex[:8].upper()}"


def _save_coordinator_run(
    graph,
    run_id: str,
    started_at: str,
    status: str,
    summary: str,
    input_data: dict,
    output_data: dict,
) -> dict:
    """Persist a coordinator ``AgentRun`` node to FalkorDB.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    run_id:
        Unique identifier for this coordinator run.
    started_at:
        ISO-8601 UTC start timestamp.
    status:
        ``"completed"`` or ``"failed"``.
    summary:
        Human-readable single-line description of the pipeline outcome.
    input_data:
        Dict of pipeline inputs.
    output_data:
        Dict of pipeline outputs.

    Returns
    -------
    dict
        The saved ``AgentRun`` node properties.
    """
    run_data: dict = {
        "id": run_id,
        "agent_type": "coordinator",
        "started_at": started_at,
        "completed_at": _now_iso(),
        "status": status,
        "summary": summary,
        "input_data": json.dumps(input_data, default=str),
        "output_data": json.dumps(output_data, default=str),
    }
    try:
        saved = queries.save_agent_run(graph, run_data)
        logger.info("Coordinator AgentRun saved: %s (status=%s)", run_id, status)
        return saved
    except Exception as exc:
        logger.error("_save_coordinator_run(%s) failed: %s", run_id, exc)
        raise


# ---------------------------------------------------------------------------
# Public pipeline functions
# ---------------------------------------------------------------------------

def run_scenario_pipeline(
    graph,
    branch_id: str,
    decision_id: str,
) -> dict:
    """Run ScenarioAgent → CriticAgent and store a master coordinator AgentRun.

    Prior coordinator runs are retrieved from FalkorDB before the pipeline
    starts, providing context about previous simulations.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    branch_id:
        ``id`` of the target ``ScenarioBranch`` node.
    decision_id:
        ``id`` of the source ``Decision`` node.

    Returns
    -------
    dict
        Keys: ``scenario_result``, ``critique_result``,
        ``coordinator_run_id``, ``prior_runs_count``.
    """
    coordinator_run_id = _make_coordinator_run_id()
    started_at = _now_iso()
    input_data: dict = {"branch_id": branch_id, "decision_id": decision_id}

    # ── Step 1: retrieve prior coordinator runs from FalkorDB ─────────────────
    try:
        prior_runs = queries.get_agent_runs_by_type(graph, "coordinator", limit=10)
        prior_runs_count = len(prior_runs)
        logger.info(
            "Coordinator(%s): %d prior coordinator run(s) retrieved.",
            coordinator_run_id,
            prior_runs_count,
        )
    except Exception as exc:
        logger.warning(
            "Coordinator(%s): prior run retrieval failed (non-fatal): %s",
            coordinator_run_id,
            exc,
        )
        prior_runs_count = 0

    try:
        # ── Step 2: run ScenarioAgent ─────────────────────────────────────────
        logger.info(
            "Coordinator(%s): starting ScenarioAgent for branch '%s'.",
            coordinator_run_id,
            branch_id,
        )
        scenario_agent = ScenarioAgent(graph)
        scenario_result = scenario_agent.run(
            branch_id=branch_id, decision_id=decision_id
        )
        logger.info(
            "Coordinator(%s): ScenarioAgent completed (run_id=%s, status=%s).",
            coordinator_run_id,
            scenario_result.get("run_id"),
            scenario_result.get("status"),
        )

        # ── Step 3: run CriticAgent ───────────────────────────────────────────
        logger.info(
            "Coordinator(%s): starting CriticAgent for branch '%s'.",
            coordinator_run_id,
            branch_id,
        )
        critic_agent = CriticAgent(graph)
        critique_result = critic_agent.run(
            branch_id=branch_id,
            decision_id=decision_id,
            scenario_run_id=scenario_result.get("run_id"),
        )
        logger.info(
            "Coordinator(%s): CriticAgent completed (run_id=%s, status=%s).",
            coordinator_run_id,
            critique_result.get("run_id"),
            critique_result.get("status"),
        )

        # ── Step 4: save coordinator AgentRun ─────────────────────────────────
        summary = (
            f"Scenario pipeline for branch '{branch_id}': "
            f"ScenarioAgent={scenario_result.get('run_id')}, "
            f"CriticAgent={critique_result.get('run_id')}. "
            f"Prior coordinator runs: {prior_runs_count}."
        )
        output_data: dict = {
            "scenario_run_id": scenario_result.get("run_id"),
            "critique_run_id": critique_result.get("run_id"),
            "prior_runs_count": prior_runs_count,
            "branch_id": branch_id,
        }
        _save_coordinator_run(
            graph,
            run_id=coordinator_run_id,
            started_at=started_at,
            status="completed",
            summary=summary,
            input_data=input_data,
            output_data=output_data,
        )

        return {
            "scenario_result": scenario_result,
            "critique_result": critique_result,
            "coordinator_run_id": coordinator_run_id,
            "prior_runs_count": prior_runs_count,
        }

    except Exception as exc:
        logger.error(
            "Coordinator(%s): scenario pipeline failed: %s", coordinator_run_id, exc
        )
        try:
            _save_coordinator_run(
                graph,
                run_id=coordinator_run_id,
                started_at=started_at,
                status="failed",
                summary=f"Scenario pipeline failed: {exc}",
                input_data=input_data,
                output_data={"error": str(exc)},
            )
        except Exception as save_exc:
            logger.error(
                "Coordinator(%s): could not save failure run: %s",
                coordinator_run_id,
                save_exc,
            )
        return {
            "scenario_result": {"status": "failed", "error": str(exc)},
            "critique_result": {"status": "skipped"},
            "coordinator_run_id": coordinator_run_id,
            "prior_runs_count": prior_runs_count if "prior_runs_count" in dir() else 0,
            "error": str(exc),
        }


def run_evaluation_pipeline(
    graph,
    branch_id: str,
    decision_id: str,
    observed_outcome: str,
) -> dict:
    """Run the OutcomeEvaluator and store a master coordinator AgentRun.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    branch_id:
        ``id`` of the target ``ScenarioBranch`` node.
    decision_id:
        ``id`` of the source ``Decision`` node.
    observed_outcome:
        Free-text description of the real observation to compare against
        stored predictions.

    Returns
    -------
    dict
        Keys: ``evaluation_result``, ``coordinator_run_id``.
    """
    coordinator_run_id = _make_coordinator_run_id()
    started_at = _now_iso()
    input_data: dict = {
        "branch_id": branch_id,
        "decision_id": decision_id,
        "observed_outcome": observed_outcome,
    }

    try:
        # ── Step 1: run OutcomeEvaluator ──────────────────────────────────────
        logger.info(
            "Coordinator(%s): starting OutcomeEvaluator for branch '%s'.",
            coordinator_run_id,
            branch_id,
        )
        evaluator = OutcomeEvaluator(graph)
        evaluation_result = evaluator.run(
            branch_id=branch_id,
            decision_id=decision_id,
            observed_outcome=observed_outcome,
        )
        logger.info(
            "Coordinator(%s): OutcomeEvaluator completed (run_id=%s, status=%s).",
            coordinator_run_id,
            evaluation_result.get("run_id"),
            evaluation_result.get("status"),
        )

        # ── Step 2: save coordinator AgentRun ─────────────────────────────────
        summary = (
            f"Evaluation pipeline for branch '{branch_id}': "
            f"OutcomeEvaluator={evaluation_result.get('run_id')}. "
            f"Outcome node: {evaluation_result.get('outcome_id', 'N/A')}."
        )
        output_data: dict = {
            "evaluator_run_id": evaluation_result.get("run_id"),
            "outcome_id": evaluation_result.get("outcome_id", ""),
            "branch_id": branch_id,
        }
        _save_coordinator_run(
            graph,
            run_id=coordinator_run_id,
            started_at=started_at,
            status="completed",
            summary=summary,
            input_data=input_data,
            output_data=output_data,
        )

        return {
            "evaluation_result": evaluation_result,
            "coordinator_run_id": coordinator_run_id,
        }

    except Exception as exc:
        logger.error(
            "Coordinator(%s): evaluation pipeline failed: %s", coordinator_run_id, exc
        )
        try:
            _save_coordinator_run(
                graph,
                run_id=coordinator_run_id,
                started_at=started_at,
                status="failed",
                summary=f"Evaluation pipeline failed: {exc}",
                input_data=input_data,
                output_data={"error": str(exc)},
            )
        except Exception as save_exc:
            logger.error(
                "Coordinator(%s): could not save failure run: %s",
                coordinator_run_id,
                save_exc,
            )
        return {
            "evaluation_result": {"status": "failed", "error": str(exc)},
            "coordinator_run_id": coordinator_run_id,
            "error": str(exc),
        }


def get_pipeline_history(graph, limit: int = 10) -> list[dict]:
    """Return recent coordinator ``AgentRun`` nodes from FalkorDB.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    limit:
        Maximum number of runs to return (default 10).

    Returns
    -------
    list[dict]
        Coordinator ``AgentRun`` dicts, most recent first.
        Returns an empty list on any query failure (logged as warning).
    """
    try:
        runs = queries.get_agent_runs_by_type(graph, "coordinator", limit=limit)
        logger.debug("get_pipeline_history() -> %d run(s).", len(runs))
        return runs
    except Exception as exc:
        logger.warning("get_pipeline_history() failed (non-fatal): %s", exc)
        return []
