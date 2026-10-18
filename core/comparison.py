"""EchoForge — Comparison engine.

Produces structured diffs between an actual Decision and a hypothetical
ScenarioBranch, and formats them for Streamlit display panels.

This module is intentionally free of direct graph-write operations; it only
*reads* via ``db.queries``, ``db.history``, ``db.branch_service``, and
``db.traversal``.
"""

from __future__ import annotations

import logging

from db import queries as q
from db import history as h
from db import branch_service as bs
from db import traversal as t

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core comparison
# ---------------------------------------------------------------------------

def compare_decision_to_branch(
    graph,
    actual_decision_id: str,
    branch_id: str,
) -> dict:
    """Return a comprehensive comparison between an actual Decision and a branch.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    actual_decision_id:
        ``id`` of the ``is_actual=True`` Decision node.
    branch_id:
        ``id`` of the ScenarioBranch to compare against.

    Returns
    -------
    dict
        Structure::

            {
              "actual": {
                "decision": dict,
                "evidence": list[dict],
                "affected_entities": list[dict],
                "outcome": dict | None
              },
              "hypothetical": {
                "branch": dict,
                "changed_assumptions": list[dict],
                "affected_entities": list[dict],
                "predictions": list[dict]
              },
              "diff": {
                "added_impacts": list[dict],
                "removed_impacts": list[dict],
                "assumption_changes": list[dict],
                "evidence_gaps": list[dict]
              }
            }
    """
    # ---- Actual side --------------------------------------------------------
    decision = q.get_decision_by_id(graph, actual_decision_id) or {}
    evidence = q.get_decision_evidence(graph, actual_decision_id)
    actual_affected = t.get_affected_entities(graph, actual_decision_id)

    # Actual outcome (EVALUATED_AGAINST from Outcome -> Decision)
    outcome_cypher = (
        "MATCH (o:Outcome)-[:EVALUATED_AGAINST]->(d:Decision {id: $dec_id}) "
        "RETURN o.id AS id, o.description AS description, "
        "o.observed_at AS observed_at, o.is_actual AS is_actual "
        "LIMIT 1"
    )
    try:
        out_result = graph.query(outcome_cypher, {"dec_id": actual_decision_id})
        outcome = _result_to_single(out_result)
    except Exception as exc:
        logger.warning("compare_decision_to_branch: outcome lookup failed: %s", exc)
        outcome = None

    actual_section = {
        "decision": decision,
        "evidence": evidence,
        "affected_entities": actual_affected,
        "outcome": outcome,
    }

    # ---- Hypothetical side --------------------------------------------------
    branch_detail = bs.get_branch_detail(graph, branch_id)
    branch_node = branch_detail.get("branch", {})
    changed_assumptions = bs.get_branch_assumptions(graph, branch_id)
    predictions = q.get_predictions_for_branch(graph, branch_id)

    # Traverse from each hypothetical decision
    hyp_decisions = branch_detail.get("hypothetical_decisions", [])
    hyp_affected: list[dict] = []
    seen_ids: set[str] = set()
    for hd in hyp_decisions:
        hd_id = hd.get("id")
        if hd_id:
            try:
                sub = t.get_affected_entities(graph, hd_id)
                for node in sub:
                    nid = node.get("id")
                    if nid and nid not in seen_ids:
                        seen_ids.add(nid)
                        hyp_affected.append(node)
            except Exception as exc:
                logger.warning(
                    "compare_decision_to_branch: hyp traversal from %s failed: %s",
                    hd_id,
                    exc,
                )

    hypothetical_section = {
        "branch": branch_node,
        "changed_assumptions": changed_assumptions,
        "affected_entities": hyp_affected,
        "predictions": predictions,
    }

    # ---- Diff ---------------------------------------------------------------
    actual_ids = {n.get("id") for n in actual_affected if n.get("id")}
    hyp_ids = {n.get("id") for n in hyp_affected if n.get("id")}

    actual_id_map = {n.get("id"): n for n in actual_affected}
    hyp_id_map = {n.get("id"): n for n in hyp_affected}

    added_impacts = [hyp_id_map[i] for i in (hyp_ids - actual_ids) if i in hyp_id_map]
    removed_impacts = [actual_id_map[i] for i in (actual_ids - hyp_ids) if i in actual_id_map]

    # Evidence gaps: evidence supporting actual but not linked to any hyp decision
    evidence_ids = {e.get("id") for e in evidence}
    hyp_evidence: set[str] = set()
    for hd in hyp_decisions:
        hd_id = hd.get("id")
        if hd_id:
            try:
                hd_evidence = q.get_decision_evidence(graph, hd_id)
                hyp_evidence.update(e.get("id") for e in hd_evidence if e.get("id"))
            except Exception:
                pass
    evidence_gaps = [e for e in evidence if e.get("id") in (evidence_ids - hyp_evidence)]

    diff_section = {
        "added_impacts": added_impacts,
        "removed_impacts": removed_impacts,
        "assumption_changes": changed_assumptions,
        "evidence_gaps": evidence_gaps,
    }

    return {
        "actual": actual_section,
        "hypothetical": hypothetical_section,
        "diff": diff_section,
    }


