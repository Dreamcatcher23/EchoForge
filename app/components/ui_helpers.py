"""EchoForge — Reusable Streamlit UI helper functions.

Provides small, composable display primitives used across all pages of the
EchoForge application.  All functions depend only on :mod:`streamlit` — no
FalkorDB calls are made here.
"""

from __future__ import annotations

from datetime import datetime


# ---------------------------------------------------------------------------
# Status badges
# ---------------------------------------------------------------------------

_STATUS_COLORS: dict[str, str] = {
    # branch / pipeline statuses
    "active": "#27AE60",
    "archived": "#7F8C8D",
    "draft": "#F39C12",
    "completed": "#27AE60",
    "failed": "#E74C3C",
    "pending": "#F39C12",
    "running": "#3498DB",
    # evaluation statuses
    "supported": "#27AE60",
    "contradicted": "#E74C3C",
    "inconclusive": "#F39C12",
    # node type badges
    "actual": "#2980B9",
    "hypothetical": "#8E44AD",
    "prediction": "#16A085",
    "observed": "#D35400",
}

_STATUS_EMOJIS: dict[str, str] = {
    "active": "🟢",
    "archived": "🗄️",
    "draft": "✏️",
    "completed": "✅",
    "failed": "❌",
    "pending": "⏳",
    "running": "⚙️",
    "supported": "🟢",
    "contradicted": "🔴",
    "inconclusive": "🟡",
    "actual": "📜",
    "hypothetical": "🔀",
    "prediction": "🔮",
    "observed": "👁️",
}


def status_badge(status: str) -> str:
    """Return a colored markdown string for a given status value.

    Parameters
    ----------
    status:
        Status string such as ``"active"``, ``"supported"``, ``"failed"``.

    Returns
    -------
    str
        An HTML/markdown span with background color and the status emoji + text.
    """
    key = (status or "").lower().strip()
    color = _STATUS_COLORS.get(key, "#7F8C8D")
    emoji = _STATUS_EMOJIS.get(key, "●")
    return (
        f'<span style="background-color:{color};color:#FFF;'
        f'padding:2px 8px;border-radius:12px;font-size:0.82em;'
        f'font-weight:600;">{emoji} {status.upper()}</span>'
    )


# ---------------------------------------------------------------------------
# Datetime formatting
# ---------------------------------------------------------------------------

def format_datetime(iso_string: str | None) -> str:
    """Convert an ISO-8601 datetime string to a human-readable format.

    Parameters
    ----------
    iso_string:
        ISO-8601 timestamp string, e.g. ``"2024-03-15T10:30:00+00:00"``.

    Returns
    -------
    str
        Formatted string like ``"Mar 15, 2024 10:30 UTC"``, or ``"—"`` if
        *iso_string* is falsy or unparseable.
    """
    if not iso_string:
        return "—"
    # FalkorDB sometimes stores partial ISO strings; normalise them
    clean = str(iso_string).replace("Z", "+00:00")
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(clean, fmt)
            return dt.strftime("%b %d, %Y %H:%M UTC")
        except ValueError:
            continue
    return str(iso_string)


# ---------------------------------------------------------------------------
# Metrics row
# ---------------------------------------------------------------------------

def render_metrics_row(metrics: list[dict]) -> None:
    """Render a horizontal row of ``st.metric`` widgets.

    Parameters
    ----------
    metrics:
        List of dicts, each with keys:
        * ``label`` (str) — metric label.
        * ``value`` (str | int | float) — metric value.
        * ``delta`` (str | int | float, optional) — change indicator.
    """
    import streamlit as st

    if not metrics:
        return
    cols = st.columns(len(metrics))
    for col, m in zip(cols, metrics):
        with col:
            st.metric(
                label=m.get("label", ""),
                value=m.get("value", "—"),
                delta=m.get("delta"),
            )


# ---------------------------------------------------------------------------
# Evidence card
# ---------------------------------------------------------------------------

def render_evidence_card(evidence: dict) -> None:
    """Render a single evidence node as a styled ``st.container``.

    Parameters
    ----------
    evidence:
        Dict with keys: ``id``, ``content``, ``source``, ``created_at``, and
        optionally ``via`` (``"direct"`` | ``"via_project"``).
    """
    import streamlit as st

    eid = evidence.get("id", "—")
    content = evidence.get("content", "No content available.")
    source = evidence.get("source", "—")
    created_at = format_datetime(evidence.get("created_at"))
    via = evidence.get("via", "direct")
    via_icon = "🔗" if via == "via_project" else "📎"

    with st.container(border=True):
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(f"**🔎 {eid}**")
            st.write(content)
        with col2:
            st.caption(f"Source: **{source}**")
            st.caption(f"Date: {created_at}")
            st.caption(f"{via_icon} {via.replace('_', ' ').title()}")


