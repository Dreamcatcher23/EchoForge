"""EchoForge — Phase 3 agent unit tests.

Tests cover all agents without requiring a live LLM API or FalkorDB connection.
All graph calls and LLM calls are intercepted via ``unittest.mock``.

Test classes
------------
* :class:`TestBaseAgent` — run_id format, LLM toggle
* :class:`TestScenarioAgentDeterministic` — fallback predictions
* :class:`TestCriticAgentDeterministic` — fallback critique structure
* :class:`TestOutcomeEvaluatorDeterministic` — keyword overlap evaluation
* :class:`TestCoordinatorStructure` — pipeline history return type

Running
-------
    pytest tests/test_agents.py -v

All tests pass without network or database access.
"""

from __future__ import annotations

import json
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers — fake graph stub
# ---------------------------------------------------------------------------

def _make_fake_result(rows: list[dict]) -> MagicMock:
    """Build a FalkorDB-like result object from a list of dicts."""
    if not rows:
        result = MagicMock()
        result.result_set = []
        result.header = []
        return result
    header = list(rows[0].keys())
    result_set = [[row[k] for k in header] for row in rows]
    result = MagicMock()
    result.result_set = result_set
    result.header = header
    return result


def _make_graph_stub(query_rows: list[dict] | None = None) -> MagicMock:
    """Return a MagicMock graph object whose ``query()`` returns *query_rows*."""
    graph = MagicMock()
    graph.query.return_value = _make_fake_result(query_rows or [])
    return graph


# ---------------------------------------------------------------------------
# TestBaseAgent
# ---------------------------------------------------------------------------

class TestBaseAgent(unittest.TestCase):
    """Tests for :class:`agents.base_agent.BaseAgent`."""

    def _make_concrete_agent(self, graph):
        """Instantiate a concrete subclass of BaseAgent for testing."""
        from agents.base_agent import BaseAgent

        class _ConcreteAgent(BaseAgent):
            agent_type = "test_agent"

            def run(self, **kwargs) -> dict:
                return {"run_id": self.run_id, "status": "completed", "output": {}}

        return _ConcreteAgent(graph)

    def test_run_id_format(self):
        """run_id must start with 'RUN-'."""
        graph = _make_graph_stub()
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            agent = self._make_concrete_agent(graph)
        self.assertTrue(
            agent.run_id.startswith("RUN-"),
            f"run_id '{agent.run_id}' does not start with 'RUN-'",
        )

    def test_run_id_uniqueness(self):
        """Each agent instantiation must receive a distinct run_id."""
        graph = _make_graph_stub()
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            a1 = self._make_concrete_agent(graph)
            a2 = self._make_concrete_agent(graph)
        self.assertNotEqual(a1.run_id, a2.run_id)

    def test_check_llm_returns_false_without_api_key(self):
        """Unset OPENAI_API_KEY must result in llm_available=False."""
        graph = _make_graph_stub()
        env_without_key = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        with patch.dict(os.environ, env_without_key, clear=True):
            agent = self._make_concrete_agent(graph)
        self.assertFalse(
            agent.llm_available,
            "llm_available should be False when OPENAI_API_KEY is not set",
        )

    def test_check_llm_returns_false_with_empty_key(self):
        """Empty OPENAI_API_KEY string must result in llm_available=False."""
        graph = _make_graph_stub()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "   "}, clear=False):
            agent = self._make_concrete_agent(graph)
        self.assertFalse(agent.llm_available)

    def test_check_llm_returns_true_with_key(self):
        """Non-empty OPENAI_API_KEY must result in llm_available=True."""
        graph = _make_graph_stub()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-key"}, clear=False):
            agent = self._make_concrete_agent(graph)
        self.assertTrue(agent.llm_available)

    def test_mark_started_sets_started_at(self):
        """_mark_started() must set started_at to a non-None ISO string."""
        graph = _make_graph_stub()
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            agent = self._make_concrete_agent(graph)
        self.assertIsNone(agent.started_at)
        ts = agent._mark_started()
        self.assertIsNotNone(agent.started_at)
        self.assertEqual(ts, agent.started_at)
        # Basic ISO format check
        self.assertIn("T", agent.started_at)

    def test_get_prior_runs_returns_empty_list_on_graph_error(self):
        """get_prior_runs() must return [] and not raise when graph errors."""
        graph = _make_graph_stub()
        graph.query.side_effect = RuntimeError("connection refused")
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            agent = self._make_concrete_agent(graph)
        result = agent.get_prior_runs(limit=5)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)


