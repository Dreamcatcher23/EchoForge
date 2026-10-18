"""EchoForge — Outcome Evaluator Agent.

The Outcome Evaluator compares recorded ``Prediction`` nodes against a
subsequently entered observation string, evaluating each prediction as
``supported``, ``contradicted``, or ``inconclusive``.

Pipeline:
1. Retrieve prior ``OutcomeEvaluator`` runs from FalkorDB for context.
2. Fetch all predictions for the branch via real Cypher queries.
3. Fetch actual outcomes already recorded in FalkorDB (if any).
4. For each prediction evaluate it against the observed outcome string —
   using the OpenAI LLM when available, or keyword-overlap scoring otherwise.
5. Create a single ``Outcome`` node in FalkorDB.
6. Link each ``Prediction`` to the ``Outcome`` via ``EVALUATED_AGAINST``.
7. Persist the ``AgentRun`` node in FalkorDB.

Design rules
------------
* No output is produced without prior real graph queries.
* The deterministic fallback uses keyword/phrase overlap scoring and is
  tagged ``[DETERMINISTIC FALLBACK]``.
* Variable data travels via Cypher ``params`` dicts — no f-string injection.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from dotenv import load_dotenv

load_dotenv()

import db.history as history
import db.queries as queries
from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class OutcomeEvaluator(BaseAgent):
    """Evaluate predictions against an observed outcome.

    All evaluations are grounded in real graph data retrieved before any
    output is produced.
    """

    agent_type: str = "outcome_evaluator"

    def run(  # type: ignore[override]
        self,
        branch_id: str,
        decision_id: str,
        observed_outcome: str,
    ) -> dict:
        """Execute the Outcome Evaluator pipeline.

        Parameters
        ----------
        branch_id:
            ``id`` of the target ``ScenarioBranch`` node.
        decision_id:
            ``id`` of the source ``Decision`` node.
        observed_outcome:
            Free-text description of what actually happened; compared
            semantically (LLM) or by keyword overlap (fallback) against each
            stored prediction.

        Returns
        -------
        dict
            Keys: ``run_id``, ``status``, ``evaluations`` (list of dicts),
            ``outcome_id`` (str).
        """
        self._mark_started()
        input_data: dict = {
            "branch_id": branch_id,
            "decision_id": decision_id,
            "observed_outcome": observed_outcome,
        }

        try:
            # ── Step 1: prior runs ────────────────────────────────────────────
            prior_runs = self.get_prior_runs(limit=5)
            logger.debug(
                "OutcomeEvaluator(%s): %d prior run(s) retrieved.",
                self.run_id,
                len(prior_runs),
            )

            # ── Step 2: predictions for the branch (real graph query) ─────────
            predictions = queries.get_predictions_for_branch(self.graph, branch_id)
            logger.debug(
                "OutcomeEvaluator(%s): %d prediction(s) found for branch '%s'.",
                self.run_id,
                len(predictions),
                branch_id,
            )

            # ── Step 3: actual outcomes (real graph query) ────────────────────
            actual_outcomes = history.get_actual_outcomes(self.graph)
            logger.debug(
                "OutcomeEvaluator(%s): %d actual outcome(s) in history.",
                self.run_id,
                len(actual_outcomes),
            )

            # ── Step 4: evaluate each prediction ─────────────────────────────
            evaluations: list[dict] = []
            for pred in predictions:
                pred_id = pred.get("id", "")
                pred_content = pred.get("content", "")

                if self.llm_available:
                    try:
                        eval_result = self._llm_evaluate(
                            pred_id, pred_content, observed_outcome
                        )
                    except Exception as llm_exc:
                        logger.warning(
                            "OutcomeEvaluator(%s): LLM eval failed for '%s' (%s); "
                            "using deterministic fallback.",
                            self.run_id,
                            pred_id,
                            llm_exc,
                        )
                        eval_result = self._deterministic_evaluate(
                            pred_content, observed_outcome
                        )
                        eval_result["prediction_id"] = pred_id
                else:
                    eval_result = self._deterministic_evaluate(
                        pred_content, observed_outcome
                    )
                    eval_result["prediction_id"] = pred_id

                evaluations.append(eval_result)

            # ── Step 5: create Outcome node in FalkorDB ───────────────────────
            outcome_node = queries.create_outcome(
                self.graph,
                {
                    "description": observed_outcome,
                    "branch_id": branch_id,
                },
            )
            outcome_id: str = outcome_node.get("id", "")

            # ── Step 6: link predictions to outcome ───────────────────────────
            for eval_item in evaluations:
                pred_id = eval_item.get("prediction_id", "")
                eval_status = eval_item.get("status", "inconclusive")
                if pred_id and outcome_id:
                    try:
                        queries.link_prediction_to_outcome(
                            self.graph, pred_id, outcome_id, eval_status
                        )
                    except Exception as link_exc:
                        logger.error(
                            "OutcomeEvaluator(%s): could not link '%s' to '%s': %s",
                            self.run_id,
                            pred_id,
                            outcome_id,
                            link_exc,
                        )

            # ── Step 7: save AgentRun ─────────────────────────────────────────
            supported = sum(
                1 for e in evaluations if e.get("status") == "supported"
            )
            contradicted = sum(
                1 for e in evaluations if e.get("status") == "contradicted"
            )
            summary = (
                f"Evaluated {len(predictions)} prediction(s) for branch '{branch_id}'. "
                f"Supported: {supported}, Contradicted: {contradicted}, "
                f"Inconclusive: {len(evaluations) - supported - contradicted}. "
                f"Outcome node: {outcome_id}."
            )
            output_data: dict = {
                "evaluations": evaluations,
                "outcome_id": outcome_id,
                "branch_id": branch_id,
            }
            self.save_run(
                status="completed",
                summary=summary,
                input_data=input_data,
                output_data=output_data,
            )

            # ── Step 8: return ────────────────────────────────────────────────
            return {
                "run_id": self.run_id,
                "status": "completed",
                "evaluations": evaluations,
                "outcome_id": outcome_id,
            }

        except Exception as exc:
            logger.error("OutcomeEvaluator(%s) failed: %s", self.run_id, exc)
            try:
                self.save_run(
                    status="failed",
                    summary=f"Run failed: {exc}",
                    input_data=input_data,
                    output_data={"error": str(exc)},
                )
            except Exception as save_exc:
                logger.error(
                    "OutcomeEvaluator(%s): could not save failure run: %s",
                    self.run_id,
                    save_exc,
                )
            return {
                "run_id": self.run_id,
                "status": "failed",
                "evaluations": [],
                "outcome_id": "",
                "error": str(exc),
            }

    # ------------------------------------------------------------------
    # LLM evaluation helper
    # ------------------------------------------------------------------

    def _llm_evaluate(
        self,
        prediction_id: str,
        prediction_content: str,
        observed_outcome: str,
    ) -> dict:
        """Use the LLM to semantically compare a prediction to the observation.

        Parameters
        ----------
        prediction_id:
            ``id`` of the Prediction node.
        prediction_content:
            Full text of the prediction.
        observed_outcome:
            Free-text observed outcome to compare against.

        Returns
        -------
        dict
            Keys: ``prediction_id``, ``status`` (``supported`` |
            ``contradicted`` | ``inconclusive``), ``rationale``,
            ``confidence``.
        """
        prompt = (
            f"Compare the following prediction against the observed outcome.\n\n"
            f"Prediction: {prediction_content}\n\n"
            f"Observed Outcome: {observed_outcome}\n\n"
            f"Evaluate whether the prediction is:\n"
            f"- 'supported': the observation confirms or is consistent with the prediction\n"
            f"- 'contradicted': the observation directly contradicts the prediction\n"
            f"- 'inconclusive': insufficient information to determine alignment\n\n"
            f"Return ONLY valid JSON (no markdown):\n"
            f'{{"prediction_id": "{prediction_id}", '
            f'"status": "supported|contradicted|inconclusive", '
            f'"rationale": "brief explanation", '
            f'"confidence": 0.8}}'
        )
        raw = self._call_llm(prompt)
        cleaned = re.sub(r"```(?:json)?", "", raw).strip()

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            parsed = json.loads(match.group()) if match else {}

        valid_statuses = {"supported", "contradicted", "inconclusive"}
        status = parsed.get("status", "inconclusive")
        if status not in valid_statuses:
            status = "inconclusive"

        try:
            confidence = float(parsed.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = 0.5

        return {
            "prediction_id": prediction_id,
            "status": status,
            "rationale": str(parsed.get("rationale", "")),
            "confidence": confidence,
        }

    # ------------------------------------------------------------------
    # Deterministic fallback
    # ------------------------------------------------------------------

    def _deterministic_evaluate(
        self,
        prediction_content: str,
        observed_outcome: str,
    ) -> dict:
        """Evaluate a prediction using keyword/phrase overlap scoring.

        Scoring rules:
        * overlap ratio > 30 %  → ``supported``
        * overlap ratio < 5 %   → ``contradicted``
        * otherwise             → ``inconclusive``

        All outputs are tagged ``[DETERMINISTIC FALLBACK]``.

        Parameters
        ----------
        prediction_content:
            Full text of the prediction.
        observed_outcome:
            Free-text observed outcome.

        Returns
        -------
        dict
            Keys: ``status``, ``rationale``, ``confidence``.
            ``prediction_id`` is added by the caller.
        """
        def _tokenize(text: str) -> set[str]:
            # Lowercase, split on non-alphanumeric, filter short tokens
            tokens = re.findall(r"[a-z0-9]{3,}", text.lower())
            return set(tokens)

        pred_tokens = _tokenize(prediction_content)
        obs_tokens = _tokenize(observed_outcome)

        if not pred_tokens or not obs_tokens:
            overlap_ratio = 0.0
        else:
            common = pred_tokens & obs_tokens
            # Jaccard-like: overlap / union
            overlap_ratio = len(common) / len(pred_tokens | obs_tokens)

        if overlap_ratio > 0.30:
            status = "supported"
            confidence = round(min(0.5 + overlap_ratio, 0.9), 2)
            rationale = (
                f"[DETERMINISTIC FALLBACK] Keyword overlap ratio={overlap_ratio:.2f} "
                f"(>{0.30:.2f} threshold). "
                f"Common terms: {sorted(pred_tokens & obs_tokens)[:5]}. "
                f"Prediction content aligns with observed outcome."
            )
        elif overlap_ratio < 0.05:
            status = "contradicted"
            confidence = round(max(0.5 - overlap_ratio * 2, 0.2), 2)
            rationale = (
                f"[DETERMINISTIC FALLBACK] Keyword overlap ratio={overlap_ratio:.2f} "
                f"(<{0.05:.2f} threshold). "
                f"Very few shared terms; prediction content does not align with "
                f"observed outcome."
            )
        else:
            status = "inconclusive"
            confidence = round(0.3 + overlap_ratio, 2)
            rationale = (
                f"[DETERMINISTIC FALLBACK] Keyword overlap ratio={overlap_ratio:.2f} "
                f"(between 0.05 and 0.30). "
                f"Partial alignment; insufficient to confirm or contradict prediction."
            )

        return {
            "status": status,
            "rationale": rationale,
            "confidence": confidence,
        }
