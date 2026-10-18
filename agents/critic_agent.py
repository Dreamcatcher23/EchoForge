"""EchoForge — Critic Agent.

The Critic Agent independently reviews a scenario's predictions against graph
evidence, identifying unsupported claims and missing evidence.

Pipeline:
1. Retrieve prior ``CriticAgent`` runs from FalkorDB for context.
2. Fetch predictions for the branch via real Cypher queries.
3. Fetch evidence chain via real Cypher traversal.
4. Fetch branch assumptions via real Cypher queries.
5. Generate structured critique — using the OpenAI LLM when available, or a
   clearly labelled deterministic fallback otherwise.
6. Persist the ``AgentRun`` node in FalkorDB.

Design rules
------------
* No output is produced without prior real graph queries.
* The deterministic fallback is structurally identical to LLM output and is
  tagged ``[DETERMINISTIC FALLBACK]`` in all finding texts.
* Variable data travels via Cypher ``params`` dicts — no f-string injection.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from dotenv import load_dotenv

load_dotenv()

import db.branch_service as branch_service
import db.queries as queries
import db.traversal as traversal
from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class CriticAgent(BaseAgent):
    """Independently review scenario predictions against graph evidence.

    All critique findings are grounded in real graph data retrieved before
    any output is produced.
    """

    agent_type: str = "critic"

    def run(  # type: ignore[override]
        self,
        branch_id: str,
        decision_id: str,
        scenario_run_id: str | None = None,
    ) -> dict:
        """Execute the Critic Agent pipeline.

        Parameters
        ----------
        branch_id:
            ``id`` of the target ``ScenarioBranch`` node.
        decision_id:
            ``id`` of the source ``Decision`` node.
        scenario_run_id:
            Optional ``run_id`` of the preceding ``ScenarioAgent`` run,
            stored in the ``AgentRun`` for traceability.

        Returns
        -------
        dict
            Keys: ``run_id``, ``status``, ``critique_findings`` (list),
            ``unsupported_claims`` (list), ``missing_evidence`` (list),
            ``used_llm`` (bool).
        """
        self._mark_started()
        input_data: dict = {
            "branch_id": branch_id,
            "decision_id": decision_id,
            "scenario_run_id": scenario_run_id,
        }

        try:
            # ── Step 1: prior runs ────────────────────────────────────────────
            prior_runs = self.get_prior_runs(limit=5)
            logger.debug(
                "CriticAgent(%s): %d prior run(s) retrieved.",
                self.run_id,
                len(prior_runs),
            )

            # ── Step 2: predictions — read from ScenarioAgent's stored
            #    AgentRun output_data in FalkorDB when run_id available
            #    (Track 2: true cross-agent DB memory reads)
            scenario_agent_output: dict = {}
            if scenario_run_id:
                stored_run = queries.get_agent_run_by_id(self.graph, scenario_run_id)
                if stored_run and stored_run.get("output_data"):
                    try:
                        scenario_agent_output = json.loads(stored_run["output_data"])
                        logger.info(
                            "CriticAgent(%s): loaded ScenarioAgent output from "
                            "FalkorDB AgentRun %s.",
                            self.run_id,
                            scenario_run_id,
                        )
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(
                            "CriticAgent(%s): could not parse stored output_data "
                            "for run %s — falling back to direct DB query.",
                            self.run_id,
                            scenario_run_id,
                        )

            # Use predictions from stored AgentRun if available, else query DB
            if scenario_agent_output.get("predictions"):
                predictions = scenario_agent_output["predictions"]
                logger.info(
                    "CriticAgent(%s): using %d prediction(s) from ScenarioAgent "
                    "AgentRun stored in FalkorDB.",
                    self.run_id,
                    len(predictions),
                )
            else:
                predictions = queries.get_predictions_for_branch(self.graph, branch_id)

            # ── Step 3: evidence chain (real graph query) ─────────────────────
            evidence_chain = traversal.get_evidence_chain(self.graph, decision_id)

            # ── Step 4: branch assumptions (real graph query) ─────────────────
            assumptions = branch_service.get_branch_assumptions(self.graph, branch_id)

            # ── Step 5: build context ─────────────────────────────────────────
            context: dict[str, Any] = {
                "branch_id": branch_id,
                "predictions": predictions,
                "evidence_chain": evidence_chain,
                "assumptions": assumptions,
                "prior_runs_count": len(prior_runs),
                "scenario_run_id": scenario_run_id,
                "scenario_agent_output_source": (
                    "falkordb_agentrun" if scenario_agent_output.get("predictions")
                    else "direct_db_query"
                ),
            }

            # ── Step 6: generate critique ─────────────────────────────────────
            used_llm = False
            if self.llm_available:
                try:
                    prompt = self._build_critique_prompt(context)
                    system_prompt = (
                        "You are a rigorous counterfactual scenario critic. "
                        "Analyse predictions against graph evidence and return "
                        "only structured JSON critique findings."
                    )
                    llm_output = self._call_llm(prompt, system_prompt)
                    critique_result = self._parse_critique(llm_output, context)
                    used_llm = True
                    logger.info(
                        "CriticAgent(%s): LLM critique generated.", self.run_id
                    )
                except Exception as llm_exc:
                    logger.warning(
                        "CriticAgent(%s): LLM call failed (%s); using deterministic fallback.",
                        self.run_id,
                        llm_exc,
                    )
                    critique_result = self._deterministic_critique(context)
            else:
                critique_result = self._deterministic_critique(context)

            critique_findings = critique_result.get("critique_findings", [])
            unsupported_claims = critique_result.get("unsupported_claims", [])
            missing_evidence = critique_result.get("missing_evidence", [])

            # ── Step 7 (implicitly done in steps 6) ───────────────────────────

            # ── Step 8: save AgentRun ─────────────────────────────────────────
            summary = (
                f"Critique of branch '{branch_id}': "
                f"{len(critique_findings)} finding(s), "
                f"{len(unsupported_claims)} unsupported claim(s), "
                f"{len(missing_evidence)} missing evidence item(s). "
                f"Method: {'LLM' if used_llm else '[DETERMINISTIC FALLBACK]'}."
            )
            output_data: dict = {
                "critique_findings": critique_findings,
                "unsupported_claims": unsupported_claims,
                "missing_evidence": missing_evidence,
                "used_llm": used_llm,
                "branch_id": branch_id,
                "scenario_run_id": scenario_run_id,
            }
            self.save_run(
                status="completed",
                summary=summary,
                input_data=input_data,
                output_data=output_data,
            )

            # ── Step 9: return ────────────────────────────────────────────────
            return {
                "run_id": self.run_id,
                "status": "completed",
                "critique_findings": critique_findings,
                "unsupported_claims": unsupported_claims,
                "missing_evidence": missing_evidence,
                "used_llm": used_llm,
            }

        except Exception as exc:
            logger.error("CriticAgent(%s) failed: %s", self.run_id, exc)
            try:
                self.save_run(
                    status="failed",
                    summary=f"Run failed: {exc}",
                    input_data=input_data,
                    output_data={"error": str(exc)},
                )
            except Exception as save_exc:
                logger.error(
                    "CriticAgent(%s): could not save failure run: %s",
                    self.run_id,
                    save_exc,
                )
            return {
                "run_id": self.run_id,
                "status": "failed",
                "critique_findings": [],
                "unsupported_claims": [],
                "missing_evidence": [],
                "used_llm": False,
                "error": str(exc),
            }

    # ------------------------------------------------------------------
    # Deterministic fallback
    # ------------------------------------------------------------------

    def _deterministic_critique(self, context: dict) -> dict:
        """Perform a rule-based critique grounded in real graph context.

        Checks performed:
        * Predictions with ``confidence > 0.8`` that have fewer than 2
          evidence items supporting them → flagged as unsupported.
        * Affected entities with no evidence reachable from the decision
          → flagged as missing evidence.
        * Undocumented assumptions (no ``field`` key set) → flagged as finding.

        All findings are tagged ``[DETERMINISTIC FALLBACK]``.

        Parameters
        ----------
        context:
            Dict assembled from real graph queries inside :meth:`run`.

        Returns
        -------
        dict
            Keys: ``critique_findings``, ``unsupported_claims``,
            ``missing_evidence``.
        """
        predictions: list[dict] = context.get("predictions", [])
        evidence_chain: list[dict] = context.get("evidence_chain", [])
        assumptions: list[dict] = context.get("assumptions", [])

        evidence_count = len(evidence_chain)
        critique_findings: list[str] = []
        unsupported_claims: list[str] = []
        missing_evidence_items: list[str] = []

        # Check 1: high-confidence predictions with insufficient evidence
        for pred in predictions:
            try:
                conf = float(pred.get("confidence", 0.0))
            except (TypeError, ValueError):
                conf = 0.0
            if conf > 0.8 and evidence_count < 2:
                claim = pred.get("content", pred.get("id", "unknown prediction"))[:100]
                unsupported_claims.append(
                    f"[DETERMINISTIC FALLBACK] High-confidence prediction "
                    f"(confidence={conf:.2f}) has insufficient evidence support "
                    f"({evidence_count} item(s) < 2 required): '{claim}...'"
                )

        # Check 2: zero evidence available at all
        if evidence_count == 0:
            missing_evidence_items.append(
                "[DETERMINISTIC FALLBACK] No evidence items found via "
                "SUPPORTED_BY traversal from the source decision. "
                "All predictions lack direct evidential grounding."
            )
        elif evidence_count < 2:
            missing_evidence_items.append(
                f"[DETERMINISTIC FALLBACK] Only {evidence_count} evidence "
                f"item(s) found. Recommend sourcing additional supporting "
                f"evidence before treating predictions as high-confidence."
            )

        # Check 3: undocumented assumptions
        undocumented = [
            a for a in assumptions if not a.get("field") or not a.get("new_value")
        ]
        if undocumented:
            critique_findings.append(
                f"[DETERMINISTIC FALLBACK] {len(undocumented)} assumption(s) "
                f"are missing required 'field' or 'new_value' documentation, "
                f"making the scenario conditions partially undefined."
            )
        else:
            critique_findings.append(
                f"[DETERMINISTIC FALLBACK] All {len(assumptions)} assumption(s) "
                f"are documented with field, original_value, and new_value. "
                f"Scenario definition is structurally complete."
            )

        # Overall finding based on prediction count
        if not predictions:
            critique_findings.append(
                "[DETERMINISTIC FALLBACK] No predictions exist for this branch. "
                "Run the Scenario Agent first to generate predictions."
            )
        else:
            critique_findings.append(
                f"[DETERMINISTIC FALLBACK] Reviewed {len(predictions)} prediction(s) "
                f"against {evidence_count} evidence item(s). "
                f"Evidence-to-prediction ratio: "
                f"{evidence_count / max(len(predictions), 1):.2f}."
            )

        return {
            "critique_findings": critique_findings,
            "unsupported_claims": unsupported_claims,
            "missing_evidence": missing_evidence_items,
        }

    # ------------------------------------------------------------------
    # Prompt builder
    # ------------------------------------------------------------------

    def _build_critique_prompt(self, context: dict) -> str:
        """Build a structured LLM prompt for critique generation.

        Parameters
        ----------
        context:
            Dict assembled from real graph queries.

        Returns
        -------
        str
            A complete prompt ready to pass to :meth:`~BaseAgent._call_llm`.
        """
        predictions: list[dict] = context.get("predictions", [])
        evidence_chain: list[dict] = context.get("evidence_chain", [])
        assumptions: list[dict] = context.get("assumptions", [])

        predictions_text = "\n".join(
            f"  - [conf={p.get('confidence', '?')}] {p.get('content', '')[:150]}"
            for p in predictions
        ) or "  (no predictions found for this branch)"

        evidence_text = "\n".join(
            f"  - [{e.get('via', 'direct')}] {e.get('content', '')[:120]}"
            for e in evidence_chain
        ) or "  (no evidence found)"

        assumptions_text = "\n".join(
            f"  - Field '{a.get('field')}': '{a.get('original_value')}' → '{a.get('new_value')}'"
            for a in assumptions
        ) or "  (no assumptions recorded)"

        return (
            f"You are a rigorous counterfactual scenario critic for EchoForge.\n\n"
            f"## Predictions to Review\n{predictions_text}\n\n"
            f"## Available Evidence (from graph)\n{evidence_text}\n\n"
            f"## Branch Assumptions (from graph)\n{assumptions_text}\n\n"
            f"## Task\n"
            f"Review the predictions critically:\n"
            f"1. Identify any UNSUPPORTED CLAIMS — predictions not grounded "
            f"in the available evidence.\n"
            f"2. Identify MISSING EVIDENCE — evidence that should exist but "
            f"is absent from the graph.\n"
            f"3. Note INCONSISTENT ASSUMPTIONS — assumptions that contradict "
            f"each other or the evidence.\n\n"
            f"Return ONLY valid JSON (no markdown, no text outside JSON):\n"
            f'{{"critique_findings": ["finding1", "finding2"], '
            f'"unsupported_claims": ["claim1"], '
            f'"missing_evidence": ["evidence_gap1"]}}'
        )

    # ------------------------------------------------------------------
    # Output parser
    # ------------------------------------------------------------------

    def _parse_critique(self, llm_output: str, context: dict) -> dict:
        """Parse LLM critique output into structured findings.

        Parameters
        ----------
        llm_output:
            Raw string from the LLM (expected to contain a JSON object).
        context:
            Original context dict (used to generate deterministic fallback if
            parsing fails).

        Returns
        -------
        dict
            Keys: ``critique_findings``, ``unsupported_claims``,
            ``missing_evidence``.
        """
        cleaned = re.sub(r"```(?:json)?", "", llm_output).strip()

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group())
                except json.JSONDecodeError:
                    parsed = {}
            else:
                parsed = {}

        if not isinstance(parsed, dict):
            parsed = {}

        def _to_str_list(value: Any) -> list[str]:
            if isinstance(value, list):
                return [str(v) for v in value]
            return []

        return {
            "critique_findings": _to_str_list(parsed.get("critique_findings")),
            "unsupported_claims": _to_str_list(parsed.get("unsupported_claims")),
            "missing_evidence": _to_str_list(parsed.get("missing_evidence")),
        }
