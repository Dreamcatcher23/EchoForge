"""EchoForge — FalkorDB graph schema setup.

Defines indexes for all node label ``id`` properties so lookups are fast
and ``id`` values are effectively unique within each label.

FalkorDB syntax for index creation::

    CREATE INDEX FOR (n:Label) ON (n.property)

``create_schema(graph)`` is idempotent — calling it multiple times does not
raise errors because FalkorDB silently ignores duplicate index creation
requests.
"""

import logging

logger = logging.getLogger(__name__)

# Each entry: (label, property)
_INDEXES: list[tuple[str, str]] = [
    ("Person", "id"),
    ("Project", "id"),
    ("Decision", "id"),
    ("Evidence", "id"),
    ("ScenarioBranch", "id"),
    ("Prediction", "id"),
    ("Outcome", "id"),
    ("AgentRun", "id"),
    ("Policy", "id"),          # Track 3: Company Brain — governance policies
]


def create_schema(graph) -> None:
    """Create indexes for all node labels in the EchoForge graph.

    Parameters
    ----------
    graph:
        A connected FalkorDB Graph object (from ``db.connection.get_graph()``).

    Notes
    -----
    The function is idempotent.  FalkorDB does not raise an error when an
    index already exists, so this can be called safely on every start-up.
    """
    created: list[str] = []
    skipped: list[str] = []

    for label, prop in _INDEXES:
        cypher = f"CREATE INDEX FOR (n:{label}) ON (n.{prop})"
        try:
            graph.query(cypher)
            created.append(f"{label}.{prop}")
            logger.debug("Index created (or already exists): %s.%s", label, prop)
        except Exception as exc:
            # FalkorDB may raise if the index already exists in some versions;
            # treat that as a harmless skip rather than a fatal error.
            error_msg = str(exc).lower()
            if "already" in error_msg or "exist" in error_msg:
                skipped.append(f"{label}.{prop}")
                logger.debug("Index already exists, skipping: %s.%s", label, prop)
            else:
                logger.error(
                    "Failed to create index for %s.%s: %s", label, prop, exc
                )
                raise

    logger.info(
        "Schema setup complete. Created: %d index(es), skipped (already exist): %d.",
        len(created),
        len(skipped),
    )
    print(
        f"[schema] Indexes processed — created/confirmed: {len(created)}, "
        f"skipped (already existed): {len(skipped)}."
    )
