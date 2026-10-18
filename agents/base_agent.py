"""EchoForge — Base agent class with persistent memory and shared FalkorDB state.

Every concrete agent inherits from :class:`BaseAgent`, which provides:

* Unique ``run_id`` generation per instantiation.
* LLM availability detection via the ``OPENAI_API_KEY`` environment variable.
* Persistent ``AgentRun`` node storage in FalkorDB through :func:`save_run`.
* Prior-run retrieval through :func:`get_prior_runs`.
* A thin :func:`_call_llm` wrapper around the OpenAI chat completion API.

Design rules
------------
* No shared mutable global state — all coordination happens via FalkorDB.
* ``load_dotenv()`` is called at module import time so environment variables
  are always available regardless of how the module is imported.
* All variable data travels via parameterized Cypher queries — no f-string
  injection of user data.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

import db.queries as queries

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base for all EchoForge agents.

    Provides graph access, ``AgentRun`` persistence, prior-run retrieval,
    and an LLM toggle.

    Attributes
    ----------
    agent_type:
        Class-level string identifying the agent kind; must be overridden by
        subclasses.  Used to filter ``AgentRun`` nodes in FalkorDB.
    graph:
        Connected FalkorDB Graph object injected at construction time.
    run_id:
        Unique identifier for this agent instantiation (``RUN-XXXXXXXX``).
    started_at:
        ISO-8601 UTC timestamp recorded when :meth:`run` is first called.
        ``None`` until the first :meth:`_mark_started` call.
    llm_available:
        ``True`` when ``OPENAI_API_KEY`` is set in the environment.
    """

    agent_type: str = "base"

    def __init__(self, graph) -> None:
        """Initialise the agent with a graph connection.

        Parameters
        ----------
        graph:
            A connected FalkorDB Graph object (from :func:`db.connection.get_graph`).
        """
        self.graph = graph
        self.run_id: str = f"RUN-{uuid.uuid4().hex[:8].upper()}"
        self.started_at: str | None = None
        self.llm_available: bool = self._check_llm()

    # ------------------------------------------------------------------
    # LLM detection
    # ------------------------------------------------------------------

    def _check_llm(self) -> bool:
        """Return ``True`` if ``OPENAI_API_KEY`` is set and non-empty.

        Returns
        -------
        bool
            ``True`` when the key is present in the environment.
        """
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        available = bool(key)
        logger.debug(
            "%s(%s): LLM available=%s", self.__class__.__name__, self.run_id, available
        )
        return available

    # ------------------------------------------------------------------
    # Timestamp helper
    # ------------------------------------------------------------------

    def _mark_started(self) -> str:
        """Record the start time of this run and return the ISO timestamp."""
        self.started_at = datetime.now(timezone.utc).isoformat()
        return self.started_at

    # ------------------------------------------------------------------
    # Persistent memory — prior runs
    # ------------------------------------------------------------------

    def get_prior_runs(self, limit: int = 5) -> list[dict]:
        """Query FalkorDB for the most recent ``AgentRun`` nodes of this type.

        Parameters
        ----------
        limit:
            Maximum number of prior runs to retrieve (default 5).

        Returns
        -------
        list[dict]
            Most recent ``AgentRun`` dicts ordered by ``started_at`` DESC.
            Returns an empty list if none exist or on query failure (logged).
        """
        try:
            runs = queries.get_agent_runs_by_type(
                self.graph, self.agent_type, limit=limit
            )
            logger.debug(
                "%s.get_prior_runs() -> %d prior run(s).",
                self.__class__.__name__,
                len(runs),
            )
            return runs
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "%s.get_prior_runs() failed (non-fatal): %s",
                self.__class__.__name__,
                exc,
            )
            return []

    # ------------------------------------------------------------------
    # Persistent memory — save run
    # ------------------------------------------------------------------

    def save_run(
        self,
        status: str,
        summary: str,
        input_data: dict,
        output_data: dict,
    ) -> dict:
        """Create or update an ``AgentRun`` node in FalkorDB.

        Parameters
        ----------
        status:
            Final run status string, e.g. ``"completed"`` or ``"failed"``.
        summary:
            Human-readable single-line description of the run outcome.
        input_data:
            Dict of inputs passed to :meth:`run`; serialised to JSON string.
        output_data:
            Dict of outputs produced by :meth:`run`; serialised to JSON string.

        Returns
        -------
        dict
            The saved ``AgentRun`` node properties.
        """
        completed_at = datetime.now(timezone.utc).isoformat()
        run_data: dict = {
            "id": self.run_id,
            "agent_type": self.agent_type,
            "started_at": self.started_at or completed_at,
            "completed_at": completed_at,
            "status": status,
            "summary": summary,
            "input_data": json.dumps(input_data, default=str),
            "output_data": json.dumps(output_data, default=str),
        }
        try:
            saved = queries.save_agent_run(self.graph, run_data)
            logger.info(
                "%s.save_run(%s): status=%s", self.__class__.__name__, self.run_id, status
            )
            return saved
        except Exception as exc:
            logger.error(
                "%s.save_run(%s) failed: %s", self.__class__.__name__, self.run_id, exc
            )
            raise

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    def _call_llm(self, prompt: str, system_prompt: str = "") -> str:
        """Call the OpenAI chat completion API.

        Parameters
        ----------
        prompt:
            The user-role message to send to the model.
        system_prompt:
            Optional system-role message; defaults to an empty string.

        Returns
        -------
        str
            The model's reply text.

        Raises
        ------
        RuntimeError
            On any OpenAI API exception, with the original error message
            embedded so callers can decide whether to fall back.
        """
        try:
            from openai import OpenAI  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "openai package is not installed. Install it with: pip install openai"
            ) from exc

        model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.3,
            )
            content = response.choices[0].message.content or ""
            logger.debug(
                "%s._call_llm(): model=%s, response_len=%d",
                self.__class__.__name__,
                model,
                len(content),
            )
            return content
        except Exception as exc:
            raise RuntimeError(
                f"LLM API call failed ({type(exc).__name__}): {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def run(self, **kwargs) -> dict:
        """Execute the agent.

        Must return a dict containing at least:

        * ``run_id`` — the unique run identifier
        * ``status`` — ``"completed"`` or ``"failed"``
        * ``output`` — agent-specific output payload
        """
