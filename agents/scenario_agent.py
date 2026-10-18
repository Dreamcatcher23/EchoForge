"""EchoForge — Scenario Agent.

For a given ``ScenarioBranch`` the Scenario Agent:

1. Retrieves prior ``ScenarioAgent`` runs from FalkorDB for context.
2. Fetches branch detail, affected entities, and evidence chain via real
   Cypher queries.
3. Generates predicted alternative outcomes — using the OpenAI LLM when
   available, or a clearly labelled deterministic fallback otherwise.
4. Persists each ``Prediction`` node to FalkorDB.
5. Records the complete ``AgentRun`` node in FalkorDB.

Design rules
------------
* No agent output is produced without first executing real graph queries.
* The deterministic fallback is structurally identical to LLM output and
  every prediction it produces is tagged ``[DETERMINISTIC FALLBACK]``.
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


class ScenarioAgent(BaseAgent):
    """Generate predicted alternative outcomes for a ScenarioBranch.

    All predictions are grounded in real graph data retrieved before any
    output is produced.
    """

    agent_type: str = "scenario"

    def run(self, branch_id: str, decision_id: str) -> dict:  # type: ignore[override]
        """Execute the Scenario Agent pipeline.

        Parameters
        ----------
        branch_id:
            ``id`` of the target ``ScenarioBranch`` node.
        decision_id:
            ``id`` of the source ``Decision`` node.

        Returns
        -------
        dict
            Keys: ``run_id``, ``status``, ``predictions`` (list of dicts),
            ``used_llm`` (bool), ``branch_id``.
        """
        self._mark_started()
        input_data: dict = {"branch_id": branch_id, "decision_id": decision_id}

        try:
            # ── Step 1: retrieve prior runs for context ──────────────────────
            prior_runs = self.get_prior_runs(limit=5)
            logger.debug(
                "ScenarioAgent(%s): %d prior run(s) retrieved.",
                self.run_id,
                len(prior_runs),
            )

            # ── Step 2: branch detail (real graph query) ─────────────────────
            branch_detail = branch_service.get_branch_detail(self.graph, branch_id)
            if not branch_detail.get("branch"):
                raise ValueError(
                    f"ScenarioBranch '{branch_id}' not found in the graph."
                )

            # ── Step 3: affected entities (real graph query) ─────────────────
            affected_entities = traversal.get_affected_entities(
                self.graph, decision_id
            )

            # ── Step 4: evidence chain (real graph query) ────────────────────
            evidence_chain = traversal.get_evidence_chain(self.graph, decision_id)

            # ── Step 5: build context ─────────────────────────────────────────
            context: dict[str, Any] = {
                "branch": branch_detail.get("branch", {}),
                "source_decision": branch_detail.get("source_decision"),
                "hypothetical_decisions": branch_detail.get(
                    "hypothetical_decisions", []
                ),
                "affected_entities": affected_entities,
                "evidence_chain": evidence_chain,
                "prior_runs_count": len(prior_runs),
            }

            # ── Steps 6-7: generate predictions ──────────────────────────────
            used_llm = False
            if self.llm_available:
                try:
                    prompt = self._build_prompt(context)
                    system_prompt = (
                        "You are an expert counterfactual scenario analyst. "
                        "Analyse the provided graph context and generate exactly "
                        "3 predictions in the requested JSON format."
                    )
                    llm_output = self._call_llm(prompt, system_prompt)
                    raw_predictions = self._parse_predictions(llm_output, branch_id)
                    used_llm = True
                    logger.info(
                        "ScenarioAgent(%s): LLM predictions generated.", self.run_id
                    )
                except Exception as llm_exc:
                    logger.warning(
                        "ScenarioAgent(%s): LLM call failed (%s); using deterministic fallback.",
                        self.run_id,
                        llm_exc,
                    )
                    raw_predictions = self._deterministic_scenario(context)
            else:
                raw_predictions = self._deterministic_scenario(context)

            # ── Step 8: persist predictions to FalkorDB ───────────────────────
            saved_predictions: list[dict] = []
            for pred in raw_predictions:
                try:
                    saved = queries.create_prediction(
                        self.graph,
                        {
                            "content": pred["content"],
                            "confidence": pred["confidence"],
                            "branch_id": branch_id,
                        },
                    )
                    saved["rationale"] = pred.get("rationale", "")
                    saved_predictions.append(saved)
                except Exception as pred_exc:
                    logger.error(
                        "ScenarioAgent(%s): failed to persist prediction: %s",
                        self.run_id,
                        pred_exc,
                    )

            # ── Step 9: save AgentRun ─────────────────────────────────────────
            summary = (
                f"Generated {len(saved_predictions)} prediction(s) for branch "
                f"'{branch_id}' using {'LLM' if used_llm else '[DETERMINISTIC FALLBACK]'}."
            )
            output_data: dict = {
                "predictions": saved_predictions,
                "used_llm": used_llm,
                "branch_id": branch_id,
            }
            self.save_run(
                status="completed",
                summary=summary,
                input_data=input_data,
                output_data=output_data,
            )

            # ── Step 10: return ───────────────────────────────────────────────
            return {
                "run_id": self.run_id,
                "status": "completed",
                "predictions": saved_predictions,
                "used_llm": used_llm,
                "branch_id": branch_id,
            }

        except Exception as exc:
            logger.error("ScenarioAgent(%s) failed: %s", self.run_id, exc)
            error_summary = f"Run failed: {exc}"
            try:
                self.save_run(
                    status="failed",
                    summary=error_summary,
                    input_data=input_data,
                    output_data={"error": str(exc)},
                )
            except Exception as save_exc:
                logger.error(
                    "ScenarioAgent(%s): could not save failure run: %s",
                    self.run_id,
                    save_exc,
                )
            return {
                "run_id": self.run_id,
                "status": "failed",
                "predictions": [],
                "used_llm": False,
                "branch_id": branch_id,
                "error": str(exc),
            }

    # ------------------------------------------------------------------
    # Deterministic fallback
    # ------------------------------------------------------------------

    def _deterministic_scenario(self, context: dict) -> list[dict]:
        """Generate 3 deterministic predictions grounded in real graph context.

        Predictions are derived from:
        * The number of affected entities retrieved from the graph.
        * The number of evidence items retrieved from the graph.
        * The branch assumptions (changed fields).

        Every prediction is labelled ``[DETERMINISTIC FALLBACK]``.

        Parameters
        ----------
        context:
            Dict assembled from real graph queries inside :meth:`run`.

        Returns
        -------
        list[dict]
            Exactly 3 prediction dicts, each with ``content``, ``confidence``,
            and ``rationale`` keys.
        """
        branch = context.get("branch", {})
        branch_name = branch.get("name", "Unknown Branch")
        affected_entities = context.get("affected_entities", [])
        evidence_chain = context.get("evidence_chain", [])
        hyp_decisions = context.get("hypothetical_decisions", [])

        entity_count = len(affected_entities)
        evidence_count = len(evidence_chain)
        assumption_count = len(hyp_decisions)

        # Confidence scaled by evidence availability
        base_confidence = min(0.5 + evidence_count * 0.05, 0.85)
        low_confidence = max(0.2, base_confidence - 0.25)
        med_confidence = base_confidence
        high_confidence = min(base_confidence + 0.1, 0.9)

        entity_names = [
            str(e.get("name") or e.get("id") or "entity") for e in affected_entities[:3]
        ]
        entity_str = (
            ", ".join(entity_names) if entity_names else "no directly affected entities"
        )

        assumption_fields = [
            str(h.get("field") or h.get("title") or h.get("id") or "unknown")
            for h in hyp_decisions[:3]
        ]
        assumption_str = (
            ", ".join(assumption_fields) if assumption_fields else "no changed assumptions"
        )

        predictions: list[dict] = [
            {
                "content": (
                    f"[DETERMINISTIC FALLBACK] Branch '{branch_name}': "
                    f"Changing {assumption_str} will directly impact {entity_count} "
                    f"entity/entities ({entity_str}), causing measurable disruption "
                    f"to at least {max(1, entity_count // 2)} downstream dependencies."
                ),
                "confidence": round(high_confidence, 2),
                "rationale": (
                    f"Derived from {entity_count} affected entities and "
                    f"{evidence_count} evidence items found in graph traversal. "
                    f"High entity count indicates broad impact."
                ),
            },
            {
                "content": (
                    f"[DETERMINISTIC FALLBACK] Branch '{branch_name}': "
                    f"With {assumption_count} assumption change(s) ({assumption_str}), "
                    f"the scenario will produce an outcome diverging significantly "
                    f"from the actual historical decision within the first affected cycle."
                ),
                "confidence": round(med_confidence, 2),
                "rationale": (
                    f"Based on {assumption_count} changed assumption(s) linked via "
                    f"CHANGES relationships. Each assumption change introduces a "
                    f"compounding divergence factor."
                ),
            },
            {
                "content": (
                    f"[DETERMINISTIC FALLBACK] Branch '{branch_name}': "
                    f"Evidence availability ({evidence_count} items) is "
                    f"{'sufficient' if evidence_count >= 2 else 'insufficient'} "
                    f"to fully validate the scenario; the predicted outcome carries "
                    f"a residual uncertainty factor proportional to unsupported assumptions."
                ),
                "confidence": round(low_confidence, 2),
                "rationale": (
                    f"Only {evidence_count} evidence item(s) found via SUPPORTED_BY "
                    f"traversal. Confidence inversely weighted by evidence gaps."
                ),
            },
        ]
        return predictions

    # ------------------------------------------------------------------
    # Prompt builder
    # ------------------------------------------------------------------

    def _build_prompt(self, context: dict) -> str:
        """Build a structured LLM prompt from graph-retrieved context.

        Parameters
        ----------
        context:
            Dict assembled from real graph queries inside :meth:`run`.

        Returns
        -------
        str
            A complete prompt ready to pass to :meth:`~BaseAgent._call_llm`.
        """
        branch = context.get("branch", {})
        source_decision = context.get("source_decision") or {}
        hyp_decisions = context.get("hypothetical_decisions", [])
        affected_entities = context.get("affected_entities", [])
        evidence_chain = context.get("evidence_chain", [])
        prior_runs_count = context.get("prior_runs_count", 0)

        assumptions_text = "\n".join(
            f"  - Field '{h.get('field') or h.get('title') or h.get('id', 'unknown')}': "
            f"'{h.get('original_value', 'N/A')}' -> '{h.get('new_value', 'N/A')}'"
            for h in hyp_decisions
        ) or "  (no changed assumptions recorded)"

        entities_text = "\n".join(
            f"  - [{e.get('label', 'Node')}] "
            f"{str(e.get('name') or e.get('id') or 'unknown')} "
            f"(depth={e.get('depth', '?')})"
            for e in affected_entities
        ) or "  (no directly affected entities found)"

        evidence_text = "\n".join(
            f"  - [{e.get('via', 'direct')}] {e.get('content', '')[:120]}"
            for e in evidence_chain
        ) or "  (no evidence items found)"

        return (
            f"You are analysing a counterfactual scenario branch in the EchoForge "
            f"Counterfactual Decision Lab.\n\n"
            f"## Branch\n"
            f"Name: {branch.get('name', 'N/A')}\n"
            f"Description: {branch.get('description', 'N/A')}\n"
            f"Status: {branch.get('status', 'N/A')}\n\n"
            f"## Source Decision\n"
            f"ID: {source_decision.get('id', 'N/A')}\n"
            f"Title: {source_decision.get('title', 'N/A')}\n"
            f"Description: {source_decision.get('description', 'N/A')}\n\n"
            f"## Changed Assumptions\n{assumptions_text}\n\n"
            f"## Affected Entities (from graph traversal)\n{entities_text}\n\n"
            f"## Supporting Evidence (from graph traversal)\n{evidence_text}\n\n"
            f"## Context\n"
            f"Prior scenario agent runs: {prior_runs_count}\n\n"
            f"## Task\n"
            f"Generate exactly 3 predictions for what would happen in this "
            f"counterfactual scenario. Each prediction must be grounded in the "
            f"graph data above.\n\n"
            f"Return ONLY valid JSON in this exact format (no markdown, no "
            f"explanation outside the JSON):\n"
            f'[{{"content": "...", "confidence": 0.7, "rationale": "..."}}, '
            f'{{"content": "...", "confidence": 0.6, "rationale": "..."}}, '
            f'{{"content": "...", "confidence": 0.5, "rationale": "..."}}]'
        )

    # ------------------------------------------------------------------
    # Output parser
    # ------------------------------------------------------------------

    def _parse_predictions(self, llm_output: str, branch_id: str) -> list[dict]:
        """Parse LLM or fallback output into a list of prediction dicts.

        Parameters
        ----------
        llm_output:
            Raw string from the LLM (expected to contain a JSON array).
        branch_id:
            Passed through to each prediction dict for traceability.

        Returns
        -------
        list[dict]
            Each dict has ``content``, ``confidence`` (float in [0, 1]),
            ``rationale``, and ``branch_id``.

        Notes
        -----
        Confidence values outside [0, 1] are clamped.  If JSON parsing
        fails a single fallback prediction is returned.
        """
        # Strip markdown code fences if present
        cleaned = re.sub(r"```(?:json)?", "", llm_output).strip()

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            # Attempt to extract the first JSON array
            match = re.search(r"\[.*\]", cleaned, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group())
                except json.JSONDecodeError:
                    parsed = []
            else:
                parsed = []

        if not isinstance(parsed, list):
            parsed = []

        predictions: list[dict] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            try:
                confidence = float(item.get("confidence", 0.5))
            except (TypeError, ValueError):
                confidence = 0.5
            confidence = max(0.0, min(1.0, confidence))

            predictions.append(
                {
                    "content": str(item.get("content", "")),
                    "confidence": confidence,
                    "rationale": str(item.get("rationale", "")),
                    "branch_id": branch_id,
                }
            )

        # Guarantee at least one prediction
        if not predictions:
            predictions.append(
                {
                    "content": "[LLM OUTPUT UNPARSEABLE] No structured prediction extracted.",
                    "confidence": 0.1,
                    "rationale": "LLM returned output that could not be parsed as JSON.",
                    "branch_id": branch_id,
                }
            )

        return predictions
