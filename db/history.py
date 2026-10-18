"""EchoForge — Immutability layer for actual historical data.

This module is the single enforcement point that prevents any code path from
mutating nodes whose ``is_actual`` property is ``True``.  It also exposes
read-only helpers for fetching real-history nodes and a controlled write path
for recording new actual outcomes.

Design rules
------------
* ``assert_not_actual()`` must be called before every mutating operation.
* Only ``record_actual_outcome()`` may *create* (never update) actual nodes,
  using ``ON CREATE SET`` so existing nodes are left untouched.
* No f-string injection: all variable data travels via Cypher ``params`` dicts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class HistoryViolationError(Exception):
    """Raised when an operation would mutate actual historical data."""


# ---------------------------------------------------------------------------
# Guard helper
# ---------------------------------------------------------------------------

def assert_not_actual(node_dict: dict, operation: str = "modify") -> None:
    """Raise :class:`HistoryViolationError` if *node_dict* represents an actual node.

    Parameters
    ----------
    node_dict:
        A plain-dict representation of a graph node.  Must contain the key
        ``is_actual``.
    operation:
        Human-readable description of the attempted operation; used in the
        error message.

    Raises
    ------
    HistoryViolationError
        When ``node_dict['is_actual']`` is ``True``.
    """
    if node_dict.get("is_actual") is True:
        node_id = node_dict.get("id", "<unknown>")
        raise HistoryViolationError(
            f"Refused to {operation} node '{node_id}': "
            "is_actual=True nodes are immutable historical records."
        )


# ---------------------------------------------------------------------------
# Read-only actual-history accessors
# ---------------------------------------------------------------------------

def get_actual_decisions(graph) -> list[dict]:
    """Return all Decision nodes with ``is_actual=True``, ordered by ``made_at``.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.

    Returns
    -------
    list[dict]
        Each dict contains ``id``, ``title``, ``description``, ``made_at``,
        and ``is_actual``.
    """
    cypher = (
        "MATCH (d:Decision {is_actual: true}) "
        "RETURN d.id AS id, d.title AS title, d.description AS description, "
        "d.made_at AS made_at, d.is_actual AS is_actual "
        "ORDER BY d.made_at ASC"
    )
    try:
        result = graph.query(cypher)
        rows = _result_to_list(result)
        logger.debug("get_actual_decisions returned %d record(s).", len(rows))
        return rows
    except Exception as exc:
        logger.error("get_actual_decisions failed: %s", exc)
        raise


def get_actual_outcomes(graph) -> list[dict]:
    """Return all Outcome nodes with ``is_actual=True``, ordered by ``observed_at``.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.

    Returns
    -------
    list[dict]
        Each dict contains ``id``, ``description``, ``observed_at``, and
        ``is_actual``.
    """
    cypher = (
        "MATCH (o:Outcome {is_actual: true}) "
        "RETURN o.id AS id, o.description AS description, "
        "o.observed_at AS observed_at, o.is_actual AS is_actual "
        "ORDER BY o.observed_at ASC"
    )
    try:
        result = graph.query(cypher)
        rows = _result_to_list(result)
        logger.debug("get_actual_outcomes returned %d record(s).", len(rows))
        return rows
    except Exception as exc:
        logger.error("get_actual_outcomes failed: %s", exc)
        raise


def get_actual_evidence(graph) -> list[dict]:
    """Return all Evidence nodes.

    Evidence nodes are always considered part of the historical record (they
    have no ``is_actual`` flag); this helper returns all of them.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.

    Returns
    -------
    list[dict]
        Each dict contains ``id``, ``content``, ``source``, and
        ``created_at``.
    """
    cypher = (
        "MATCH (e:Evidence) "
        "RETURN e.id AS id, e.content AS content, e.source AS source, "
        "e.created_at AS created_at"
    )
    try:
        result = graph.query(cypher)
        rows = _result_to_list(result)
        logger.debug("get_actual_evidence returned %d record(s).", len(rows))
        return rows
    except Exception as exc:
        logger.error("get_actual_evidence failed: %s", exc)
        raise


# ---------------------------------------------------------------------------
# Controlled write path for actual outcomes
# ---------------------------------------------------------------------------

def record_actual_outcome(graph, outcome_data: dict) -> dict:
    """Create a new Outcome node with ``is_actual=True``.

    Uses ``MERGE`` on ``id`` so the operation is idempotent.  ``ON CREATE SET``
    ensures that if an outcome with the same ``id`` already exists its
    ``description`` and ``observed_at`` are **never** overwritten.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    outcome_data:
        Required keys: ``id``, ``description``, ``observed_at``.

    Returns
    -------
    dict
        The created-or-existing Outcome node as a plain dict.

    Raises
    ------
    ValueError
        If any required key is absent from *outcome_data*.
    """
    required = {"id", "description", "observed_at"}
    missing = required - outcome_data.keys()
    if missing:
        raise ValueError(
            f"outcome_data is missing required keys: {sorted(missing)}"
        )

    cypher = (
        "MERGE (o:Outcome {id: $id}) "
        "ON CREATE SET "
        "  o.description = $description, "
        "  o.observed_at = $observed_at, "
        "  o.is_actual   = true "
        "RETURN o.id AS id, o.description AS description, "
        "o.observed_at AS observed_at, o.is_actual AS is_actual"
    )
    params: dict = {
        "id": outcome_data["id"],
        "description": outcome_data["description"],
        "observed_at": outcome_data["observed_at"],
    }
    try:
        result = graph.query(cypher, params)
        node = _result_to_single(result)
        logger.info("record_actual_outcome: MERGE on id=%s", outcome_data["id"])
        return node or {}
    except Exception as exc:
        logger.error("record_actual_outcome failed: %s", exc)
        raise


# ---------------------------------------------------------------------------
# Relationship helper
# ---------------------------------------------------------------------------

def link_outcome_to_decision(graph, outcome_id: str, decision_id: str) -> bool:
    """Create an ``EVALUATED_AGAINST`` relationship from an Outcome to a Decision.

    The target Decision **must** have ``is_actual=True``; this prevents
    hypothetical decisions from receiving actual outcome links.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    outcome_id:
        ``id`` of the Outcome node.
    decision_id:
        ``id`` of the Decision node.

    Returns
    -------
    bool
        ``True`` on success.

    Raises
    ------
    HistoryViolationError
        If the Decision node does not have ``is_actual=True``.
    ValueError
        If either node cannot be found.
    """
    # Fetch the target decision and validate its immutability flag
    verify_cypher = (
        "MATCH (d:Decision {id: $decision_id}) "
        "RETURN d.id AS id, d.is_actual AS is_actual"
    )
    try:
        verify_result = graph.query(verify_cypher, {"decision_id": decision_id})
        decision = _result_to_single(verify_result)
    except Exception as exc:
        logger.error("link_outcome_to_decision: Decision lookup failed: %s", exc)
        raise

    if decision is None:
        raise ValueError(f"Decision '{decision_id}' not found.")

    if decision.get("is_actual") is not True:
        raise HistoryViolationError(
            f"Decision '{decision_id}' is not an actual-history node "
            "(is_actual != True). Outcomes can only be linked to real decisions."
        )

    link_cypher = (
        "MATCH (o:Outcome {id: $outcome_id}) "
        "MATCH (d:Decision {id: $decision_id}) "
        "MERGE (o)-[r:EVALUATED_AGAINST]->(d) "
        "RETURN true AS linked"
    )
    try:
        graph.query(
            link_cypher,
            {"outcome_id": outcome_id, "decision_id": decision_id},
        )
        logger.info(
            "EVALUATED_AGAINST created: %s -> %s", outcome_id, decision_id
        )
        return True
    except Exception as exc:
        logger.error("link_outcome_to_decision failed: %s", exc)
        raise


# ---------------------------------------------------------------------------
# Internal helpers (mirrored from db.queries to avoid circular imports)
# ---------------------------------------------------------------------------

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
