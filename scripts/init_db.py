"""EchoForge — CLI smoke-test script.

Connects to FalkorDB, sets up the graph schema, loads the NovaTech Systems
seed data, and runs several read queries to confirm that the graph is
populated correctly.

Usage
-----
    python scripts/init_db.py

Environment variables (all optional — defaults shown):

    FALKORDB_HOST=localhost
    FALKORDB_PORT=6379
    FALKORDB_GRAPH_NAME=echoforge

Copy ``.env.example`` to ``.env`` and edit before running.

Exit codes
----------
0   All steps completed successfully.
1   Any step failed (error message is printed to stderr).
"""

import json
import logging
import sys
from pathlib import Path

# Allow imports from the project root when running as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger("init_db")


def _pretty(label: str, data) -> None:
    """Print a labelled, pretty-printed JSON block to stdout."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(json.dumps(data, indent=2, default=str))


def main() -> int:
    """Run schema setup, seed load, and smoke queries.

    Returns
    -------
    int
        0 on success, 1 on failure.
    """
    # ------------------------------------------------------------------
    # Step 1 — Connect
    # ------------------------------------------------------------------
    print("\n[init_db] Step 1: Connecting to FalkorDB…")
    try:
        from db.connection import get_graph, test_connection

        if not test_connection():
            print(
                "[init_db] ERROR: test_connection() returned False. "
                "Check that FalkorDB is running and .env is correct.",
                file=sys.stderr,
            )
            return 1

        graph = get_graph()
        print("[init_db] Connected successfully.")
    except ConnectionError as exc:
        print(f"[init_db] ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[init_db] Unexpected connection error: {exc}", file=sys.stderr)
        logger.exception("Connection step failed.")
        return 1

    # ------------------------------------------------------------------
    # Step 2 — Schema
    # ------------------------------------------------------------------
    print("\n[init_db] Step 2: Creating schema indexes…")
    try:
        from db.schema import create_schema

        create_schema(graph)
        print("[init_db] Schema setup complete.")
    except Exception as exc:
        print(f"[init_db] ERROR during schema setup: {exc}", file=sys.stderr)
        logger.exception("Schema step failed.")
        return 1

    # ------------------------------------------------------------------
    # Step 3 — Seed data
    # ------------------------------------------------------------------
    print("\n[init_db] Step 3: Loading seed data…")
    try:
        from db.seed import seed_database

        seed_database(graph)
        print("[init_db] Seed data loaded.")
    except Exception as exc:
        print(f"[init_db] ERROR during seed: {exc}", file=sys.stderr)
        logger.exception("Seed step failed.")
        return 1

    # ------------------------------------------------------------------
    # Step 4 — Smoke queries
    # ------------------------------------------------------------------
    print("\n[init_db] Step 4: Running smoke queries…")
    try:
        from db.queries import (
            get_affected_entities,
            get_all_decisions,
            get_decision_evidence,
            get_scenario_branches,
        )

        all_decisions = get_all_decisions(graph)
        _pretty("get_all_decisions()", all_decisions)

        affected = get_affected_entities(graph, "DEC-001")
        _pretty('get_affected_entities("DEC-001")', affected)

        evidence = get_decision_evidence(graph, "DEC-001")
        _pretty('get_decision_evidence("DEC-001")', evidence)

        branches = get_scenario_branches(graph)
        _pretty("get_scenario_branches()", branches)

        print("\n[init_db] All smoke queries passed.")
    except Exception as exc:
        print(f"[init_db] ERROR during smoke queries: {exc}", file=sys.stderr)
        logger.exception("Smoke query step failed.")
        return 1

    print("\n[init_db] Phase 1 initialization complete - exit 0.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
