"""EchoForge — Parameterized Cypher query functions.

.. note::
   Phase 2 additions (at the bottom of this file):
   ``get_node_by_id``, ``create_prediction``, ``create_outcome``,
   ``link_prediction_to_outcome``.

All functions accept a ``graph`` argument (FalkorDB Graph object) and return
plain Python ``dict`` / ``list`` values — never raw FalkorDB result objects.

IMPORTANT
---------
* No f-string query injection: all variable data is passed via the ``params``
  dict argument to ``graph.query(cypher, params)``.
* ``create_scenario_branch`` explicitly guards against mutating any node whose
  ``is_actual`` property is ``True``.
"""

import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_header_keys(header) -> list[str]:
    """Extract column name strings from FalkorDB result headers.

    FalkorDB SDK returns headers as ``(type_code, column_name)`` tuples,
    e.g. ``[(1, 'd.id'), (1, 'd.title'), ...]``.
    Older/newer SDK builds may return plain strings instead.
    This function normalises both formats into plain strings.
    """
    keys: list[str] = []
    for col in header:
        if isinstance(col, (list, tuple)) and len(col) >= 2:
            # Standard FalkorDB SDK: index 1 is the column name string
            keys.append(str(col[1]))
        elif isinstance(col, (list, tuple)) and len(col) == 1:
            keys.append(str(col[0]))
        else:
            keys.append(str(col))
    return keys


def _row_to_dict(keys: list[str], row) -> dict:
    """Convert a single result row to a plain dict using the given column keys.

    Handles FalkorDB ``Node`` / ``Edge`` objects by unpacking their
    ``properties`` attribute into a nested dict.
    """
    result_dict: dict = {}
    for i in range(len(keys)):
        val = row[i] if i < len(row) else None
        if hasattr(val, "properties"):
            # FalkorDB Node or Edge object
            result_dict[keys[i]] = dict(val.properties)
        else:
            result_dict[keys[i]] = val
    return result_dict


def _result_to_list(result) -> list[dict]:
    """Convert a FalkorDB QueryResult to a list of plain Python dicts."""
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
        # Fallback: use positional keys
        keys = [f"col_{i}" for i in range(len(result_set[0]))]
    return [_row_to_dict(keys, row) for row in result_set]


def _result_to_single(result) -> dict | None:
    """Convert a FalkorDB query result to a single dict, or None if empty."""
    rows = _result_to_list(result)
    return rows[0] if rows else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Decision queries
# ---------------------------------------------------------------------------

def get_all_decisions(graph) -> list[dict]:
    """Return all Decision nodes as a list of dicts.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.

    Returns
    -------
    list[dict]
        Each dict contains the Decision node's properties.
    """
    cypher = (
        "MATCH (d:Decision) "
        "RETURN d.id AS id, d.title AS title, d.description AS description, "
        "d.made_at AS made_at, d.is_actual AS is_actual"
    )
    try:
        result = graph.query(cypher)
        decisions = _result_to_list(result)
        logger.debug("get_all_decisions returned %d record(s).", len(decisions))
        return decisions
    except Exception as exc:
        logger.error("get_all_decisions failed: %s", exc)
        raise


def get_decision_by_id(graph, decision_id: str) -> dict | None:
    """Return a single Decision node by its ``id``, or ``None`` if not found.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    decision_id:
        The ``id`` property of the Decision node (e.g. ``"DEC-001"``).
    """
    cypher = (
        "MATCH (d:Decision {id: $decision_id}) "
        "RETURN d.id AS id, d.title AS title, d.description AS description, "
        "d.made_at AS made_at, d.is_actual AS is_actual"
    )
    try:
        result = graph.query(cypher, {"decision_id": decision_id})
        decision = _result_to_single(result)
        logger.debug("get_decision_by_id(%s) -> %s", decision_id, decision)
        return decision
    except Exception as exc:
        logger.error("get_decision_by_id(%s) failed: %s", decision_id, exc)
        raise


