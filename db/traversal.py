"""EchoForge — Multi-hop graph traversal engine.

This module provides the core "connected data" reasoning required by the
hackathon brief.  All traversal operations use real parameterized Cypher
queries — no in-memory mock data.

Functions
---------
* ``get_affected_entities``  — AFFECTS*1..N depth traversal
* ``get_dependency_path``    — shortest-path between any two nodes
* ``get_impact_summary``     — structured summary dict for a decision
* ``compare_traversals``     — diff between actual and hypothetical impacts
* ``get_evidence_chain``     — evidence nodes reachable from a decision

Design rules
------------
* Variable data only travels via Cypher ``params`` dicts.
* ``max_depth`` is injected as a *literal* into the Cypher string because
  FalkorDB does not support parameterised range quantifiers (``[*1..$n]``).
  The value is validated to be an integer in 1–10 before interpolation.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
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


def _safe_depth(max_depth: int) -> int:
    """Clamp max_depth to the range [1, 10] and return an int."""
    if not isinstance(max_depth, int):
        raise TypeError(f"max_depth must be an int, got {type(max_depth)}")
    return max(1, min(max_depth, 10))


# ---------------------------------------------------------------------------
# Multi-hop AFFECTS traversal
# ---------------------------------------------------------------------------

def get_affected_entities(
    graph,
    decision_id: str,
    max_depth: int = 5,
) -> list[dict]:
    """Traverse ``AFFECTS`` relationships up to *max_depth* hops.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    decision_id:
        ``id`` of the source Decision node.
    max_depth:
        Maximum relationship hops (1–10, default 5).

    Returns
    -------
    list[dict]
        Each dict contains ``id``, ``label``, ``name``, ``depth``, and
        ``path_ids`` (list of node ids along the path).

    Notes
    -----
    The depth literal is validated and interpolated as a safe integer — it
    carries no user-supplied string data.
    """
    depth = _safe_depth(max_depth)
    # depth is a validated integer; interpolation is safe (no string injection)
    cypher = (
        f"MATCH path = (d:Decision {{id: $id}})-[:AFFECTS*1..{depth}]->(affected) "
        "RETURN affected.id AS id, "
        "labels(affected)[0] AS label, "
        "affected.name AS name, "
        "length(path) AS depth, "
        "[n IN nodes(path) | n.id] AS path_ids "
        "ORDER BY depth ASC"
    )
    try:
        result = graph.query(cypher, {"id": decision_id})
        rows = _result_to_list(result)
        logger.debug(
            "get_affected_entities(%s, depth=%d) -> %d node(s).",
            decision_id,
            depth,
            len(rows),
        )
        return rows
    except Exception as exc:
        logger.error("get_affected_entities(%s) failed: %s", decision_id, exc)
        raise


# ---------------------------------------------------------------------------
# Shortest-path between two arbitrary nodes
# ---------------------------------------------------------------------------

def get_dependency_path(
    graph,
    from_node_id: str,
    to_node_id: str,
) -> list[dict]:
    """Find the shortest path between two nodes across any relationship type.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    from_node_id:
        ``id`` property of the start node.
    to_node_id:
        ``id`` property of the destination node.

    Returns
    -------
    list[dict]
        Ordered list of ``{node_id, node_label, relationship_type}`` dicts
        representing the path.  The final entry will have
        ``relationship_type = None`` (no outgoing edge from the last node).
        Returns an empty list if no path exists.
    """
    cypher = (
        "MATCH (a {id: $from_id}), (b {id: $to_id}) "
        "MATCH path = shortestPath((a)-[*1..10]->(b)) "
        "RETURN "
        "  [n IN nodes(path) | n.id]            AS node_ids, "
        "  [n IN nodes(path) | labels(n)[0]]    AS node_labels, "
        "  [r IN relationships(path) | type(r)] AS rel_types"
    )
    try:
        result = graph.query(cypher, {"from_id": from_node_id, "to_id": to_node_id})
        row = _result_to_single(result)
        if row is None:
            return []

        node_ids: list = row.get("node_ids") or []
        node_labels: list = row.get("node_labels") or []
        rel_types: list = row.get("rel_types") or []

        path_records: list[dict] = []
        for i, nid in enumerate(node_ids):
            path_records.append(
                {
                    "node_id": nid,
                    "node_label": node_labels[i] if i < len(node_labels) else None,
                    "relationship_type": rel_types[i] if i < len(rel_types) else None,
                }
            )
        logger.debug(
            "get_dependency_path(%s -> %s): %d step(s).",
            from_node_id,
            to_node_id,
            len(path_records),
        )
        return path_records
    except Exception as exc:
        logger.error(
            "get_dependency_path(%s -> %s) failed: %s",
            from_node_id,
            to_node_id,
            exc,
        )
        raise


# ---------------------------------------------------------------------------
# Impact summary
# ---------------------------------------------------------------------------

def get_impact_summary(graph, decision_id: str) -> dict:
    """Return a structured impact summary for a Decision.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    decision_id:
        ``id`` of the Decision node.

    Returns
    -------
    dict
        Keys:

        * ``decision_id`` — str
        * ``directly_affected_projects`` — list of Project-label dicts
        * ``directly_affected_people`` — list of Person-label dicts
        * ``total_affected_count`` — int
        * ``max_depth_reached`` — int
        * ``dependency_chain`` — all affected nodes ordered by depth
    """
    all_affected = get_affected_entities(graph, decision_id, max_depth=5)

    projects = [n for n in all_affected if n.get("label") == "Project" and n.get("depth") == 1]
    people = [n for n in all_affected if n.get("label") == "Person" and n.get("depth") == 1]

    depths = [n.get("depth", 0) for n in all_affected]
    max_depth_reached = max(depths) if depths else 0

    return {
        "decision_id": decision_id,
        "directly_affected_projects": projects,
        "directly_affected_people": people,
        "total_affected_count": len(all_affected),
        "max_depth_reached": max_depth_reached,
        "dependency_chain": all_affected,
    }


# ---------------------------------------------------------------------------
# Hypothetical vs. actual traversal comparison
# ---------------------------------------------------------------------------

def compare_traversals(
    graph,
    actual_decision_id: str,
    branch_id: str,
) -> dict:
    """Compare the AFFECTS traversal of an actual Decision vs. a hypothetical branch.

    For the hypothetical side the traversal is run over the Decision nodes
    linked to the branch via ``CHANGES`` (``is_actual=False``).

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    actual_decision_id:
        ``id`` of the actual (``is_actual=True``) Decision.
    branch_id:
        ``id`` of the ScenarioBranch to compare against.

    Returns
    -------
    dict
        Keys: ``actual_affected``, ``hypothetical_affected``,
        ``added_impacts``, ``removed_impacts``, ``common_impacts``.
    """
    # Actual traversal
    actual_affected = get_affected_entities(graph, actual_decision_id)

    # Collect all hypothetical decisions for this branch
    hyp_cypher = (
        "MATCH (b:ScenarioBranch {id: $branch_id})-[:CHANGES]->(h:Decision) "
        "RETURN h.id AS id"
    )
    try:
        hyp_result = graph.query(hyp_cypher, {"branch_id": branch_id})
        hyp_rows = _result_to_list(hyp_result)
    except Exception as exc:
        logger.error("compare_traversals: hyp decision lookup failed: %s", exc)
        hyp_rows = []

    hypothetical_affected: list[dict] = []
    for row in hyp_rows:
        hyp_id = row.get("id")
        if hyp_id:
            try:
                sub_affected = get_affected_entities(graph, hyp_id)
                hypothetical_affected.extend(sub_affected)
            except Exception as exc:
                logger.warning(
                    "compare_traversals: traversal from %s failed: %s", hyp_id, exc
                )

    # Set-based comparison on node ids
    actual_ids = {n.get("id") for n in actual_affected if n.get("id")}
    hyp_ids = {n.get("id") for n in hypothetical_affected if n.get("id")}

    added_ids = hyp_ids - actual_ids
    removed_ids = actual_ids - hyp_ids
    common_ids = actual_ids & hyp_ids

    # Build result lists preserving full node dicts
    hyp_id_map = {n.get("id"): n for n in hypothetical_affected}
    actual_id_map = {n.get("id"): n for n in actual_affected}

    return {
        "actual_affected": actual_affected,
        "hypothetical_affected": hypothetical_affected,
        "added_impacts": [hyp_id_map[i] for i in added_ids if i in hyp_id_map],
        "removed_impacts": [actual_id_map[i] for i in removed_ids if i in actual_id_map],
        "common_impacts": [actual_id_map[i] for i in common_ids if i in actual_id_map],
    }


# ---------------------------------------------------------------------------
# Evidence chain
# ---------------------------------------------------------------------------

def get_evidence_chain(graph, decision_id: str) -> list[dict]:
    """Return all Evidence reachable from a Decision.

    Covers two patterns:
    1. ``(Decision)-[:SUPPORTED_BY]->(Evidence)``
    2. ``(Decision)-[:AFFECTS]->(Project)-[:SUPPORTED_BY]->(Evidence)``

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    decision_id:
        ``id`` of the Decision node.

    Returns
    -------
    list[dict]
        Unique Evidence node dicts (``id``, ``content``, ``source``,
        ``created_at``, ``via``).
    """
    # Direct evidence
    direct_cypher = (
        "MATCH (d:Decision {id: $id})-[:SUPPORTED_BY]->(e:Evidence) "
        "RETURN e.id AS id, e.content AS content, e.source AS source, "
        "e.created_at AS created_at, 'direct' AS via"
    )
    # Evidence via affected projects
    indirect_cypher = (
        "MATCH (d:Decision {id: $id})-[:AFFECTS]->(p:Project)-[:SUPPORTED_BY]->(e:Evidence) "
        "RETURN e.id AS id, e.content AS content, e.source AS source, "
        "e.created_at AS created_at, 'via_project' AS via"
    )
    params: dict = {"id": decision_id}
    evidence_map: dict[str, dict] = {}
    for cypher in (direct_cypher, indirect_cypher):
        try:
            result = graph.query(cypher, params)
            for row in _result_to_list(result):
                eid = row.get("id")
                if eid and eid not in evidence_map:
                    evidence_map[eid] = row
        except Exception as exc:
            logger.error("get_evidence_chain query failed: %s", exc)
            raise

    chain = list(evidence_map.values())
    logger.debug(
        "get_evidence_chain(%s) -> %d evidence node(s).", decision_id, len(chain)
    )
    return chain


# ---------------------------------------------------------------------------
# Policy traversal (Track 3 — Company Brain)
# ---------------------------------------------------------------------------

def get_policies_for_decision(graph, decision_id: str) -> list[dict]:
    """Return Policy nodes that GOVERN a given Decision or its affected Projects.

    Traversal patterns:
    1. ``(Policy)-[:GOVERNS]->(Decision)``
    2. ``(Policy)-[:GOVERNS]->(Project)<-[:AFFECTS]-(Decision)``

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    decision_id:
        ``id`` of the target Decision node.

    Returns
    -------
    list[dict]
        Unique Policy node dicts (``id``, ``name``, ``description``,
        ``status``, ``governs`` — 'decision' or 'project').
    """
    direct_cypher = (
        "MATCH (pol:Policy)-[:GOVERNS]->(d:Decision {id: $id}) "
        "RETURN pol.id AS id, pol.name AS name, pol.description AS description, "
        "pol.status AS status, 'decision' AS governs"
    )
    via_project_cypher = (
        "MATCH (pol:Policy)-[:GOVERNS]->(p:Project)<-[:AFFECTS]-(d:Decision {id: $id}) "
        "RETURN pol.id AS id, pol.name AS name, pol.description AS description, "
        "pol.status AS status, 'project' AS governs"
    )
    params: dict = {"id": decision_id}
    policy_map: dict[str, dict] = {}
    for cypher in (direct_cypher, via_project_cypher):
        try:
            result = graph.query(cypher, params)
            for row in _result_to_list(result):
                pid = row.get("id")
                if pid and pid not in policy_map:
                    policy_map[pid] = row
        except Exception as exc:
            logger.error("get_policies_for_decision query failed: %s", exc)
            raise
    policies = list(policy_map.values())
    logger.debug(
        "get_policies_for_decision(%s) -> %d policy node(s).", decision_id, len(policies)
    )
    return policies


# ---------------------------------------------------------------------------
# Org hierarchy traversal (Track 3 — Company Brain)
# ---------------------------------------------------------------------------

def get_org_hierarchy(graph, person_id: str, direction: str = "up") -> list[dict]:
    """Traverse the REPORTS_TO org hierarchy from a given Person.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    person_id:
        ``id`` of the starting Person node.
    direction:
        ``'up'`` — traverse upwards (who this person reports to).
        ``'down'`` — traverse downwards (who reports to this person).

    Returns
    -------
    list[dict]
        Person node dicts with ``id``, ``name``, ``role``, ``depth``.
    """
    if direction == "up":
        cypher = (
            "MATCH path = (p:Person {id: $id})-[:REPORTS_TO*1..5]->(mgr:Person) "
            "RETURN mgr.id AS id, mgr.name AS name, mgr.role AS role, "
            "length(path) AS depth ORDER BY depth ASC"
        )
    else:
        cypher = (
            "MATCH path = (p:Person {id: $id})<-[:REPORTS_TO*1..5]-(sub:Person) "
            "RETURN sub.id AS id, sub.name AS name, sub.role AS role, "
            "length(path) AS depth ORDER BY depth ASC"
        )
    try:
        result = graph.query(cypher, {"id": person_id})
        rows = _result_to_list(result)
        logger.debug(
            "get_org_hierarchy(%s, %s) -> %d node(s).", person_id, direction, len(rows)
        )
        return rows
    except Exception as exc:
        logger.error("get_org_hierarchy(%s) failed: %s", person_id, exc)
        raise


# ---------------------------------------------------------------------------
# Extended connected-data traversal: USED + SPAWNED_FROM (Track 1)
# ---------------------------------------------------------------------------

def get_full_connected_impact(graph, decision_id: str) -> dict:
    """Return the complete connected-data picture for a Decision.

    Goes beyond AFFECTS to include:
    - Evidence used by people (USED relationships)
    - Hypothetical decisions that originated from this one (SPAWNED_FROM)
    - Policies that govern the decision or its projects

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    decision_id:
        ``id`` of the target Decision node.

    Returns
    -------
    dict
        Keys: ``affected_entities``, ``evidence_chain``, ``policies``,
        ``spawned_decisions``, ``evidence_users``.
    """
    # Entities affected via AFFECTS
    affected = get_affected_entities(graph, decision_id)

    # Evidence chain (SUPPORTED_BY direct + via project)
    evidence = get_evidence_chain(graph, decision_id)

    # Policies governing this decision or its projects
    policies = get_policies_for_decision(graph, decision_id)

    # Hypothetical decisions spawned from this one
    spawned_cypher = (
        "MATCH (hyp:Decision)-[:SPAWNED_FROM]->(d:Decision {id: $id}) "
        "RETURN hyp.id AS id, hyp.title AS title, hyp.is_actual AS is_actual"
    )
    spawned: list[dict] = []
    try:
        result = graph.query(spawned_cypher, {"id": decision_id})
        spawned = _result_to_list(result)
    except Exception as exc:
        logger.warning("get_full_connected_impact: SPAWNED_FROM query failed: %s", exc)

    # People who USED evidence related to this decision
    used_cypher = (
        "MATCH (d:Decision {id: $id})-[:SUPPORTED_BY]->(e:Evidence)<-[:USED]-(p:Person) "
        "RETURN p.id AS id, p.name AS name, p.role AS role, e.id AS evidence_id"
    )
    evidence_users: list[dict] = []
    try:
        result = graph.query(used_cypher, {"id": decision_id})
        evidence_users = _result_to_list(result)
    except Exception as exc:
        logger.warning("get_full_connected_impact: USED query failed: %s", exc)

    return {
        "affected_entities": affected,
        "evidence_chain": evidence,
        "policies": policies,
        "spawned_decisions": spawned,
        "evidence_users": evidence_users,
    }