# ---------------------------------------------------------------------------
# Prediction card
# ---------------------------------------------------------------------------

def render_prediction_card(prediction: dict) -> None:
    """Render a prediction with a confidence progress bar and status badge.

    Parameters
    ----------
    prediction:
        Dict with keys: ``id``, ``content``, ``confidence`` (float 0-1),
        ``status``, and optionally ``created_at``.
    """
    import streamlit as st

    pid = prediction.get("id", "—")
    content = prediction.get("content", "No prediction content.")
    confidence_raw = prediction.get("confidence")
    status = prediction.get("status", "pending")
    created_at = format_datetime(prediction.get("created_at"))

    try:
        confidence = float(confidence_raw) if confidence_raw is not None else 0.0
    except (TypeError, ValueError):
        confidence = 0.0

    conf_pct = int(confidence * 100)
    conf_label = (
        "High 🟢" if confidence >= 0.8
        else "Medium 🟡" if confidence >= 0.5
        else "Low 🔴"
    )

    with st.container(border=True):
        col1, col2 = st.columns([4, 1])
        with col1:
            st.markdown(f"**🔮 {pid}**")
            st.write(content)
            st.progress(confidence, text=f"Confidence: {conf_pct}% ({conf_label})")
        with col2:
            st.markdown(status_badge(status), unsafe_allow_html=True)
            st.caption(f"Created: {created_at}")


# ---------------------------------------------------------------------------
# Agent run summary card
# ---------------------------------------------------------------------------

def render_agent_run_summary(run: dict) -> None:
    """Render a compact agent run card with an expandable JSON detail section.

    Parameters
    ----------
    run:
        Dict with keys: ``id``, ``agent_type``, ``started_at``, ``status``,
        ``summary``, and optionally ``input_data`` / ``output_data`` (JSON str).
    """
    import json
    import streamlit as st

    run_id = run.get("id", "—")
    agent_type = run.get("agent_type", "—")
    started = format_datetime(run.get("started_at"))
    completed = format_datetime(run.get("completed_at"))
    status = run.get("status", "—")
    summary = run.get("summary", "—")

    with st.expander(
        f"🤖 {agent_type.upper()} — {run_id} · {started} · "
        + ("✅" if status == "completed" else "❌")
    ):
        st.markdown(status_badge(status), unsafe_allow_html=True)
        st.write(f"**Summary:** {summary}")
        st.caption(f"Started: {started}  |  Completed: {completed}")

        input_raw = run.get("input_data", "")
        output_raw = run.get("output_data", "")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Input Data**")
            try:
                parsed = json.loads(input_raw) if input_raw else {}
                st.json(parsed, expanded=False)
            except (ValueError, TypeError):
                st.code(str(input_raw or "{}"))

        with col2:
            st.markdown("**Output Data**")
            try:
                parsed = json.loads(output_raw) if output_raw else {}
                st.json(parsed, expanded=False)
            except (ValueError, TypeError):
                st.code(str(output_raw or "{}"))


# ---------------------------------------------------------------------------
# Fictional data disclaimer
# ---------------------------------------------------------------------------

def fictional_disclaimer() -> None:
    """Render the fictional data disclaimer in small italic text."""
    import streamlit as st

    st.markdown(
        "<p style='font-size:0.78em;color:#7F8C8D;font-style:italic;'>"
        "⚠️ All organizational data shown (NovaTech Systems, decisions, people, "
        "projects) is fictional and created solely for demonstration purposes."
        "</p>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Connection status banner
# ---------------------------------------------------------------------------

def db_warning_banner() -> None:
    """Render a prominent warning banner when FalkorDB is not connected."""
    import streamlit as st

    st.warning(
        "⚠️ **FalkorDB is not connected.** "
        "Start FalkorDB (e.g. `docker-compose up -d falkordb`) and refresh the page. "
        "All data panels will show empty states until the connection is restored.",
        icon="🔌",
    )


# ---------------------------------------------------------------------------
# Empty-state helper
# ---------------------------------------------------------------------------

def empty_state(message: str = "No data available.", icon: str = "📭") -> None:
    """Display a centred empty-state message.

    Parameters
    ----------
    message:
        Human-readable message to display.
    icon:
        Emoji icon to prefix the message.
    """
    import streamlit as st

    st.info(f"{icon} {message}")