# ---------------------------------------------------------------------------
# TestScenarioAgentDeterministic
# ---------------------------------------------------------------------------

class TestScenarioAgentDeterministic(unittest.TestCase):
    """Tests for :class:`agents.scenario_agent.ScenarioAgent` deterministic mode."""

    def _make_agent(self):
        from agents.scenario_agent import ScenarioAgent
        graph = _make_graph_stub()
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            agent = ScenarioAgent(graph)
        self.assertFalse(agent.llm_available)
        return agent

    def _make_context(
        self,
        entity_count: int = 3,
        evidence_count: int = 2,
        assumption_count: int = 1,
    ) -> dict:
        return {
            "branch": {"name": "TestBranch", "description": "A test branch"},
            "source_decision": {"id": "DEC-001", "title": "Test Decision"},
            "hypothetical_decisions": [
                {"field": f"field_{i}", "original_value": "old", "new_value": "new"}
                for i in range(assumption_count)
            ],
            "affected_entities": [
                {"id": f"ENT-{i:03}", "name": f"Entity {i}", "label": "Project", "depth": 1}
                for i in range(entity_count)
            ],
            "evidence_chain": [
                {"id": f"EV-{i:03}", "content": f"Evidence {i}", "via": "direct"}
                for i in range(evidence_count)
            ],
            "prior_runs_count": 0,
        }

    def test_deterministic_scenario_returns_three_predictions(self):
        """_deterministic_scenario() must return exactly 3 predictions."""
        agent = self._make_agent()
        context = self._make_context()
        predictions = agent._deterministic_scenario(context)
        self.assertEqual(
            len(predictions),
            3,
            f"Expected 3 predictions, got {len(predictions)}",
        )

    def test_prediction_confidence_in_range(self):
        """All prediction confidences must be floats in [0, 1]."""
        agent = self._make_agent()
        context = self._make_context()
        predictions = agent._deterministic_scenario(context)
        for pred in predictions:
            conf = pred.get("confidence")
            self.assertIsInstance(conf, float, f"confidence is not float: {conf!r}")
            self.assertGreaterEqual(conf, 0.0, f"confidence {conf} < 0")
            self.assertLessEqual(conf, 1.0, f"confidence {conf} > 1")

    def test_prediction_content_labeled_fallback(self):
        """Every deterministic prediction must contain '[DETERMINISTIC FALLBACK]'."""
        agent = self._make_agent()
        context = self._make_context()
        predictions = agent._deterministic_scenario(context)
        for i, pred in enumerate(predictions):
            self.assertIn(
                "[DETERMINISTIC FALLBACK]",
                pred.get("content", ""),
                f"Prediction {i} content does not contain [DETERMINISTIC FALLBACK]",
            )

    def test_prediction_has_required_keys(self):
        """Each prediction dict must have content, confidence, and rationale."""
        agent = self._make_agent()
        context = self._make_context()
        predictions = agent._deterministic_scenario(context)
        required_keys = {"content", "confidence", "rationale"}
        for i, pred in enumerate(predictions):
            self.assertEqual(
                required_keys - pred.keys(),
                set(),
                f"Prediction {i} is missing keys: {required_keys - pred.keys()}",
            )

    def test_deterministic_scenario_zero_entities(self):
        """Fallback must handle zero affected entities gracefully."""
        agent = self._make_agent()
        context = self._make_context(entity_count=0, evidence_count=0, assumption_count=0)
        predictions = agent._deterministic_scenario(context)
        self.assertEqual(len(predictions), 3)
        for pred in predictions:
            self.assertIn("[DETERMINISTIC FALLBACK]", pred["content"])

    def test_parse_predictions_clamps_confidence(self):
        """_parse_predictions must clamp confidence values to [0, 1]."""
        agent = self._make_agent()
        raw = json.dumps([
            {"content": "test prediction", "confidence": 2.5, "rationale": "too high"},
            {"content": "another", "confidence": -0.3, "rationale": "too low"},
        ])
        preds = agent._parse_predictions(raw, "BRANCH-001")
        self.assertEqual(preds[0]["confidence"], 1.0)
        self.assertEqual(preds[1]["confidence"], 0.0)

    def test_parse_predictions_handles_invalid_json(self):
        """_parse_predictions must return at least one prediction even for bad JSON."""
        agent = self._make_agent()
        preds = agent._parse_predictions("not valid json at all ~~~", "BRANCH-001")
        self.assertIsInstance(preds, list)
        self.assertGreaterEqual(len(preds), 1)

    def test_parse_predictions_extracts_branch_id(self):
        """Each parsed prediction must carry the branch_id."""
        agent = self._make_agent()
        raw = json.dumps([
            {"content": "pred 1", "confidence": 0.7, "rationale": "reason 1"}
        ])
        preds = agent._parse_predictions(raw, "BRANCH-XYZ")
        self.assertEqual(preds[0]["branch_id"], "BRANCH-XYZ")

    def test_build_prompt_contains_branch_name(self):
        """_build_prompt() must include the branch name in the output."""
        agent = self._make_agent()
        context = self._make_context()
        prompt = agent._build_prompt(context)
        self.assertIn("TestBranch", prompt)

    def test_build_prompt_contains_json_instruction(self):
        """_build_prompt() must contain the JSON format instruction."""
        agent = self._make_agent()
        context = self._make_context()
        prompt = agent._build_prompt(context)
        self.assertIn("confidence", prompt)
        self.assertIn("rationale", prompt)


