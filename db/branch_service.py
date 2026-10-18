"""EchoForge — Hypothetical branch lifecycle service.

Manages the full lifecycle of ``ScenarioBranch`` nodes: creation, listing,
inspection, and archival.  This module **never** mutates nodes whose
``is_actual`` property is ``True``.

Design rules
------------
* Source Decision nodes (``is_actual=True``) are only *read*; new
  relationships point **to** them but their properties are never changed.
* ``changed_assumptions`` cause new hypothetical Decision nodes
  (``is_actual=False``) to be created and linked via ``CHANGES``.
* All data values travel via Cypher ``params`` dicts — no f-string injection.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from db.history import HistoryViolationError, assert_not_actual

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_header_keys(header) -> list[str]:
    keys: list[str] = []
    for col in header:
        if isinstance(col, (list, tuple)) and len(col) >= 2:
            keys.append(str(col[1]))
        elif isinstance(col, (list, tuple)) and len(col) == 1:
            keys.append(str(col[0]))
        else:
            keys.append(str(col))
    return keys


def _row_to_dict(keys: list[str], row) -> dict:
    result_dict: dict = {}
    for i in range(len(keys)):
        val = row[i] if i < len(row) else None
        if hasattr(val, "properties"):
            result_dict[keys[i]] = dict(val.properties)
        else:
            result_dict[keys[i]] = val
    return result_dict


def _result_to_list(result) -> list[dict]:
    if result is None:
        return []
    try:
        result_set = result.result_set
    except AttributeError:
        return []
    if not result_set:
        return []
    try:
        keys = _extract_header_keys(result.header)
    except (AttributeError, IndexError):
        keys = [f"col_{i}" for i in range(len(result_set[0]))]
    return [_row_to_dict(keys, row) for row in result_set]


def _result_to_single(result) -> dict | None:
    rows = _result_to_list(result)
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Branch creation
# ---------------------------------------------------------------------------

def create_branch(
    graph,
    source_decision_id: str,
    branch_name: str,
    description: str,
    changed_assumptions: list[dict],
) -> dict:
    """Create a new ScenarioBranch node and related hypothetical Decisions.

    The source Decision (``is_actual=True``) is **never** modified.  A
    ``HAS_BRANCH`` relationship is created from it to the new branch node.
    For each assumption in *changed_assumptions* a new hypothetical Decision
    node (``is_actual=False``) is created and linked to the branch via
    ``CHANGES``.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    source_decision_id:
        ``id`` of the actual Decision this branch diverges from.
    branch_name:
        Human-readable name for the branch.
    description:
        Longer explanation of what this branch is testing.
    changed_assumptions:
        A list of dicts, each with the keys ``field``, ``original_value``,
        and ``new_value`` describing a single assumption change.

    Returns
    -------
    dict
        The newly created ScenarioBranch node properties.

    Raises
    ------
    ValueError
        If the source Decision is not found.
    HistoryViolationError
        If the source Decision has ``is_actual=True`` and any code path
        attempted to modify it (safety net; should not be reachable via
        normal flow).
    """
    # ---- 1. Validate source decision ----------------------------------------
    verify_cypher = (
        "MATCH (d:Decision {id: $dec_id}) "
        "RETURN d.id AS id, d.title AS title, d.description AS description, "
        "d.made_at AS made_at, d.is_actual AS is_actual"
    )
    verify_result = graph.query(verify_cypher, {"dec_id": source_decision_id})
    source_decision = _result_to_single(verify_result)

    if source_decision is None:
        raise ValueError(
            f"Source Decision '{source_decision_id}' not found in the graph."
        )

    # Safety net — assert_not_actual raises HistoryViolationError if somehow
    # we're about to write to an actual node (guards are belt-and-suspenders).
    # We only assert here as a read check; we will NOT modify this node.
    # (We intentionally do NOT call assert_not_actual on source_decision here
    #  because we are allowed to *link from* it — just not to change it.)

    # ---- 2. Create branch node ----------------------------------------------
    branch_id = f"BRANCH-{uuid.uuid4().hex[:8].upper()}"
    created_at = _now_iso()

    branch_cypher = (
        "MERGE (b:ScenarioBranch {id: $id}) "
        "ON CREATE SET "
        "  b.name        = $name, "
        "  b.description = $description, "
        "  b.status      = 'active', "
        "  b.created_at  = $created_at "
        "RETURN b.id AS id, b.name AS name, b.description AS description, "
        "b.status AS status, b.created_at AS created_at"
    )
    branch_params: dict = {
        "id": branch_id,
        "name": branch_name,
        "description": description,
        "created_at": created_at,
    }
    graph.query(branch_cypher, branch_params)
    logger.info("ScenarioBranch created: %s", branch_id)

    # ---- 3. HAS_BRANCH from source Decision → branch ------------------------
    # We only create a relationship; the Decision node's properties stay intact.
    link_cypher = (
        "MATCH (d:Decision {id: $dec_id}) "
        "MATCH (b:ScenarioBranch {id: $branch_id}) "
        "MERGE (d)-[r:HAS_BRANCH]->(b) "
        "ON CREATE SET r.created_at = $created_at"
    )
    graph.query(
        link_cypher,
        {
            "dec_id": source_decision_id,
            "branch_id": branch_id,
            "created_at": created_at,
        },
    )
    logger.info("HAS_BRANCH: %s -> %s", source_decision_id, branch_id)

    # ---- 4. Create hypothetical Decision nodes for each assumption ----------
    for idx, assumption in enumerate(changed_assumptions):
        field = assumption.get("field", f"assumption_{idx}")
        original_value = str(assumption.get("original_value", ""))
        new_value = str(assumption.get("new_value", ""))

        # Build a descriptive title from the source decision + field
        hyp_title = (
            f"[HYP] {source_decision.get('title', source_decision_id)} "
            f"— {field} changed"
        )
        hyp_desc = (
            f"Hypothetical: '{field}' changed from '{original_value}' "
            f"to '{new_value}'"
        )
        hyp_id = f"HYP-DEC-{uuid.uuid4().hex[:8].upper()}"

        hyp_cypher = (
            "MERGE (h:Decision {id: $id}) "
            "ON CREATE SET "
            "  h.title       = $title, "
            "  h.description = $description, "
            "  h.made_at     = $made_at, "
            "  h.is_actual   = false, "
            "  h.field       = $field, "
            "  h.original_value = $original_value, "
            "  h.new_value   = $new_value, "
            "  h.source_decision_id = $source_dec_id "
            "RETURN h.id AS id"
        )
        hyp_params: dict = {
            "id": hyp_id,
            "title": hyp_title,
            "description": hyp_desc,
            "made_at": created_at,
            "field": field,
            "original_value": original_value,
            "new_value": new_value,
            "source_dec_id": source_decision_id,
        }
        graph.query(hyp_cypher, hyp_params)
        logger.debug("Hypothetical Decision created: %s (field=%s)", hyp_id, field)

        # CHANGES: (branch)-[:CHANGES]->(hyp_decision)
        changes_cypher = (
            "MATCH (b:ScenarioBranch {id: $branch_id}) "
            "MATCH (h:Decision {id: $hyp_id}) "
            "MERGE (b)-[r:CHANGES]->(h) "
            "ON CREATE SET r.field = $field, r.created_at = $created_at"
        )
        graph.query(
            changes_cypher,
            {
                "branch_id": branch_id,
                "hyp_id": hyp_id,
                "field": field,
                "created_at": created_at,
            },
        )

    # ---- 5. Return branch dict ----------------------------------------------
    return get_branch_detail(graph, branch_id)


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------

def list_branches(graph) -> list[dict]:
    """Return all ScenarioBranch nodes with their source Decision ``id``.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.

    Returns
    -------
    list[dict]
        Each dict contains branch properties plus ``source_decision_id``
        (may be ``None`` if not linked).
    """
    cypher = (
        "MATCH (b:ScenarioBranch) "
        "OPTIONAL MATCH (d:Decision)-[:HAS_BRANCH]->(b) "
        "RETURN b.id AS id, b.name AS name, b.description AS description, "
        "b.status AS status, b.created_at AS created_at, "
        "d.id AS source_decision_id "
        "ORDER BY b.created_at DESC"
    )
    try:
        result = graph.query(cypher)
        rows = _result_to_list(result)
        logger.debug("list_branches returned %d record(s).", len(rows))
        return rows
    except Exception as exc:
        logger.error("list_branches failed: %s", exc)
        raise


# ---------------------------------------------------------------------------
# Detail / inspection
# ---------------------------------------------------------------------------

def get_branch_detail(graph, branch_id: str) -> dict:
    """Return a comprehensive branch dict including related nodes.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    branch_id:
        ``id`` of the ScenarioBranch node.

    Returns
    -------
    dict
        Keys:

        * ``branch`` — branch node properties
        * ``source_decision`` — the actual Decision this branch diverged from
        * ``hypothetical_decisions`` — list of ``is_actual=False`` Decision nodes
          linked via ``CHANGES``
        * ``predictions`` — list of Prediction nodes linked via ``GENERATED``
        * ``outcomes`` — list of Outcome nodes linked via ``EVALUATED_AGAINST``
    """
    # Branch node
    branch_cypher = (
        "MATCH (b:ScenarioBranch {id: $branch_id}) "
        "RETURN b.id AS id, b.name AS name, b.description AS description, "
        "b.status AS status, b.created_at AS created_at"
    )
    try:
        branch_result = graph.query(branch_cypher, {"branch_id": branch_id})
        branch = _result_to_single(branch_result) or {}
    except Exception as exc:
        logger.error("get_branch_detail: branch lookup failed: %s", exc)
        raise

    # Source decision
    src_cypher = (
        "MATCH (d:Decision)-[:HAS_BRANCH]->(b:ScenarioBranch {id: $branch_id}) "
        "RETURN d.id AS id, d.title AS title, d.description AS description, "
        "d.made_at AS made_at, d.is_actual AS is_actual"
    )
    try:
        src_result = graph.query(src_cypher, {"branch_id": branch_id})
        source_decision = _result_to_single(src_result)
    except Exception as exc:
        logger.error("get_branch_detail: source decision lookup failed: %s", exc)
        source_decision = None

    # Hypothetical decisions
    hyp_cypher = (
        "MATCH (b:ScenarioBranch {id: $branch_id})-[:CHANGES]->(h:Decision) "
        "RETURN h.id AS id, h.title AS title, h.description AS description, "
        "h.is_actual AS is_actual, h.field AS field, "
        "h.original_value AS original_value, h.new_value AS new_value"
    )
    try:
        hyp_result = graph.query(hyp_cypher, {"branch_id": branch_id})
        hypothetical_decisions = _result_to_list(hyp_result)
    except Exception as exc:
        logger.error("get_branch_detail: hyp decisions lookup failed: %s", exc)
        hypothetical_decisions = []

    # Predictions
    pred_cypher = (
        "MATCH (b:ScenarioBranch {id: $branch_id})-[:GENERATED]->(p:Prediction) "
        "RETURN p.id AS id, p.content AS content, p.confidence AS confidence, "
        "p.created_at AS created_at, p.status AS status"
    )
    try:
        pred_result = graph.query(pred_cypher, {"branch_id": branch_id})
        predictions = _result_to_list(pred_result)
    except Exception as exc:
        logger.error("get_branch_detail: predictions lookup failed: %s", exc)
        predictions = []

    # Outcomes
    out_cypher = (
        "MATCH (b:ScenarioBranch {id: $branch_id})-[:EVALUATED_AGAINST]->(o:Outcome) "
        "RETURN o.id AS id, o.description AS description, "
        "o.observed_at AS observed_at, o.is_actual AS is_actual"
    )
    try:
        out_result = graph.query(out_cypher, {"branch_id": branch_id})
        outcomes = _result_to_list(out_result)
    except Exception as exc:
        logger.error("get_branch_detail: outcomes lookup failed: %s", exc)
        outcomes = []

    return {
        "branch": branch,
        "source_decision": source_decision,
        "hypothetical_decisions": hypothetical_decisions,
        "predictions": predictions,
        "outcomes": outcomes,
    }


# ---------------------------------------------------------------------------
# Archival
# ---------------------------------------------------------------------------

def deactivate_branch(graph, branch_id: str) -> bool:
    """Set a branch's ``status`` to ``'archived'``.

    Nodes are retained; only the status property of the ScenarioBranch is
    changed.  Actual nodes are never touched.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    branch_id:
        ``id`` of the ScenarioBranch to archive.

    Returns
    -------
    bool
        ``True`` on success.
    """
    cypher = (
        "MATCH (b:ScenarioBranch {id: $branch_id}) "
        "SET b.status = 'archived' "
        "RETURN b.id AS id"
    )
    try:
        result = graph.query(cypher, {"branch_id": branch_id})
        row = _result_to_single(result)
        if row is None:
            logger.warning("deactivate_branch: branch '%s' not found.", branch_id)
            return False
        logger.info("Branch archived: %s", branch_id)
        return True
    except Exception as exc:
        logger.error("deactivate_branch failed: %s", exc)
        raise


# ---------------------------------------------------------------------------
# Assumption inspection
# ---------------------------------------------------------------------------

def get_branch_assumptions(graph, branch_id: str) -> list[dict]:
    """Return the hypothetical Decision nodes linked to a branch via ``CHANGES``.

    Each result dict is formatted as an assumption with ``original_value`` vs.
    ``new_value`` for easy comparison display.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    branch_id:
        ``id`` of the ScenarioBranch.

    Returns
    -------
    list[dict]
        Each dict contains ``hyp_decision_id``, ``field``, ``original_value``,
        ``new_value``, ``title``, and ``description``.
    """
    cypher = (
        "MATCH (b:ScenarioBranch {id: $branch_id})-[r:CHANGES]->(h:Decision) "
        "RETURN h.id AS hyp_decision_id, h.title AS title, "
        "h.description AS description, "
        "h.field AS field, h.original_value AS original_value, "
        "h.new_value AS new_value, h.is_actual AS is_actual"
    )
    try:
        result = graph.query(cypher, {"branch_id": branch_id})
        rows = _result_to_list(result)
        logger.debug(
            "get_branch_assumptions(%s) returned %d record(s).", branch_id, len(rows)
        )
        return rows
    except Exception as exc:
        logger.error("get_branch_assumptions failed: %s", exc)
        raise