# ---------------------------------------------------------------------------
# Display formatting
# ---------------------------------------------------------------------------

def format_comparison_for_display(comparison: dict) -> dict:
    """Transform a raw comparison dict into Streamlit-ready display structures.

    Parameters
    ----------
    comparison:
        Output of :func:`compare_decision_to_branch`.

    Returns
    -------
    dict
        Keys: ``actual_panel``, ``hypothetical_panel``, ``diff_panel``.
        Each value is a dict of display-ready strings and labelled lists.
    """
    actual = comparison.get("actual", {})
    hyp = comparison.get("hypothetical", {})
    diff = comparison.get("diff", {})

    # ---- Actual panel -------------------------------------------------------
    decision = actual.get("decision") or {}
    outcome = actual.get("outcome")

    actual_panel = {
        "header": "📋 Actual Decision",
        "decision_id": decision.get("id", "—"),
        "title": decision.get("title", "—"),
        "description": decision.get("description", "—"),
        "made_at": decision.get("made_at", "—"),
        "status_label": "✅ Historical Record",
        "evidence_count": len(actual.get("evidence", [])),
        "affected_count": len(actual.get("affected_entities", [])),
        "outcome_summary": (
            outcome.get("description", "No outcome recorded")
            if outcome
            else "No outcome recorded"
        ),
        "evidence_items": [
            {
                "id": e.get("id"),
                "summary": (e.get("content") or "")[:120] + (
                    "…" if len(e.get("content") or "") > 120 else ""
                ),
                "source": e.get("source", "—"),
            }
            for e in actual.get("evidence", [])
        ],
        "affected_entities": _label_entities(actual.get("affected_entities", [])),
    }

    # ---- Hypothetical panel -------------------------------------------------
    branch = hyp.get("branch") or {}

    hypothetical_panel = {
        "header": "🔀 Hypothetical Branch",
        "branch_id": branch.get("id", "—"),
        "branch_name": branch.get("name", "—"),
        "description": branch.get("description", "—"),
        "created_at": branch.get("created_at", "—"),
        "status_label": _branch_status_label(branch.get("status", "")),
        "assumptions_count": len(hyp.get("changed_assumptions", [])),
        "affected_count": len(hyp.get("affected_entities", [])),
        "predictions_count": len(hyp.get("predictions", [])),
        "assumption_items": [
            {
                "field": a.get("field", "—"),
                "from": a.get("original_value", "—"),
                "to": a.get("new_value", "—"),
            }
            for a in hyp.get("changed_assumptions", [])
        ],
        "prediction_items": [
            {
                "id": p.get("id"),
                "content": (p.get("content") or "")[:120] + (
                    "…" if len(p.get("content") or "") > 120 else ""
                ),
                "confidence": p.get("confidence"),
                "confidence_label": _confidence_label(p.get("confidence")),
            }
            for p in hyp.get("predictions", [])
        ],
        "affected_entities": _label_entities(hyp.get("affected_entities", [])),
    }

    # ---- Diff panel ---------------------------------------------------------
    diff_panel = {
        "header": "🔍 Impact Diff",
        "added_impacts": [
            {**n, "change_type": "added", "change_icon": "➕"}
            for n in diff.get("added_impacts", [])
        ],
        "removed_impacts": [
            {**n, "change_type": "removed", "change_icon": "➖"}
            for n in diff.get("removed_impacts", [])
        ],
        "assumption_changes": [
            {
                "field": a.get("field", "—"),
                "from": a.get("original_value", "—"),
                "to": a.get("new_value", "—"),
                "change_icon": "🔄",
            }
            for a in diff.get("assumption_changes", [])
        ],
        "evidence_gaps": [
            {
                "id": e.get("id"),
                "summary": (e.get("content") or "")[:80] + "…",
                "gap_icon": "⚠️",
            }
            for e in diff.get("evidence_gaps", [])
        ],
        "net_impact_delta": (
            len(diff.get("added_impacts", []))
            - len(diff.get("removed_impacts", []))
        ),
        "summary_line": _build_summary_line(diff),
    }

    return {
        "actual_panel": actual_panel,
        "hypothetical_panel": hypothetical_panel,
        "diff_panel": diff_panel,
    }