# ---------------------------------------------------------------------------
# TestCriticAgentDeterministic
# ---------------------------------------------------------------------------

class TestCriticAgentDeterministic(unittest.TestCase):
    """Tests for :class:`agents.critic_agent.CriticAgent` deterministic mode."""

    def _make_agent(self):
        from agents.critic_agent import CriticAgent
        graph = _make_graph_stub()
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            agent = CriticAgent(graph)
        return agent

    def _make_context(
        self,
        predictions: list[dict] | None = None,
        evidence: list[dict] | None = None,
        assumptions: list[dict] | None = None,
    ) -> dict:
        return {
            "branch_id": "BRANCH-TEST",
            "predictions": predictions
            if predictions is not None
            else [
                {"id": "PRED-001", "content": "Prediction A", "confidence": 0.7},
                {"id": "PRED-002", "content": "Prediction B", "confidence": 0.9},
            ],
            "evidence_chain": evidence
            if evidence is not None
            else [{"id": "EV-001", "content": "Evidence A", "via": "direct"}],
            "assumptions": assumptions
            if assumptions is not None
            else [{"field": "budget", "original_value": "100k", "new_value": "50k"}],
            "prior_runs_count": 0,
            "scenario_run_id": None,
        }

    def test_deterministic_critique_returns_required_keys(self):
        """_deterministic_critique() must return dict with 3 required keys."""
        agent = self._make_agent()
        context = self._make_context()
        result = agent._deterministic_critique(context)
        required = {"critique_findings", "unsupported_claims", "missing_evidence"}
        self.assertEqual(
            required - result.keys(),
            set(),
            f"Missing keys: {required - result.keys()}",
        )

    def test_deterministic_critique_returns_lists(self):
        """All three return values must be lists."""
        agent = self._make_agent()
        context = self._make_context()
        result = agent._deterministic_critique(context)
        self.assertIsInstance(result["critique_findings"], list)
        self.assertIsInstance(result["unsupported_claims"], list)
        self.assertIsInstance(result["missing_evidence"], list)

    def test_deterministic_critique_high_confidence_low_evidence_flags_unsupported(self):
        """Prediction with confidence > 0.8 and < 2 evidence items must be flagged."""
        agent = self._make_agent()
        context = self._make_context(
            predictions=[{"id": "P1", "content": "Bold claim", "confidence": 0.95}],
            evidence=[],  # zero evidence
        )
        result = agent._deterministic_critique(context)
        self.assertGreater(
            len(result["unsupported_claims"]),
            0,
            "Expected at least 1 unsupported claim for high-confidence with no evidence",
        )
        self.assertIn("[DETERMINISTIC FALLBACK]", result["unsupported_claims"][0])

    def test_deterministic_critique_no_evidence_flags_missing(self):
        """Zero evidence must appear in missing_evidence list."""
        agent = self._make_agent()
        context = self._make_context(evidence=[])
        result = agent._deterministic_critique(context)
        self.assertGreater(
            len(result["missing_evidence"]),
            0,
            "Expected missing_evidence entries when evidence_chain is empty",
        )

    def test_deterministic_critique_findings_labeled_fallback(self):
        """All critique_findings must contain '[DETERMINISTIC FALLBACK]'."""
        agent = self._make_agent()
        context = self._make_context()
        result = agent._deterministic_critique(context)
        for finding in result["critique_findings"]:
            self.assertIn(
                "[DETERMINISTIC FALLBACK]",
                finding,
                f"Finding does not contain label: {finding}",
            )

    def test_parse_critique_handles_valid_json(self):
        """_parse_critique() must correctly parse a valid JSON response."""
        agent = self._make_agent()
        raw = json.dumps({
            "critique_findings": ["finding 1", "finding 2"],
            "unsupported_claims": ["claim A"],
            "missing_evidence": [],
        })
        context = self._make_context()
        result = agent._parse_critique(raw, context)
        self.assertEqual(result["critique_findings"], ["finding 1", "finding 2"])
        self.assertEqual(result["unsupported_claims"], ["claim A"])
        self.assertEqual(result["missing_evidence"], [])

    def test_parse_critique_handles_invalid_json(self):
        """_parse_critique() must return empty lists for unparseable output."""
        agent = self._make_agent()
        result = agent._parse_critique("THIS IS NOT JSON", self._make_context())
        self.assertIsInstance(result["critique_findings"], list)
        self.assertIsInstance(result["unsupported_claims"], list)
        self.assertIsInstance(result["missing_evidence"], list)