def get_decision_evidence(graph, decision_id: str) -> list[dict]:
    """Return all Evidence nodes linked to a Decision via ``SUPPORTED_BY``.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    decision_id:
        The ``id`` property of the Decision node.
    """
    cypher = (
        "MATCH (d:Decision {id: $decision_id})-[:SUPPORTED_BY]->(e:Evidence) "
        "RETURN e.id AS id, e.content AS content, e.source AS source, "
        "e.created_at AS created_at"
    )
    try:
        result = graph.query(cypher, {"decision_id": decision_id})
        evidence = _result_to_list(result)
        logger.debug(
            "get_decision_evidence(%s) returned %d record(s).", decision_id, len(evidence)
        )
        return evidence
    except Exception as exc:
        logger.error("get_decision_evidence(%s) failed: %s", decision_id, exc)
        raise


def get_affected_entities(graph, decision_id: str) -> list[dict]:
    """Return all entities affected by a Decision via ``AFFECTS`` relationships.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    decision_id:
        The ``id`` property of the Decision node.

    Returns
    -------
    list[dict]
        Each dict contains ``id``, ``name``, ``status``, and ``label`` of the
        affected node.
    """
    cypher = (
        "MATCH (d:Decision {id: $decision_id})-[:AFFECTS]->(e) "
        "RETURN e.id AS id, e.name AS name, e.status AS status, "
        "labels(e)[0] AS label"
    )
    try:
        result = graph.query(cypher, {"decision_id": decision_id})
        entities = _result_to_list(result)
        logger.debug(
            "get_affected_entities(%s) returned %d record(s).", decision_id, len(entities)
        )
        return entities
    except Exception as exc:
        logger.error("get_affected_entities(%s) failed: %s", decision_id, exc)
        raise


# ---------------------------------------------------------------------------
# ScenarioBranch queries
# ---------------------------------------------------------------------------

def get_scenario_branches(graph) -> list[dict]:
    """Return all ScenarioBranch nodes.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    """
    cypher = (
        "MATCH (b:ScenarioBranch) "
        "RETURN b.id AS id, b.name AS name, b.description AS description, "
        "b.created_at AS created_at, b.status AS status"
    )
    try:
        result = graph.query(cypher)
        branches = _result_to_list(result)
        logger.debug("get_scenario_branches returned %d record(s).", len(branches))
        return branches
    except Exception as exc:
        logger.error("get_scenario_branches failed: %s", exc)
        raise


def get_branch_by_id(graph, branch_id: str) -> dict | None:
    """Return a single ScenarioBranch by its ``id``, or ``None``.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    branch_id:
        The ``id`` property of the ScenarioBranch node.
    """
    cypher = (
        "MATCH (b:ScenarioBranch {id: $branch_id}) "
        "RETURN b.id AS id, b.name AS name, b.description AS description, "
        "b.created_at AS created_at, b.status AS status"
    )
    try:
        result = graph.query(cypher, {"branch_id": branch_id})
        branch = _result_to_single(result)
        logger.debug("get_branch_by_id(%s) -> %s", branch_id, branch)
        return branch
    except Exception as exc:
        logger.error("get_branch_by_id(%s) failed: %s", branch_id, exc)
        raise


def create_scenario_branch(graph, branch_data: dict) -> dict:
    """Create a new ScenarioBranch node and optionally link it to a Decision.

    This function NEVER mutates nodes with ``is_actual=True``.  If
    ``branch_data`` contains a ``source_decision_id`` key, a ``HAS_BRANCH``
    relationship is added from the source Decision to the new branch — but
    only as a new relationship; the source Decision node itself is untouched.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    branch_data:
        Required keys: ``id``, ``name``, ``description``.
        Optional keys: ``source_decision_id`` (str), ``status`` (str).

    Returns
    -------
    dict
        The properties of the newly created ScenarioBranch node.

    Raises
    ------
    ValueError
        If required keys are missing from ``branch_data``.
    """
    required = {"id", "name", "description"}
    missing = required - branch_data.keys()
    if missing:
        raise ValueError(f"branch_data is missing required keys: {missing}")

    branch_id = branch_data["id"]
    branch_name = branch_data["name"]
    branch_desc = branch_data["description"]
    branch_status = branch_data.get("status", "draft")
    created_at = _now_iso()

    # Create the branch node (MERGE — safe to re-run)
    create_cypher = (
        "MERGE (b:ScenarioBranch {id: $id}) "
        "ON CREATE SET b.name = $name, b.description = $description, "
        "b.status = $status, b.created_at = $created_at"
    )
    params: dict = {
        "id": branch_id,
        "name": branch_name,
        "description": branch_desc,
        "status": branch_status,
        "created_at": created_at,
    }

    try:
        graph.query(create_cypher, params)
        logger.info("ScenarioBranch created: %s", branch_id)
    except Exception as exc:
        logger.error("create_scenario_branch node creation failed: %s", exc)
        raise

    # Optionally link to source Decision — guard: never touch is_actual=True nodes
    source_decision_id = branch_data.get("source_decision_id")
    if source_decision_id:
        # Verify the source decision exists before linking
        verify_cypher = (
            "MATCH (d:Decision {id: $dec_id}) "
            "RETURN d.id AS id, d.is_actual AS is_actual"
        )
        try:
            verify_result = graph.query(verify_cypher, {"dec_id": source_decision_id})
            source = _result_to_single(verify_result)
            if source is None:
                logger.warning(
                    "source_decision_id '%s' not found; skipping HAS_BRANCH link.",
                    source_decision_id,
                )
            else:
                # Link via HAS_BRANCH — the Decision node itself is NOT modified
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
                logger.info(
                    "HAS_BRANCH created: %s -> %s", source_decision_id, branch_id
                )
        except Exception as exc:
            logger.error(
                "create_scenario_branch link step failed: %s", exc
            )
            raise

    # Return the created branch
    return get_branch_by_id(graph, branch_id) or {}


