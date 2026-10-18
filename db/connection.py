"""EchoForge — FalkorDB connection factory.

Reads connection settings from environment variables (with defaults) and
exposes two public helpers:

* ``get_graph()``  — returns a connected FalkorDB Graph object.
* ``test_connection()`` — returns True if FalkorDB is reachable, False otherwise.
"""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_FALKORDB_HOST: str = os.getenv("FALKORDB_HOST", "localhost")
_FALKORDB_PORT: int = int(os.getenv("FALKORDB_PORT", "6379"))
_FALKORDB_GRAPH_NAME: str = os.getenv("FALKORDB_GRAPH_NAME", "echoforge")


def get_graph():
    """Return a connected FalkorDB Graph object for the configured graph name.

    Raises
    ------
    ConnectionError
        If FalkorDB cannot be reached at the configured host/port.
    """
    try:
        import falkordb  # local import to surface missing-package errors clearly

        client = falkordb.FalkorDB(host=_FALKORDB_HOST, port=_FALKORDB_PORT)
        graph = client.select_graph(_FALKORDB_GRAPH_NAME)
        return graph
    except ImportError as exc:
        raise ImportError(
            "The 'falkordb' package is not installed. "
            "Run: pip install falkordb>=1.0.0"
        ) from exc
    except Exception as exc:
        raise ConnectionError(
            f"Could not connect to FalkorDB at {_FALKORDB_HOST}:{_FALKORDB_PORT}. "
            "Ensure FalkorDB is running and FALKORDB_HOST / FALKORDB_PORT are set "
            "correctly in your .env file. "
            f"Original error: {exc}"
        ) from exc


def test_connection() -> bool:
    """Ping FalkorDB by running a trivial query.

    Returns
    -------
    bool
        True if the connection succeeds, False otherwise.
    """
    try:
        graph = get_graph()
        result = graph.query("RETURN 1 AS ping")
        # Verify we got a result back
        records = list(result.result_set) if result.result_set is not None else []
        logger.info("FalkorDB connection OK (graph=%s)", _FALKORDB_GRAPH_NAME)
        return len(records) > 0
    except Exception as exc:
        logger.error("FalkorDB connection test failed: %s", exc)
        return False