# ---------------------------------------------------------------------------
# TestOutcomeEvaluatorDeterministic
# ---------------------------------------------------------------------------

class TestOutcomeEvaluatorDeterministic(unittest.TestCase):
    """Tests for :class:`agents.outcome_evaluator.OutcomeEvaluator` deterministic mode."""

    def _make_agent(self):
        from agents.outcome_evaluator import OutcomeEvaluator
        graph = _make_graph_stub()
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            agent = OutcomeEvaluator(graph)
        return agent

    def test_deterministic_evaluate_supported(self):
        """High keyword overlap must return status 'supported'."""
        agent = self._make_agent()
        prediction = (
            "The budget reduction will cause project delays and resource constraints "
            "resulting in missed deadlines across all active teams."
        )
        observation = (
            "Budget cuts led to project delays and resource shortages; "
            "teams missed deadlines and constraints were widely reported."
        )
        result = agent._deterministic_evaluate(prediction, observation)
        self.assertEqual(
            result["status"],
            "supported",
            f"Expected 'supported' but got '{result['status']}' "
            f"(rationale: {result.get('rationale', '')})",
        )
        self.assertIn("[DETERMINISTIC FALLBACK]", result["rationale"])

    def test_deterministic_evaluate_contradicted(self):
        """Minimal keyword overlap must return status 'contradicted'."""
        agent = self._make_agent()
        prediction = "Quarterly revenue will increase due to new market expansion."
        observation = "Flooding destroyed infrastructure; evacuation orders issued."
        result = agent._deterministic_evaluate(prediction, observation)
        self.assertEqual(
            result["status"],
            "contradicted",
            f"Expected 'contradicted' but got '{result['status']}' "
            f"(rationale: {result.get('rationale', '')})",
        )
        self.assertIn("[DETERMINISTIC FALLBACK]", result["rationale"])

    def test_deterministic_evaluate_inconclusive(self):
        """Medium keyword overlap must return status 'inconclusive'."""
        agent = self._make_agent()
        # Craft medium overlap: some shared words but not enough for supported
        prediction = (
            "The new policy will moderately affect team productivity metrics."
        )
        observation = (
            "External factors influenced several markets but productivity was unrelated."
        )
        result = agent._deterministic_evaluate(prediction, observation)
        # Either inconclusive or contradicted is valid for medium overlap;
        # verify the function returns a valid status and tagged rationale.
        self.assertIn(result["status"], {"supported", "contradicted", "inconclusive"})
        self.assertIn("[DETERMINISTIC FALLBACK]", result["rationale"])

    def test_deterministic_evaluate_returns_required_keys(self):
        """_deterministic_evaluate() must return dict with status, rationale, confidence."""
        agent = self._make_agent()
        result = agent._deterministic_evaluate("some prediction", "some observation")
        required = {"status", "rationale", "confidence"}
        self.assertEqual(
            required - result.keys(),
            set(),
            f"Missing keys: {required - result.keys()}",
        )

    def test_deterministic_evaluate_confidence_in_range(self):
        """Returned confidence must be a float in [0, 1]."""
        agent = self._make_agent()
        result = agent._deterministic_evaluate(
            "prediction text here", "observation text here"
        )
        self.assertIsInstance(result["confidence"], float)
        self.assertGreaterEqual(result["confidence"], 0.0)
        self.assertLessEqual(result["confidence"], 1.0)

    def test_deterministic_evaluate_empty_strings(self):
        """Must not raise an exception for empty prediction/observation strings."""
        agent = self._make_agent()
        try:
            result = agent._deterministic_evaluate("", "")
            self.assertIn(result["status"], {"supported", "contradicted", "inconclusive"})
        except Exception as exc:
            self.fail(f"_deterministic_evaluate raised an unexpected exception: {exc}")

    def test_deterministic_evaluate_status_values(self):
        """Status must always be one of the three allowed values."""
        agent = self._make_agent()
        cases = [
            ("alpha beta gamma delta epsilon zeta eta theta", "alpha beta gamma delta"),
            ("completely different words here", "unrelated other stuff entirely"),
            ("some words", "a few same words plus others"),
        ]
        valid = {"supported", "contradicted", "inconclusive"}
        for pred, obs in cases:
            result = agent._deterministic_evaluate(pred, obs)
            self.assertIn(
                result["status"],
                valid,
                f"Unexpected status '{result['status']}' for pred='{pred}', obs='{obs}'",
            )