# ---------------------------------------------------------------------------
# Path / traversal queries
# ---------------------------------------------------------------------------

def get_dependency_path(graph, from_id: str, to_id: str) -> list:
    """Return the shortest path between two nodes identified by their ``id``.

    The traversal follows any relationship type up to depth 6.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    from_id:
        ``id`` property of the start node.
    to_id:
        ``id`` property of the end node.

    Returns
    -------
    list
        A list of node ``id`` strings along the shortest path, or an empty
        list if no path exists.
    """
    cypher = (
        "MATCH (start {id: $from_id}), (end {id: $to_id}) "
        "MATCH p = shortestPath((start)-[*1..6]->(end)) "
        "UNWIND nodes(p) AS n "
        "RETURN n.id AS id"
    )
    try:
        result = graph.query(cypher, {"from_id": from_id, "to_id": to_id})
        rows = _result_to_list(result)
        path = [r["id"] for r in rows]
        logger.debug(
            "get_dependency_path(%s -> %s) -> %s", from_id, to_id, path
        )
        return path
    except Exception as exc:
        logger.error(
            "get_dependency_path(%s -> %s) failed: %s", from_id, to_id, exc
        )
        raise


# ---------------------------------------------------------------------------
# Prediction queries
# ---------------------------------------------------------------------------

def get_predictions_for_branch(graph, branch_id: str) -> list[dict]:
    """Return all Prediction nodes associated with a ScenarioBranch.

    Predictions are linked to branches via ``SPAWNED_FROM`` (branch->prediction)
    or ``GENERATED`` (agent_run->prediction) + ``EVALUATED_AGAINST`` (prediction->branch).
    This query covers both patterns.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    branch_id:
        The ``id`` property of the ScenarioBranch.
    """
    cypher = (
        "MATCH (b:ScenarioBranch {id: $branch_id})-[:GENERATED]->(p:Prediction) "
        "RETURN p.id AS id, p.content AS content, p.confidence AS confidence, "
        "p.created_at AS created_at, p.status AS status, p.branch_id AS branch_id"
    )
    try:
        result = graph.query(cypher, {"branch_id": branch_id})
        predictions = _result_to_list(result)
        logger.debug(
            "get_predictions_for_branch(%s) returned %d record(s).",
            branch_id,
            len(predictions),
        )
        return predictions
    except Exception as exc:
        logger.error("get_predictions_for_branch(%s) failed: %s", branch_id, exc)
        raise


# ---------------------------------------------------------------------------
# Outcome queries
# ---------------------------------------------------------------------------

def get_outcomes(graph, is_actual: bool = True) -> list[dict]:
    """Return Outcome nodes filtered by ``is_actual``.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    is_actual:
        If ``True`` (default), returns only real-history outcomes.
        If ``False``, returns only hypothetical outcomes.
    """
    cypher = (
        "MATCH (o:Outcome {is_actual: $is_actual}) "
        "RETURN o.id AS id, o.description AS description, "
        "o.observed_at AS observed_at, o.is_actual AS is_actual"
    )
    try:
        result = graph.query(cypher, {"is_actual": is_actual})
        outcomes = _result_to_list(result)
        logger.debug(
            "get_outcomes(is_actual=%s) returned %d record(s).", is_actual, len(outcomes)
        )
        return outcomes
    except Exception as exc:
        logger.error("get_outcomes(is_actual=%s) failed: %s", is_actual, exc)
        raise