# ---------------------------------------------------------------------------
# Private formatting helpers
# ---------------------------------------------------------------------------

def _label_entities(entities: list[dict]) -> list[dict]:
    """Add display-ready ``type_icon`` to each entity dict."""
    icon_map = {
        "Project": "📁",
        "Person": "👤",
        "Decision": "📋",
        "Outcome": "🎯",
        "Evidence": "🔎",
        "ScenarioBranch": "🔀",
        "Prediction": "🔮",
        "AgentRun": "🤖",
    }
    result = []
    for entity in entities:
        label = entity.get("label", "Node")
        result.append(
            {
                **entity,
                "type_icon": icon_map.get(label, "●"),
                "display_name": entity.get("name") or entity.get("id") or "—",
            }
        )
    return result


def _confidence_label(confidence) -> str:
    """Map a 0-1 float to a human-readable confidence label."""
    if confidence is None:
        return "—"
    try:
        c = float(confidence)
    except (TypeError, ValueError):
        return "—"
    if c >= 0.8:
        return "High 🟢"
    if c >= 0.5:
        return "Medium 🟡"
    return "Low 🔴"


def _branch_status_label(status: str) -> str:
    status_map = {
        "active": "🟢 Active",
        "archived": "🗄️ Archived",
        "draft": "✏️ Draft",
    }
    return status_map.get(status, f"● {status}")


def _build_summary_line(diff: dict) -> str:
    added = len(diff.get("added_impacts", []))
    removed = len(diff.get("removed_impacts", []))
    gaps = len(diff.get("evidence_gaps", []))
    changes = len(diff.get("assumption_changes", []))
    parts = []
    if changes:
        parts.append(f"{changes} assumption change(s)")
    if added:
        parts.append(f"{added} new impact(s)")
    if removed:
        parts.append(f"{removed} removed impact(s)")
    if gaps:
        parts.append(f"{gaps} evidence gap(s)")
    return "; ".join(parts) if parts else "No differences detected."


# ---------------------------------------------------------------------------
# Internal result helpers (avoid circular import from db.queries)
# ---------------------------------------------------------------------------

def _row_to_dict(keys: list[str], row) -> dict:
    return {keys[i]: row[i] for i in range(len(keys))}


def _result_to_list(result) -> list[dict]:
    if result is None or result.result_set is None:
        return []
    header = result.header
    return [_row_to_dict(header, row) for row in result.result_set]


def _result_to_single(result) -> dict | None:
    rows = _result_to_list(result)
    return rows[0] if rows else None