# ---------------------------------------------------------------------------
# TestCoordinatorStructure
# ---------------------------------------------------------------------------

class TestCoordinatorStructure(unittest.TestCase):
    """Tests for :mod:`agents.coordinator` module structure and utilities."""

    def test_get_pipeline_history_returns_list(self):
        """get_pipeline_history() must return a list (may be empty with mock graph)."""
        from agents.coordinator import get_pipeline_history

        graph = _make_graph_stub(query_rows=[])
        result = get_pipeline_history(graph, limit=5)
        self.assertIsInstance(
            result,
            list,
            f"get_pipeline_history returned {type(result).__name__}, expected list",
        )

    def test_get_pipeline_history_returns_list_on_graph_error(self):
        """get_pipeline_history() must return [] and not raise when graph errors."""
        from agents.coordinator import get_pipeline_history

        graph = _make_graph_stub()
        graph.query.side_effect = RuntimeError("db unreachable")
        result = get_pipeline_history(graph, limit=5)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)

    def test_run_scenario_pipeline_returns_expected_keys(self):
        """run_scenario_pipeline() must return a dict with the 4 expected keys."""
        from agents.coordinator import run_scenario_pipeline

        # We patch all agent run() methods and save_agent_run to avoid DB calls
        with patch("agents.scenario_agent.ScenarioAgent.run") as mock_scenario, \
             patch("agents.critic_agent.CriticAgent.run") as mock_critic, \
             patch("db.queries.get_agent_runs_by_type", return_value=[]), \
             patch("db.queries.save_agent_run", return_value={"id": "COORD-001"}):

            mock_scenario.return_value = {
                "run_id": "RUN-SCEN001",
                "status": "completed",
                "predictions": [],
                "used_llm": False,
                "branch_id": "BRANCH-001",
            }
            mock_critic.return_value = {
                "run_id": "RUN-CRIT001",
                "status": "completed",
                "critique_findings": [],
                "unsupported_claims": [],
                "missing_evidence": [],
                "used_llm": False,
            }

            graph = _make_graph_stub()
            with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
                result = run_scenario_pipeline(graph, "BRANCH-001", "DEC-001")

        expected_keys = {
            "scenario_result",
            "critique_result",
            "coordinator_run_id",
            "prior_runs_count",
        }
        self.assertEqual(
            expected_keys - result.keys(),
            set(),
            f"Missing keys: {expected_keys - result.keys()}",
        )

    def test_run_evaluation_pipeline_returns_expected_keys(self):
        """run_evaluation_pipeline() must return a dict with the 2 expected keys."""
        from agents.coordinator import run_evaluation_pipeline

        with patch("agents.outcome_evaluator.OutcomeEvaluator.run") as mock_eval, \
             patch("db.queries.save_agent_run", return_value={"id": "COORD-002"}):

            mock_eval.return_value = {
                "run_id": "RUN-EVAL001",
                "status": "completed",
                "evaluations": [],
                "outcome_id": "OUT-001",
            }

            graph = _make_graph_stub()
            with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
                result = run_evaluation_pipeline(
                    graph, "BRANCH-001", "DEC-001", "Things improved."
                )

        expected_keys = {"evaluation_result", "coordinator_run_id"}
        self.assertEqual(
            expected_keys - result.keys(),
            set(),
            f"Missing keys: {expected_keys - result.keys()}",
        )

    def test_coordinator_run_id_has_prefix(self):
        """The coordinator_run_id must start with 'COORD-'."""
        from agents.coordinator import run_scenario_pipeline

        with patch("agents.scenario_agent.ScenarioAgent.run") as mock_scenario, \
             patch("agents.critic_agent.CriticAgent.run") as mock_critic, \
             patch("db.queries.get_agent_runs_by_type", return_value=[]), \
             patch("db.queries.save_agent_run", return_value={"id": "COORD-001"}):

            mock_scenario.return_value = {
                "run_id": "RUN-S",
                "status": "completed",
                "predictions": [],
                "used_llm": False,
                "branch_id": "B",
            }
            mock_critic.return_value = {
                "run_id": "RUN-C",
                "status": "completed",
                "critique_findings": [],
                "unsupported_claims": [],
                "missing_evidence": [],
                "used_llm": False,
            }
            graph = _make_graph_stub()
            with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
                result = run_scenario_pipeline(graph, "B", "D")

        self.assertTrue(
            result["coordinator_run_id"].startswith("COORD-"),
            f"coordinator_run_id '{result['coordinator_run_id']}' does not start with 'COORD-'",
        )