# ---------------------------------------------------------------------------
# AgentRun queries
# ---------------------------------------------------------------------------

def get_agent_runs(graph) -> list[dict]:
    """Return all AgentRun nodes.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    """
    cypher = (
        "MATCH (a:AgentRun) "
        "RETURN a.id AS id, a.agent_type AS agent_type, "
        "a.started_at AS started_at, a.completed_at AS completed_at, "
        "a.status AS status, a.summary AS summary"
    )
    try:
        result = graph.query(cypher)
        runs = _result_to_list(result)
        logger.debug("get_agent_runs returned %d record(s).", len(runs))
        return runs
    except Exception as exc:
        logger.error("get_agent_runs failed: %s", exc)
        raise


# ---------------------------------------------------------------------------
# Phase 2 additions — generic node lookup, predictions, outcomes
# ---------------------------------------------------------------------------

def get_node_by_id(graph, node_id: str) -> dict | None:
    """Generic node lookup by ``id`` across all labels.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    node_id:
        The ``id`` property to search for.

    Returns
    -------
    dict | None
        Node properties as a plain dict, or ``None`` if not found.
        Includes a ``label`` key derived from the first label of the node.
    """
    cypher = (
        "MATCH (n {id: $node_id}) "
        "RETURN n.id AS id, labels(n)[0] AS label, "
        "n.name AS name, n.title AS title, "
        "n.description AS description, n.status AS status, "
        "n.is_actual AS is_actual, n.created_at AS created_at"
    )
    try:
        result = graph.query(cypher, {"node_id": node_id})
        node = _result_to_single(result)
        logger.debug("get_node_by_id(%s) -> %s", node_id, node)
        return node
    except Exception as exc:
        logger.error("get_node_by_id(%s) failed: %s", node_id, exc)
        raise


def create_prediction(graph, prediction_data: dict) -> dict:
    """Create a Prediction node and link it to a ScenarioBranch via GENERATED.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    prediction_data:
        Required keys: ``content`` (str), ``confidence`` (float 0-1),
        ``branch_id`` (str).  ``id`` is auto-generated if absent.

    Returns
    -------
    dict
        The created Prediction node properties.

    Raises
    ------
    ValueError
        If required keys are missing or ``confidence`` is outside [0, 1].
    """
    required = {"content", "confidence", "branch_id"}
    missing = required - prediction_data.keys()
    if missing:
        raise ValueError(
            f"prediction_data is missing required keys: {sorted(missing)}"
        )

    confidence = prediction_data["confidence"]
    try:
        confidence = float(confidence)
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be a float between 0 and 1.") from exc
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(
            f"confidence must be between 0 and 1, got {confidence}."
        )

    pred_id = prediction_data.get("id") or f"PRED-{uuid.uuid4().hex[:8].upper()}"
    created_at = _now_iso()
    branch_id = prediction_data["branch_id"]

    create_cypher = (
        "MERGE (p:Prediction {id: $id}) "
        "ON CREATE SET "
        "  p.content    = $content, "
        "  p.confidence = $confidence, "
        "  p.created_at = $created_at, "
        "  p.status     = 'pending', "
        "  p.branch_id  = $branch_id "
        "RETURN p.id AS id, p.content AS content, p.confidence AS confidence, "
        "p.created_at AS created_at, p.status AS status, p.branch_id AS branch_id"
    )
    params: dict = {
        "id": pred_id,
        "content": prediction_data["content"],
        "confidence": confidence,
        "created_at": created_at,
        "branch_id": branch_id,
    }
    try:
        result = graph.query(create_cypher, params)
        node = _result_to_single(result) or {}
        logger.info("Prediction created: %s", pred_id)
    except Exception as exc:
        logger.error("create_prediction failed: %s", exc)
        raise

    # GENERATED: (branch)-[:GENERATED]->(prediction)
    link_cypher = (
        "MATCH (b:ScenarioBranch {id: $branch_id}) "
        "MATCH (p:Prediction {id: $pred_id}) "
        "MERGE (b)-[r:GENERATED]->(p) "
        "ON CREATE SET r.created_at = $created_at"
    )
    try:
        graph.query(
            link_cypher,
            {
                "branch_id": branch_id,
                "pred_id": pred_id,
                "created_at": created_at,
            },
        )
        logger.debug("GENERATED: %s -> %s", branch_id, pred_id)
    except Exception as exc:
        logger.error("create_prediction: GENERATED link failed: %s", exc)
        raise

    return node


