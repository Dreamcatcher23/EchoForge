"""EchoForge — Fictional seed data for the NovaTech Systems demo graph.

All entities are entirely fictional and exist solely for demonstration and
development purposes.  The seed represents a database-migration decision made
at "NovaTech Systems" in early 2024 together with its evidence, affected
projects, hypothetical scenario branch, and recorded outcome.

``seed_database(graph)`` uses ``MERGE`` for every node and relationship so the
function is fully idempotent — running it multiple times produces exactly the
same graph state without creating duplicate nodes.

IMPORTANT
---------
``is_actual=True`` nodes represent real history and are NEVER overwritten by
branch-creation logic.  The hypothetical decision ``DEC-002`` and the branch
``BRANCH-001`` both carry ``is_actual=False``.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Return the current UTC datetime as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _merge_node(graph, label: str, params: dict) -> None:
    """MERGE a single node into the graph using its ``id`` property as the key.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    label:
        The Cypher node label (e.g. ``"Person"``).
    params:
        A dict containing at minimum ``{"id": ...}`` plus all other properties
        to set on creation.  Properties are applied via ``ON CREATE SET`` so
        existing nodes are left unchanged.
    """
    # Build ON CREATE SET clause from all params except the merge key 'id'
    set_clauses = ", ".join(
        f"n.{k} = ${k}" for k in params if k != "id"
    )
    on_create = f"ON CREATE SET {set_clauses}" if set_clauses else ""
    # Use a dynamically built string for the label only — no user data in it
    cypher = (
        f"MERGE (n:{label} {{id: $id}}) "
        f"{on_create}"
    )
    graph.query(cypher, params)


def _merge_rel(
    graph,
    from_label: str,
    from_id: str,
    rel_type: str,
    to_label: str,
    to_id: str,
    rel_props: dict | None = None,
) -> None:
    """MERGE a relationship between two already-existing nodes.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object.
    from_label, from_id:
        Label and ``id`` of the source node.
    rel_type:
        Relationship type string (e.g. ``"MADE"``).
    to_label, to_id:
        Label and ``id`` of the target node.
    rel_props:
        Optional extra properties to set on the relationship at creation time.
    """
    props = rel_props or {}
    props.setdefault("created_at", _now_iso())

    # Build SET clause for relationship properties
    set_clauses = ", ".join(f"r.{k} = $rel_{k}" for k in props)
    on_create = f"ON CREATE SET {set_clauses}" if set_clauses else ""

    # Prefix rel prop keys to avoid name collision with node params
    rel_params = {f"rel_{k}": v for k, v in props.items()}
    rel_params["from_id"] = from_id
    rel_params["to_id"] = to_id

    cypher = (
        f"MATCH (a:{from_label} {{id: $from_id}}) "
        f"MATCH (b:{to_label} {{id: $to_id}}) "
        f"MERGE (a)-[r:{rel_type}]->(b) "
        f"{on_create}"
    )
    graph.query(cypher, rel_params)


# ---------------------------------------------------------------------------
# Node creation helpers
# ---------------------------------------------------------------------------

def _seed_people(graph) -> None:
    people = [
        {
            "id": "PERSON-001",
            "name": "Alice Chen",
            "role": "CTO",
            "created_at": "2024-01-01T00:00:00+00:00",
        },
        {
            "id": "PERSON-002",
            "name": "Bob Ramirez",
            "role": "Engineering Lead",
            "created_at": "2024-01-01T00:00:00+00:00",
        },
        {
            "id": "PERSON-003",
            "name": "Carol Singh",
            "role": "Database Architect",
            "created_at": "2024-01-01T00:00:00+00:00",
        },
        {
            "id": "PERSON-004",
            "name": "David Park",
            "role": "Project Manager",
            "created_at": "2024-01-01T00:00:00+00:00",
        },
    ]
    for p in people:
        _merge_node(graph, "Person", p)
    logger.info("Seeded %d Person nodes.", len(people))
    print(f"[seed] Merged {len(people)} Person node(s).")


def _seed_projects(graph) -> None:
    projects = [
        {
            "id": "PROJ-001",
            "name": "Phoenix API",
            "status": "active",
            "created_at": "2024-01-15T00:00:00+00:00",
        },
        {
            "id": "PROJ-002",
            "name": "Atlas Analytics",
            "status": "active",
            "created_at": "2024-01-20T00:00:00+00:00",
        },
        {
            "id": "PROJ-003",
            "name": "Mercury DevTools",
            "status": "active",
            "created_at": "2024-02-01T00:00:00+00:00",
        },
    ]
    for proj in projects:
        _merge_node(graph, "Project", proj)
    logger.info("Seeded %d Project nodes.", len(projects))
    print(f"[seed] Merged {len(projects)} Project node(s).")


def _seed_decisions(graph) -> None:
    decisions = [
        {
            "id": "DEC-001",
            "title": "Migrate production database from PostgreSQL 12 to PostgreSQL 15",
            "description": (
                "Decision to upgrade the NovaTech Systems production database from "
                "PostgreSQL 12 to PostgreSQL 15 to stay ahead of the EOL deadline and "
                "benefit from performance improvements."
            ),
            "made_at": "2024-03-15T09:00:00+00:00",
            "is_actual": True,
        },
        # Hypothetical decision — is_actual=False; lives inside BRANCH-001
        {
            "id": "DEC-002",
            "title": "Migrate production database two weeks earlier on 2024-03-01",
            "description": (
                "[HYPOTHETICAL] What if the migration had been executed two weeks "
                "earlier, on 2024-03-01, giving the Atlas Analytics team more runway?"
            ),
            "made_at": "2024-03-01T09:00:00+00:00",
            "is_actual": False,
        },
    ]
    for d in decisions:
        _merge_node(graph, "Decision", d)
    logger.info("Seeded %d Decision nodes.", len(decisions))
    print(f"[seed] Merged {len(decisions)} Decision node(s).")


def _seed_evidence(graph) -> None:
    evidence = [
        {
            "id": "EV-001",
            "content": "PostgreSQL 12 EOL announced for November 2024.",
            "source": "PostgreSQL.org",
            "created_at": "2024-02-10T00:00:00+00:00",
        },
        {
            "id": "EV-002",
            "content": (
                "Performance benchmarks show 23% query improvement on PostgreSQL 15 "
                "compared to PostgreSQL 12 under NovaTech workload profiles."
            ),
            "source": "Internal benchmark report",
            "created_at": "2024-02-28T00:00:00+00:00",
        },
        {
            "id": "EV-003",
            "content": "Atlas Analytics team estimated 2-week integration effort for PG15 migration.",
            "source": "Team estimation meeting",
            "created_at": "2024-03-10T00:00:00+00:00",
        },
    ]
    for ev in evidence:
        _merge_node(graph, "Evidence", ev)
    logger.info("Seeded %d Evidence nodes.", len(evidence))
    print(f"[seed] Merged {len(evidence)} Evidence node(s).")


def _seed_scenario_branches(graph) -> None:
    branches = [
        {
            "id": "BRANCH-001",
            "name": "Early Migration Scenario",
            "description": (
                "What if the migration occurred two weeks earlier (2024-03-01)? "
                "This branch explores whether earlier execution would have avoided "
                "the 3-day delay experienced by the Atlas Analytics team."
            ),
            "created_at": "2024-05-01T00:00:00+00:00",
            "status": "draft",
        },
    ]
    for b in branches:
        _merge_node(graph, "ScenarioBranch", b)
    logger.info("Seeded %d ScenarioBranch node(s).", len(branches))
    print(f"[seed] Merged {len(branches)} ScenarioBranch node(s).")


def _seed_outcomes(graph) -> None:
    outcomes = [
        {
            "id": "OUT-001",
            "description": (
                "Migration completed on 2024-04-20 with a 3-day delay caused by "
                "Atlas Analytics integration issues discovered during the cutover window."
            ),
            "observed_at": "2024-04-20T18:00:00+00:00",
            "is_actual": True,
        },
    ]
    for o in outcomes:
        _merge_node(graph, "Outcome", o)
    logger.info("Seeded %d Outcome node(s).", len(outcomes))
    print(f"[seed] Merged {len(outcomes)} Outcome node(s).")


# ---------------------------------------------------------------------------
# Policy nodes (Track 3 — Company Brain)
# ---------------------------------------------------------------------------

def _seed_policies(graph) -> None:
    """Seed governance Policy nodes for NovaTech Systems."""
    policies = [
        {
            "id": "POL-001",
            "name": "Database Upgrade Policy",
            "description": (
                "All production database upgrades must be approved by the CTO "
                "and have at least two supporting evidence items before execution."
            ),
            "version": "1.0",
            "status": "active",
            "created_at": "2024-01-01T00:00:00+00:00",
        },
        {
            "id": "POL-002",
            "name": "Change Freeze Policy",
            "description": (
                "No production changes are permitted within 4 weeks of a major "
                "product release unless approved by the CTO and Engineering Lead."
            ),
            "version": "1.0",
            "status": "active",
            "created_at": "2024-01-01T00:00:00+00:00",
        },
    ]
    for p in policies:
        _merge_node(graph, "Policy", p)
    logger.info("Seeded %d Policy node(s).", len(policies))
    print(f"[seed] Merged {len(policies)} Policy node(s).")


# ---------------------------------------------------------------------------
# Relationship creation
# ---------------------------------------------------------------------------

def _seed_relationships(graph) -> None:
    """Create all required relationships using MERGE (idempotent)."""
    rels = [
        # ── Core decision relationships ─────────────────────────────────────
        # Alice MADE DEC-001
        ("Person", "PERSON-001", "MADE", "Decision", "DEC-001"),
        # DEC-001 AFFECTS PROJ-001
        ("Decision", "DEC-001", "AFFECTS", "Project", "PROJ-001"),
        # DEC-001 AFFECTS PROJ-002
        ("Decision", "DEC-001", "AFFECTS", "Project", "PROJ-002"),
        # DEC-001 SUPPORTED_BY EV-001
        ("Decision", "DEC-001", "SUPPORTED_BY", "Evidence", "EV-001"),
        # DEC-001 SUPPORTED_BY EV-002
        ("Decision", "DEC-001", "SUPPORTED_BY", "Evidence", "EV-002"),
        # PROJ-002 SUPPORTED_BY EV-003
        ("Project", "PROJ-002", "SUPPORTED_BY", "Evidence", "EV-003"),
        # DEC-001 HAS_BRANCH BRANCH-001
        ("Decision", "DEC-001", "HAS_BRANCH", "ScenarioBranch", "BRANCH-001"),
        # BRANCH-001 CHANGES DEC-002
        ("ScenarioBranch", "BRANCH-001", "CHANGES", "Decision", "DEC-002"),
        # DEC-001 PRODUCED OUT-001  (actual outcome from the actual decision)
        ("Decision", "DEC-001", "PRODUCED", "Outcome", "OUT-001"),
        # ── Org hierarchy (Track 3 — Company Brain) ─────────────────────────
        # Bob REPORTS_TO Alice (Engineering Lead → CTO)
        ("Person", "PERSON-002", "REPORTS_TO", "Person", "PERSON-001"),
        # Carol REPORTS_TO Bob (Database Architect → Engineering Lead)
        ("Person", "PERSON-003", "REPORTS_TO", "Person", "PERSON-002"),
        # David REPORTS_TO Alice (Project Manager → CTO)
        ("Person", "PERSON-004", "REPORTS_TO", "Person", "PERSON-001"),
        # ── Governance (Track 3 — Company Brain) ────────────────────────────
        # POL-001 GOVERNS DEC-001 (database upgrade policy governs the migration)
        ("Policy", "POL-001", "GOVERNS", "Decision", "DEC-001"),
        # POL-002 GOVERNS PROJ-001 (change freeze governs Phoenix API project)
        ("Policy", "POL-002", "GOVERNS", "Project", "PROJ-001"),
        # ── Evidence usage (Track 1 — Connected Data) ───────────────────────
        # Carol USED EV-002 (DB Architect used the benchmark evidence)
        ("Person", "PERSON-003", "USED", "Evidence", "EV-002"),
        # DEC-002 SPAWNED_FROM DEC-001 (hypothetical spawned from actual)
        ("Decision", "DEC-002", "SPAWNED_FROM", "Decision", "DEC-001"),
    ]

    for from_label, from_id, rel_type, to_label, to_id in rels:
        _merge_rel(graph, from_label, from_id, rel_type, to_label, to_id)

    logger.info("Seeded %d relationship(s).", len(rels))
    print(f"[seed] Merged {len(rels)} relationship(s).")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def seed_database(graph) -> None:
    """Load the NovaTech Systems fictional seed data into the EchoForge graph.

    Uses ``MERGE`` for every node and relationship so the function is fully
    idempotent — safe to run multiple times without duplicating data.

    ``is_actual=True`` nodes (``DEC-001``, ``OUT-001``) are never touched by
    branch-creation logic; only the explicitly hypothetical entities
    (``DEC-002``, ``BRANCH-001``) carry ``is_actual=False``.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object (from ``db.connection.get_graph()``).
    """
    print("[seed] Starting NovaTech Systems seed data load…")
    try:
        _seed_people(graph)
        _seed_projects(graph)
        _seed_decisions(graph)
        _seed_evidence(graph)
        _seed_scenario_branches(graph)
        _seed_outcomes(graph)
        _seed_policies(graph)
        _seed_relationships(graph)
        print("[seed] Seed data load complete.")
        logger.info("seed_database() completed successfully.")
    except Exception as exc:
        logger.error("seed_database() failed: %s", exc)
        raise