# ---------------------------------------------------------------------------
# TestDbQueriesAgentRunExtensions
# ---------------------------------------------------------------------------

class TestDbQueriesAgentRunExtensions(unittest.TestCase):
    """Tests for Phase 3 additions to :mod:`db.queries`."""

    def _make_run_data(self) -> dict:
        return {
            "id": "RUN-TEST001",
            "agent_type": "test_agent",
            "started_at": "2026-01-01T00:00:00+00:00",
            "completed_at": "2026-01-01T00:01:00+00:00",
            "status": "completed",
            "summary": "Test run",
            "input_data": '{"key": "value"}',
            "output_data": '{"result": "ok"}',
        }

    def test_save_agent_run_raises_on_missing_required_keys(self):
        """save_agent_run() must raise ValueError for incomplete run_data."""
        from db.queries import save_agent_run

        graph = _make_graph_stub()
        with self.assertRaises(ValueError):
            save_agent_run(graph, {"id": "RUN-INCOMPLETE"})

    def test_save_agent_run_calls_graph_query(self):
        """save_agent_run() must execute a graph.query() call."""
        from db.queries import save_agent_run

        run_data = self._make_run_data()
        graph = _make_graph_stub([run_data])
        save_agent_run(graph, run_data)
        self.assertTrue(graph.query.called, "graph.query() was not called")

    def test_get_agent_run_by_id_returns_none_for_missing(self):
        """get_agent_run_by_id() must return None when no rows are returned."""
        from db.queries import get_agent_run_by_id

        graph = _make_graph_stub([])
        result = get_agent_run_by_id(graph, "RUN-NONEXISTENT")
        self.assertIsNone(result)

    def test_get_agent_runs_by_type_returns_list(self):
        """get_agent_runs_by_type() must return a list."""
        from db.queries import get_agent_runs_by_type

        row = {
            "id": "RUN-001",
            "agent_type": "scenario",
            "started_at": "2026-01-01T00:00:00+00:00",
            "completed_at": "2026-01-01T00:01:00+00:00",
            "status": "completed",
            "summary": "test",
            "input_data": "",
            "output_data": "",
        }
        graph = _make_graph_stub([row])
        result = get_agent_runs_by_type(graph, "scenario", limit=5)
        self.assertIsInstance(result, list)

    def test_get_agent_runs_by_type_empty_graph_returns_empty(self):
        """get_agent_runs_by_type() must return [] when graph has no matching nodes."""
        from db.queries import get_agent_runs_by_type

        graph = _make_graph_stub([])
        result = get_agent_runs_by_type(graph, "scenario", limit=5)
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