def create_outcome(graph, outcome_data: dict) -> dict:
    """Create a hypothetical Outcome node (``is_actual=False``).

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    outcome_data:
        Required keys: ``description`` (str), ``branch_id`` (str).
        ``id`` is auto-generated if absent.

    Returns
    -------
    dict
        The created Outcome node properties.

    Raises
    ------
    ValueError
        If required keys are missing from *outcome_data*.
    """
    required = {"description", "branch_id"}
    missing = required - outcome_data.keys()
    if missing:
        raise ValueError(
            f"outcome_data is missing required keys: {sorted(missing)}"
        )

    out_id = outcome_data.get("id") or f"OUT-{uuid.uuid4().hex[:8].upper()}"
    created_at = _now_iso()
    branch_id = outcome_data["branch_id"]

    create_cypher = (
        "MERGE (o:Outcome {id: $id}) "
        "ON CREATE SET "
        "  o.description = $description, "
        "  o.is_actual   = false, "
        "  o.observed_at = $observed_at, "
        "  o.branch_id   = $branch_id "
        "RETURN o.id AS id, o.description AS description, "
        "o.is_actual AS is_actual, o.observed_at AS observed_at, "
        "o.branch_id AS branch_id"
    )
    params: dict = {
        "id": out_id,
        "description": outcome_data["description"],
        "observed_at": outcome_data.get("observed_at", created_at),
        "branch_id": branch_id,
    }
    try:
        result = graph.query(create_cypher, params)
        node = _result_to_single(result) or {}
        logger.info("Hypothetical Outcome created: %s", out_id)
        return node
    except Exception as exc:
        logger.error("create_outcome failed: %s", exc)
        raise


def link_prediction_to_outcome(
    graph,
    prediction_id: str,
    outcome_id: str,
    evaluation_status: str,
) -> bool:
    """Create an EVALUATED_AGAINST relationship from a Prediction to an Outcome.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    prediction_id:
        ``id`` of the Prediction node.
    outcome_id:
        ``id`` of the Outcome node.
    evaluation_status:
        One of ``'supported'``, ``'contradicted'``, or ``'inconclusive'``.

    Returns
    -------
    bool
        ``True`` on success.

    Raises
    ------
    ValueError
        If *evaluation_status* is not one of the three allowed values.
    """
    valid_statuses = {"supported", "contradicted", "inconclusive"}
    if evaluation_status not in valid_statuses:
        raise ValueError(
            f"evaluation_status must be one of {sorted(valid_statuses)}, "
            f"got '{evaluation_status}'."
        )

    cypher = (
        "MATCH (p:Prediction {id: $pred_id}) "
        "MATCH (o:Outcome {id: $out_id}) "
        "MERGE (p)-[r:EVALUATED_AGAINST]->(o) "
        "ON CREATE SET r.status = $status, r.created_at = $created_at "
        "RETURN true AS linked"
    )
    params: dict = {
        "pred_id": prediction_id,
        "out_id": outcome_id,
        "status": evaluation_status,
        "created_at": _now_iso(),
    }
    try:
        graph.query(cypher, params)
        logger.info(
            "EVALUATED_AGAINST: %s -> %s (status=%s)",
            prediction_id,
            outcome_id,
            evaluation_status,
        )
        return True
    except Exception as exc:
        logger.error("link_prediction_to_outcome failed: %s", exc)
        raise


# ---------------------------------------------------------------------------
# Phase 3 additions — AgentRun persistence
# ---------------------------------------------------------------------------

def save_agent_run(graph, run_data: dict) -> dict:
    """MERGE an AgentRun node by ``id``, setting all required properties.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    run_data:
        Required keys: ``id``, ``agent_type``, ``started_at``,
        ``completed_at``, ``status``, ``summary``.
        Optional keys: ``input_data`` (JSON string), ``output_data`` (JSON
        string).

    Returns
    -------
    dict
        The saved AgentRun node as a plain dict.

    Raises
    ------
    ValueError
        If any required key is missing from *run_data*.
    """
    required = {"id", "agent_type", "started_at", "completed_at", "status", "summary"}
    missing = required - run_data.keys()
    if missing:
        raise ValueError(
            f"run_data is missing required keys: {sorted(missing)}"
        )

    cypher = (
        "MERGE (a:AgentRun {id: $id}) "
        "ON CREATE SET "
        "  a.agent_type   = $agent_type, "
        "  a.started_at   = $started_at, "
        "  a.completed_at = $completed_at, "
        "  a.status       = $status, "
        "  a.summary      = $summary, "
        "  a.input_data   = $input_data, "
        "  a.output_data  = $output_data "
        "ON MATCH SET "
        "  a.completed_at = $completed_at, "
        "  a.status       = $status, "
        "  a.summary      = $summary, "
        "  a.output_data  = $output_data "
        "RETURN a.id AS id, a.agent_type AS agent_type, "
        "a.started_at AS started_at, a.completed_at AS completed_at, "
        "a.status AS status, a.summary AS summary, "
        "a.input_data AS input_data, a.output_data AS output_data"
    )
    params: dict = {
        "id": run_data["id"],
        "agent_type": run_data["agent_type"],
        "started_at": run_data["started_at"],
        "completed_at": run_data["completed_at"],
        "status": run_data["status"],
        "summary": run_data["summary"],
        "input_data": run_data.get("input_data", ""),
        "output_data": run_data.get("output_data", ""),
    }
    try:
        result = graph.query(cypher, params)
        node = _result_to_single(result) or {}
        logger.info("AgentRun saved: %s (status=%s)", run_data["id"], run_data["status"])
        return node
    except Exception as exc:
        logger.error("save_agent_run(%s) failed: %s", run_data.get("id"), exc)
        raise


def get_agent_run_by_id(graph, run_id: str) -> dict | None:
    """Return a single AgentRun node by its ``id``, or ``None`` if not found.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    run_id:
        The ``id`` property of the AgentRun node.

    Returns
    -------
    dict | None
        The AgentRun node as a plain dict, or ``None``.
    """
    cypher = (
        "MATCH (a:AgentRun {id: $run_id}) "
        "RETURN a.id AS id, a.agent_type AS agent_type, "
        "a.started_at AS started_at, a.completed_at AS completed_at, "
        "a.status AS status, a.summary AS summary, "
        "a.input_data AS input_data, a.output_data AS output_data"
    )
    try:
        result = graph.query(cypher, {"run_id": run_id})
        node = _result_to_single(result)
        logger.debug("get_agent_run_by_id(%s) -> %s", run_id, node)
        return node
    except Exception as exc:
        logger.error("get_agent_run_by_id(%s) failed: %s", run_id, exc)
        raise


def get_agent_runs_by_type(
    graph,
    agent_type: str,
    limit: int = 10,
) -> list[dict]:
    """Return recent AgentRun nodes filtered by *agent_type*, ordered by
    ``started_at`` DESC.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    agent_type:
        Value of the ``agent_type`` property to filter on.
    limit:
        Maximum number of records to return (default 10).

    Returns
    -------
    list[dict]
        AgentRun node dicts, most recent first.
    """
    # limit is validated as int; safe integer interpolation
    safe_limit = max(1, int(limit))
    cypher = (
        "MATCH (a:AgentRun {agent_type: $agent_type}) "
        "RETURN a.id AS id, a.agent_type AS agent_type, "
        "a.started_at AS started_at, a.completed_at AS completed_at, "
        "a.status AS status, a.summary AS summary, "
        "a.input_data AS input_data, a.output_data AS output_data "
        "ORDER BY a.started_at DESC "
        f"LIMIT {safe_limit}"
    )
    try:
        result = graph.query(cypher, {"agent_type": agent_type})
        rows = _result_to_list(result)
        logger.debug(
            "get_agent_runs_by_type(%s, limit=%d) -> %d record(s).",
            agent_type,
            safe_limit,
            len(rows),
        )
        return rows
    except Exception as exc:
        logger.error(
            "get_agent_runs_by_type(%s) failed: %s", agent_type, exc
        )
        raise
