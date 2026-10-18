"""EchoForge — Counterfactual Decision Lab.

Full Streamlit multi-page application.  All seven pages are rendered from a
single sidebar-navigated script.

Pages
-----
1. 🏠 Dashboard
2. 🔍 Decision Inspector
3. 🌿 Scenario Creator
4. ⚖️ Comparison View
5. 📊 Predictions & Evidence
6. 🤖 Agent History
7. ✅ Outcome Evaluation

Design rules
------------
* ``@st.cache_resource`` caches the FalkorDB graph connection.
* Every DB call is wrapped in try/except; ``st.error`` is shown on failure.
* A warning banner appears on every page when FalkorDB is offline.
* No hardcoded data values — everything comes from FalkorDB queries.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import date

# Ensure the project root is on sys.path so that `app`, `db`, `agents`, and
# `core` packages are importable regardless of how Streamlit resolves paths.
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import streamlit as st

# ---------------------------------------------------------------------------
# Page config (must be the FIRST Streamlit call)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="EchoForge",
    page_icon="🔀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Internal imports (after page config)
# ---------------------------------------------------------------------------

from app.components.graph_viz import (
    render_branch_comparison_graph,
    render_decision_graph,
    render_full_knowledge_graph,
)
from app.components.ui_helpers import (
    db_warning_banner,
    empty_state,
    fictional_disclaimer,
    format_datetime,
    render_agent_run_summary,
    render_evidence_card,
    render_metrics_row,
    render_prediction_card,
    status_badge,
)

# ---------------------------------------------------------------------------
# FalkorDB connection — cached at session level
# ---------------------------------------------------------------------------


@st.cache_resource(show_spinner="Connecting to FalkorDB…")
def _get_graph():
    """Return a cached FalkorDB Graph object or None on failure."""
    try:
        from db.connection import get_graph
        return get_graph()
    except Exception as exc:
        return None


def _is_connected(graph) -> bool:
    if graph is None:
        return False
    try:
        graph.query("RETURN 1 AS ping")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------

PAGES = [
    "🏠 Dashboard",
    "🔍 Decision Inspector",
    "🌿 Scenario Creator",
    "⚖️ Comparison View",
    "📊 Predictions & Evidence",
    "🤖 Agent History",
    "✅ Outcome Evaluation",
]

with st.sidebar:
    st.title("🔀 EchoForge")
    st.caption("Counterfactual Decision Lab")
    st.divider()
    page = st.radio("Navigation", PAGES, label_visibility="collapsed")
    st.divider()
    fictional_disclaimer()
    st.caption("Phase 4 · FalkorDB + PyVis")

# ---------------------------------------------------------------------------
# Resolve graph & connection status
# ---------------------------------------------------------------------------

graph = _get_graph()
connected = _is_connected(graph)

# ---------------------------------------------------------------------------
# ═══════════════════════════════════════════════════════════════════════════
# PAGE 1 — Dashboard
# ═══════════════════════════════════════════════════════════════════════════
# ---------------------------------------------------------------------------

if page == "🏠 Dashboard":
    st.title("🏠 EchoForge Dashboard")
    fictional_disclaimer()

    # ── Connection banner ─────────────────────────────────────────────────
    if not connected:
        db_warning_banner()
    else:
        # Auto-initialise schema and seed on first load
        col_status, col_seed = st.columns([3, 1])
        with col_status:
            st.success("✅ Connected to FalkorDB")
        with col_seed:
            if st.button("🌱 Re-seed Database", use_container_width=True):
                try:
                    from db.schema import create_schema
                    from db.seed import seed_database
                    create_schema(graph)
                    seed_database(graph)
                    st.cache_resource.clear()
                    st.rerun()
                except Exception as exc:
                    st.error(f"Seed failed: {exc}")

        # Auto-create schema silently
        try:
            from db.schema import create_schema
            from db.seed import seed_database
            create_schema(graph)
            seed_database(graph)
        except Exception:
            pass  # Already seeded or non-fatal

    # ── Summary metrics ───────────────────────────────────────────────────
    st.subheader("📊 Summary Metrics")

    total_decisions = 0
    total_projects = 0
    total_branches = 0
    total_agent_runs = 0
    decisions = []
    recent_runs = []

    if connected:
        try:
            from db.history import get_actual_decisions
            decisions = get_actual_decisions(graph)
            total_decisions = len(decisions)
        except Exception as exc:
            st.error(f"Failed to load decisions: {exc}")

        try:
            proj_result = graph.query(
                "MATCH (p:Project) RETURN count(p) AS total"
            )
            if proj_result and proj_result.result_set:
                total_projects = proj_result.result_set[0][0] or 0
        except Exception:
            pass

        try:
            from db.branch_service import list_branches
            branches = list_branches(graph)
            total_branches = len(branches)
        except Exception as exc:
            st.error(f"Failed to load branches: {exc}")

        try:
            from db.queries import get_agent_runs
            all_runs = get_agent_runs(graph)
            total_agent_runs = len(all_runs)
            recent_runs = all_runs[-5:] if all_runs else []
        except Exception as exc:
            st.error(f"Failed to load agent runs: {exc}")

    render_metrics_row([
        {"label": "Actual Decisions", "value": total_decisions},
        {"label": "Projects Affected", "value": total_projects},
        {"label": "Scenario Branches", "value": total_branches},
        {"label": "Agent Runs", "value": total_agent_runs},
    ])

    st.divider()

    # ── Decision history table ────────────────────────────────────────────
    st.subheader("📋 Decision History")
    if decisions:
        import pandas as pd
        df = pd.DataFrame(decisions)
        display_cols = [c for c in ["id", "title", "made_at", "is_actual"] if c in df.columns]
        if "made_at" in df.columns:
            df["made_at"] = df["made_at"].apply(format_datetime)
        st.dataframe(df[display_cols], use_container_width=True, hide_index=True)
    else:
        empty_state("No decisions found. Connect to FalkorDB and seed the database.")

    # ── Recent agent runs expander ────────────────────────────────────────
    if recent_runs:
        with st.expander("🤖 Recent Agent Runs", expanded=False):
            for run in recent_runs:
                render_agent_run_summary(run)

    # ── Knowledge graph overview ──────────────────────────────────────────
    if connected:
        st.subheader("🌐 Knowledge Graph Overview")
        render_full_knowledge_graph(graph, height="500px")

# ---------------------------------------------------------------------------
# ═══════════════════════════════════════════════════════════════════════════
# PAGE 2 — Decision Inspector
# ═══════════════════════════════════════════════════════════════════════════
# ---------------------------------------------------------------------------

elif page == "🔍 Decision Inspector":
    st.title("🔍 Decision Inspector")
    fictional_disclaimer()

    if not connected:
        db_warning_banner()

    decisions = []
    if connected:
        try:
            from db.history import get_actual_decisions
            decisions = get_actual_decisions(graph)
        except Exception as exc:
            st.error(f"Failed to load decisions: {exc}")

    if not decisions:
        empty_state("No decisions available. Ensure FalkorDB is connected and seeded.")
        st.stop()

    decision_options = {f"{d['id']} — {d.get('title', '')}": d["id"] for d in decisions}
    selected_label = st.selectbox("Select a Decision", list(decision_options.keys()))
    selected_id = decision_options[selected_label]

    # ── Decision details ──────────────────────────────────────────────────
    decision = None
    try:
        from db.queries import get_decision_by_id
        decision = get_decision_by_id(graph, selected_id)
    except Exception as exc:
        st.error(f"Failed to load decision: {exc}")

    if decision:
        st.info(
            f"**{decision.get('title', '—')}**\n\n"
            f"{decision.get('description', '—')}\n\n"
            f"Made at: {format_datetime(decision.get('made_at'))} · "
            f"Actual: {'✅' if decision.get('is_actual') else '❌'}"
        )

    # ── Evidence ──────────────────────────────────────────────────────────
    evidence = []
    try:
        from db.traversal import get_evidence_chain
        evidence = get_evidence_chain(graph, selected_id)
    except Exception as exc:
        st.error(f"Failed to load evidence: {exc}")

    with st.expander(f"🔎 Evidence ({len(evidence)} items)", expanded=False):
        if evidence:
            for ev in evidence:
                render_evidence_card(ev)
        else:
            empty_state("No evidence linked to this decision.")

    # ── Affected entities ─────────────────────────────────────────────────
    affected = []
    try:
        from db.traversal import get_affected_entities
        affected = get_affected_entities(graph, selected_id)
    except Exception as exc:
        st.error(f"Failed to load affected entities: {exc}")

    st.subheader(f"🎯 Affected Entities ({len(affected)})")
    if affected:
        import pandas as pd
        adf = pd.DataFrame(affected)
        display_cols = [c for c in ["id", "label", "name", "depth"] if c in adf.columns]
        try:
            # pandas >= 2.1 renamed applymap → map
            styled = adf[display_cols].style.map(
                lambda v: "color: #4A90D9; font-weight: bold;"
                if isinstance(v, str) and v.startswith("DEC") else "",
                subset=["id"] if "id" in display_cols else [],
            )
        except AttributeError:
            styled = adf[display_cols]
        st.dataframe(styled, use_container_width=True, hide_index=True)
    else:
        empty_state("No affected entities found.")

    # ── Impact summary ────────────────────────────────────────────────────
    impact = {}
    try:
        from db.traversal import get_impact_summary
        impact = get_impact_summary(graph, selected_id)
    except Exception as exc:
        st.error(f"Failed to load impact summary: {exc}")

    if impact:
        render_metrics_row([
            {"label": "Total Affected", "value": impact.get("total_affected_count", 0)},
            {"label": "Projects (depth-1)", "value": len(impact.get("directly_affected_projects", []))},
            {"label": "People (depth-1)", "value": len(impact.get("directly_affected_people", []))},
            {"label": "Max Depth", "value": impact.get("max_depth_reached", 0)},
        ])

    # ── Interactive graph ─────────────────────────────────────────────────
    st.subheader("🌐 Decision Graph")
    render_decision_graph(graph, selected_id, height="500px")

    # ── Navigate to scenario creator ─────────────────────────────────────
    st.divider()
    if st.button("🌿 Create Hypothetical Branch from this Decision"):
        st.session_state["branch_source_decision_id"] = selected_id
        st.session_state["branch_source_decision_label"] = selected_label
        st.info(f"Switched to Scenario Creator with decision **{selected_id}** pre-selected.")

# ---------------------------------------------------------------------------
# ═══════════════════════════════════════════════════════════════════════════
# PAGE 3 — Scenario Creator
# ═══════════════════════════════════════════════════════════════════════════
# ---------------------------------------------------------------------------

elif page == "🌿 Scenario Creator":
    st.title("🌿 Scenario Creator")
    fictional_disclaimer()

    if not connected:
        db_warning_banner()

    decisions = []
    if connected:
        try:
            from db.history import get_actual_decisions
            decisions = get_actual_decisions(graph)
        except Exception as exc:
            st.error(f"Failed to load decisions: {exc}")

    if not decisions:
        empty_state("No decisions available. Ensure FalkorDB is connected and seeded.")
        st.stop()

    decision_options = {f"{d['id']} — {d.get('title', '')}": d["id"] for d in decisions}

    # Pre-select if navigated from Inspector
    pre_selected = st.session_state.get("branch_source_decision_label")
    default_idx = 0
    if pre_selected and pre_selected in decision_options:
        default_idx = list(decision_options.keys()).index(pre_selected)

    selected_label = st.selectbox(
        "Source Decision", list(decision_options.keys()), index=default_idx
    )
    selected_id = decision_options[selected_label]

    col1, col2 = st.columns(2)
    with col1:
        branch_name = st.text_input(
            "Branch Name",
            value="",
            placeholder="e.g. Delayed Hiring Scenario",
        )
    with col2:
        branch_desc = st.text_area(
            "Description",
            value="",
            placeholder="Describe what this hypothetical branch is testing…",
            height=100,
        )

    # ── Dynamic assumptions form ──────────────────────────────────────────
    st.subheader("🔄 Changed Assumptions")
    if "assumption_count" not in st.session_state:
        st.session_state["assumption_count"] = 1

    assumptions: list[dict] = []
    for i in range(st.session_state["assumption_count"]):
        st.markdown(f"**Assumption {i + 1}**")
        a_col1, a_col2, a_col3 = st.columns(3)
        with a_col1:
            field = st.text_input(
                "Field / Parameter", key=f"assumption_field_{i}",
                placeholder="e.g. budget"
            )
        with a_col2:
            original = st.text_input(
                "Original Value", key=f"assumption_original_{i}",
                placeholder="e.g. $500K"
            )
        with a_col3:
            new_val = st.text_input(
                "New Value", key=f"assumption_new_{i}",
                placeholder="e.g. $250K"
            )
        if field:
            assumptions.append(
                {"field": field, "original_value": original, "new_value": new_val}
            )

    if st.button("➕ Add Another Assumption"):
        st.session_state["assumption_count"] += 1
        st.rerun()

    st.divider()

    # ── Create branch ─────────────────────────────────────────────────────
    branch_result: dict | None = None
    if st.button("🌿 Create Branch", type="primary", disabled=not connected):
        if not branch_name.strip():
            st.warning("Branch Name is required.")
        elif not assumptions:
            st.warning("Add at least one changed assumption.")
        else:
            try:
                from db.branch_service import create_branch
                with st.spinner("Creating branch in FalkorDB…"):
                    branch_result = create_branch(
                        graph,
                        source_decision_id=selected_id,
                        branch_name=branch_name.strip(),
                        description=branch_desc.strip(),
                        changed_assumptions=assumptions,
                    )
                new_branch_id = branch_result.get("branch", {}).get("id", "—")
                st.success(f"✅ Branch created! ID: **{new_branch_id}**")
                st.session_state["last_created_branch_id"] = new_branch_id
                st.session_state["assumption_count"] = 1
                # cache clear so new branch shows up everywhere
                st.cache_resource.clear()
            except Exception as exc:
                st.error(f"Failed to create branch: {exc}")

    # ── Run scenario analysis ─────────────────────────────────────────────
    st.subheader("🤖 Run Scenario Analysis")
    branch_id_for_run = st.session_state.get("last_created_branch_id", "")
    branch_id_input = st.text_input(
        "Branch ID to analyse",
        value=branch_id_for_run,
        placeholder="e.g. BRANCH-XXXXXXXX",
    )

    if st.button("▶️ Run Scenario Analysis", disabled=not connected):
        if not branch_id_input.strip():
            st.warning("Enter a Branch ID.")
        else:
            try:
                from agents.coordinator import run_scenario_pipeline
                with st.spinner("Running ScenarioAgent → CriticAgent…"):
                    result = run_scenario_pipeline(graph, branch_id_input.strip(), selected_id)

                st.success(
                    f"Pipeline completed — coordinator run: "
                    f"**{result.get('coordinator_run_id', '—')}**"
                )

                scenario = result.get("scenario_result", {})
                critique = result.get("critique_result", {})

                with st.expander("🔮 ScenarioAgent Results"):
                    st.json(scenario)
                with st.expander("🧐 CriticAgent Results"):
                    st.json(critique)

            except Exception as exc:
                st.error(f"Scenario pipeline failed: {exc}")

# ---------------------------------------------------------------------------
# ═══════════════════════════════════════════════════════════════════════════
# PAGE 4 — Comparison View
# ═══════════════════════════════════════════════════════════════════════════
# ---------------------------------------------------------------------------

elif page == "⚖️ Comparison View":
    st.title("⚖️ Comparison View")
    fictional_disclaimer()

    if not connected:
        db_warning_banner()

    decisions = []
    branches = []

    if connected:
        try:
            from db.history import get_actual_decisions
            decisions = get_actual_decisions(graph)
        except Exception as exc:
            st.error(f"Failed to load decisions: {exc}")

        try:
            from db.branch_service import list_branches
            branches = list_branches(graph)
        except Exception as exc:
            st.error(f"Failed to load branches: {exc}")

    if not decisions or not branches:
        empty_state(
            "Comparison requires at least one actual decision and one branch. "
            "Go to Scenario Creator to create a branch first."
        )
        st.stop()

    dec_options = {f"{d['id']} — {d.get('title', '')}": d["id"] for d in decisions}
    branch_options = {
        f"{b['id']} — {b.get('name', '')}": b["id"] for b in branches
    }

    col_sel1, col_sel2 = st.columns(2)
    with col_sel1:
        sel_dec_label = st.selectbox("Actual Decision", list(dec_options.keys()))
        sel_dec_id = dec_options[sel_dec_label]
    with col_sel2:
        sel_branch_label = st.selectbox("Hypothetical Branch", list(branch_options.keys()))
        sel_branch_id = branch_options[sel_branch_label]

    comparison: dict | None = None
    display: dict | None = None

    try:
        from core.comparison import compare_decision_to_branch, format_comparison_for_display
        with st.spinner("Loading comparison…"):
            comparison = compare_decision_to_branch(graph, sel_dec_id, sel_branch_id)
            display = format_comparison_for_display(comparison)
    except Exception as exc:
        st.error(f"Comparison failed: {exc}")

    if not display:
        st.stop()

    actual_panel = display.get("actual_panel", {})
    hyp_panel = display.get("hypothetical_panel", {})
    diff_panel = display.get("diff_panel", {})

    # ── Two-column layout ─────────────────────────────────────────────────
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("📜 Actual History")
        st.markdown(status_badge("ACTUAL"), unsafe_allow_html=True)
        st.markdown(f"**{actual_panel.get('title', '—')}**")
        st.write(actual_panel.get("description", "—"))
        st.caption(
            f"Made: {format_datetime(actual_panel.get('made_at'))} · "
            f"{actual_panel.get('evidence_count', 0)} evidence item(s) · "
            f"{actual_panel.get('affected_count', 0)} affected node(s)"
        )

        outcome_summary = actual_panel.get("outcome_summary", "No outcome recorded")
        if outcome_summary and outcome_summary != "No outcome recorded":
            st.markdown(status_badge("OBSERVED"), unsafe_allow_html=True)
            st.write(outcome_summary)
        else:
            st.caption("_No actual outcome recorded yet._")

        with st.expander("🔎 Evidence Items"):
            for ev in actual_panel.get("evidence_items", []):
                st.markdown(f"- **{ev.get('id')}**: {ev.get('summary')} *(source: {ev.get('source')})*")
            if not actual_panel.get("evidence_items"):
                empty_state("No evidence.")

        with st.expander("🎯 Affected Entities"):
            for en in actual_panel.get("affected_entities", []):
                st.markdown(
                    f"- {en.get('type_icon', '●')} **{en.get('display_name')}** "
                    f"(depth {en.get('depth', '—')})"
                )
            if not actual_panel.get("affected_entities"):
                empty_state("No affected entities.")

    with col_right:
        st.subheader("🔀 Hypothetical Branch")
        st.markdown(status_badge("HYPOTHETICAL"), unsafe_allow_html=True)
        st.markdown(f"**{hyp_panel.get('branch_name', '—')}**")
        st.write(hyp_panel.get("description", "—"))
        st.caption(
            f"Created: {format_datetime(hyp_panel.get('created_at'))} · "
            f"{hyp_panel.get('assumptions_count', 0)} assumption(s) · "
            f"{hyp_panel.get('predictions_count', 0)} prediction(s)"
        )

        with st.expander("🔄 Changed Assumptions"):
            for a in hyp_panel.get("assumption_items", []):
                st.markdown(
                    f"- **{a.get('field')}**: `{a.get('from')}` → `{a.get('to')}`"
                )
            if not hyp_panel.get("assumption_items"):
                empty_state("No changed assumptions.")

        with st.expander("🔮 Predictions"):
            for p in hyp_panel.get("prediction_items", []):
                conf = p.get("confidence_label", "—")
                st.markdown(
                    f"- {p.get('content')} · {conf}"
                )
                st.markdown(status_badge("PREDICTION"), unsafe_allow_html=True)
            if not hyp_panel.get("prediction_items"):
                empty_state("No predictions — run scenario analysis first.")

        with st.expander("🎯 Hypothetical Affected Entities"):
            for en in hyp_panel.get("affected_entities", []):
                st.markdown(
                    f"- {en.get('type_icon', '●')} **{en.get('display_name')}** "
                    f"(depth {en.get('depth', '—')})"
                )
            if not hyp_panel.get("affected_entities"):
                empty_state("No affected entities.")

    # ── Diff panel ────────────────────────────────────────────────────────
    st.divider()
    st.subheader(f"🔍 Impact Diff  —  {diff_panel.get('summary_line', '')}")

    d1, d2, d3 = st.columns(3)
    with d1:
        st.markdown("#### 🟢 Added Impacts")
        for n in diff_panel.get("added_impacts", []):
            st.markdown(
                f"➕ **{n.get('display_name', n.get('id', '—'))}** "
                f"({n.get('label', '—')})"
            )
        if not diff_panel.get("added_impacts"):
            empty_state("No added impacts.")
    with d2:
        st.markdown("#### 🔴 Removed Impacts")
        for n in diff_panel.get("removed_impacts", []):
            st.markdown(
                f"➖ **{n.get('display_name', n.get('id', '—'))}** "
                f"({n.get('label', '—')})"
            )
        if not diff_panel.get("removed_impacts"):
            empty_state("No removed impacts.")
    with d3:
        st.markdown("#### ⚪ Assumption Changes")
        for a in diff_panel.get("assumption_changes", []):
            st.markdown(
                f"🔄 **{a.get('field')}**: `{a.get('from')}` → `{a.get('to')}`"
            )
        if not diff_panel.get("assumption_changes"):
            empty_state("No assumption changes.")

    # ── Branch comparison graph ───────────────────────────────────────────
    st.subheader("🌐 Branch Comparison Graph")
    render_branch_comparison_graph(graph, sel_dec_id, sel_branch_id, height="600px")

# ---------------------------------------------------------------------------
# ═══════════════════════════════════════════════════════════════════════════
# PAGE 5 — Predictions & Evidence
# ═══════════════════════════════════════════════════════════════════════════
# ---------------------------------------------------------------------------

elif page == "📊 Predictions & Evidence":
    st.title("📊 Predictions & Evidence")
    fictional_disclaimer()

    if not connected:
        db_warning_banner()

    branches = []
    if connected:
        try:
            from db.branch_service import list_branches
            branches = list_branches(graph)
        except Exception as exc:
            st.error(f"Failed to load branches: {exc}")

    if not branches:
        empty_state("No branches found. Create a branch in the Scenario Creator.")
    else:
        st.subheader("🔮 Predictions by Branch")
        for branch in branches:
            bid = branch.get("id", "—")
            bname = branch.get("name", bid)
            bstatus = branch.get("status", "—")

            with st.expander(
                f"{bid} — {bname}  "
                + ("🟢" if bstatus == "active" else "🗄️"),
                expanded=False,
            ):
                st.markdown(status_badge(bstatus), unsafe_allow_html=True)
                st.caption(branch.get("description", ""))

                preds = []
                try:
                    from db.queries import get_predictions_for_branch
                    preds = get_predictions_for_branch(graph, bid)
                except Exception as exc:
                    st.error(f"Failed to load predictions for {bid}: {exc}")

                if preds:
                    for pred in preds:
                        render_prediction_card(pred)
                else:
                    empty_state("No predictions for this branch. Run scenario analysis.")

    # ── All evidence panel ────────────────────────────────────────────────
    st.divider()
    st.subheader("🔎 All Evidence Nodes")

    evidence = []
    if connected:
        try:
            from db.history import get_actual_evidence
            evidence = get_actual_evidence(graph)
        except Exception as exc:
            st.error(f"Failed to load evidence: {exc}")

    if evidence:
        import pandas as pd
        edf = pd.DataFrame(evidence)
        display_cols = [c for c in ["id", "content", "source", "created_at"] if c in edf.columns]
        if "created_at" in edf.columns:
            edf["created_at"] = edf["created_at"].apply(format_datetime)
        st.dataframe(edf[display_cols], use_container_width=True, hide_index=True)
    else:
        empty_state("No evidence nodes found.")

    # ── Evidence–decision relationship graph ──────────────────────────────
    if connected and evidence:
        st.subheader("🌐 Evidence ↔ Decision Graph")
        render_full_knowledge_graph(graph, height="500px")

# ---------------------------------------------------------------------------
# ═══════════════════════════════════════════════════════════════════════════
# PAGE 6 — Agent History
# ═══════════════════════════════════════════════════════════════════════════
# ---------------------------------------------------------------------------

elif page == "🤖 Agent History":
    st.title("🤖 Agent History")
    fictional_disclaimer()

    if not connected:
        db_warning_banner()

    all_runs = []
    if connected:
        try:
            from db.queries import get_agent_runs
            all_runs = get_agent_runs(graph)
        except Exception as exc:
            st.error(f"Failed to load agent runs: {exc}")

    agent_types = sorted({r.get("agent_type", "unknown") for r in all_runs})
    filter_options = ["All"] + agent_types
    selected_type = st.selectbox("Filter by Agent Type", filter_options)

    filtered = (
        all_runs
        if selected_type == "All"
        else [r for r in all_runs if r.get("agent_type") == selected_type]
    )

    if filtered:
        import pandas as pd
        df_runs = pd.DataFrame(filtered)
        summary_cols = [c for c in ["id", "agent_type", "started_at", "status", "summary"] if c in df_runs.columns]
        if "started_at" in df_runs.columns:
            df_runs["started_at"] = df_runs["started_at"].apply(format_datetime)
        st.dataframe(df_runs[summary_cols], use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("📋 Run Details")
        for run in filtered:
            render_agent_run_summary(run)
    else:
        empty_state("No agent runs found. Run a scenario analysis to generate agent runs.")

    # ── Re-run pipeline ───────────────────────────────────────────────────
    st.divider()
    st.subheader("🔁 Re-run Pipeline")

    branches_rerun = []
    decisions_rerun = []
    if connected:
        try:
            from db.branch_service import list_branches
            from db.history import get_actual_decisions
            branches_rerun = list_branches(graph)
            decisions_rerun = get_actual_decisions(graph)
        except Exception:
            pass

    if branches_rerun and decisions_rerun:
        col_r1, col_r2 = st.columns(2)
        with col_r1:
            rerun_branch_opts = {
                f"{b['id']} — {b.get('name', '')}": b["id"]
                for b in branches_rerun
            }
            rerun_branch_label = st.selectbox(
                "Branch", list(rerun_branch_opts.keys()), key="rerun_branch"
            )
            rerun_branch_id = rerun_branch_opts[rerun_branch_label]
        with col_r2:
            rerun_dec_opts = {
                f"{d['id']} — {d.get('title', '')}": d["id"]
                for d in decisions_rerun
            }
            rerun_dec_label = st.selectbox(
                "Decision", list(rerun_dec_opts.keys()), key="rerun_decision"
            )
            rerun_dec_id = rerun_dec_opts[rerun_dec_label]

        if st.button("▶️ Re-run Pipeline", disabled=not connected):
            try:
                from agents.coordinator import run_scenario_pipeline
                with st.spinner("Running agents…"):
                    result = run_scenario_pipeline(graph, rerun_branch_id, rerun_dec_id)
                st.success(
                    f"Re-run completed — coordinator: **{result.get('coordinator_run_id', '—')}**"
                )
            except Exception as exc:
                st.error(f"Re-run failed: {exc}")
    else:
        empty_state("No branches/decisions available for re-run.")

# ---------------------------------------------------------------------------
# ═══════════════════════════════════════════════════════════════════════════
# PAGE 7 — Outcome Evaluation
# ═══════════════════════════════════════════════════════════════════════════
# ---------------------------------------------------------------------------

elif page == "✅ Outcome Evaluation":
    st.title("✅ Outcome Evaluation")
    fictional_disclaimer()

    if not connected:
        db_warning_banner()

    branches = []
    decisions = []
    if connected:
        try:
            from db.branch_service import list_branches
            branches = list_branches(graph)
        except Exception as exc:
            st.error(f"Failed to load branches: {exc}")
        try:
            from db.history import get_actual_decisions
            decisions = get_actual_decisions(graph)
        except Exception as exc:
            st.error(f"Failed to load decisions: {exc}")

    # ── Evaluate predictions against observed outcome ─────────────────────
    st.subheader("🧪 Evaluate Predictions")

    if branches and decisions:
        col_ev1, col_ev2 = st.columns(2)
        with col_ev1:
            branch_opts = {
                f"{b['id']} — {b.get('name', '')}": b["id"] for b in branches
            }
            sel_branch_label = st.selectbox(
                "Branch to Evaluate", list(branch_opts.keys()), key="eval_branch"
            )
            sel_branch_id = branch_opts[sel_branch_label]
        with col_ev2:
            dec_opts = {
                f"{d['id']} — {d.get('title', '')}": d["id"] for d in decisions
            }
            sel_dec_label = st.selectbox(
                "Reference Decision", list(dec_opts.keys()), key="eval_decision"
            )
            sel_dec_id = dec_opts[sel_dec_label]

        observed_text = st.text_area(
            "Observed Outcome Description",
            placeholder="Describe what actually happened in reality…",
            height=120,
        )
        observed_date = st.date_input("Observed Date", value=date.today())

        if st.button("📊 Evaluate Predictions", type="primary", disabled=not connected):
            if not observed_text.strip():
                st.warning("Enter an observed outcome description.")
            else:
                try:
                    from agents.coordinator import run_evaluation_pipeline
                    with st.spinner("Running OutcomeEvaluator…"):
                        eval_result = run_evaluation_pipeline(
                            graph,
                            branch_id=sel_branch_id,
                            decision_id=sel_dec_id,
                            observed_outcome=observed_text.strip(),
                        )
                    coord_run_id = eval_result.get("coordinator_run_id", "—")
                    evaluation = eval_result.get("evaluation_result", {})
                    st.success(f"Evaluation complete — coordinator run: **{coord_run_id}**")

                    # Show prediction evaluation results
                    evaluations = evaluation.get("evaluations", [])
                    if evaluations:
                        import pandas as pd
                        eval_df = pd.DataFrame(evaluations)
                        st.dataframe(eval_df, use_container_width=True, hide_index=True)

                        for ev_item in evaluations:
                            status = ev_item.get("status", "inconclusive")
                            pred_content = ev_item.get("prediction_content", "—")
                            st.markdown(
                                f"{status_badge(status)} {pred_content}",
                                unsafe_allow_html=True,
                            )
                    else:
                        with st.expander("🔍 Raw Evaluation Result"):
                            st.json(evaluation)

                except Exception as exc:
                    st.error(f"Evaluation pipeline failed: {exc}")
    else:
        empty_state(
            "Need at least one branch and one decision. "
            "Create them in the Scenario Creator first."
        )

    # ── Record an actual outcome ───────────────────────────────────────────
    st.divider()
    st.subheader("📝 Record Actual Outcome")

    with st.form("record_outcome_form"):
        out_id = st.text_input(
            "Outcome ID",
            value=f"OUT-{uuid.uuid4().hex[:8].upper()}",
            help="Unique identifier for this outcome node.",
        )
        out_desc = st.text_area(
            "Outcome Description",
            placeholder="Describe the real-world outcome…",
            height=100,
        )
        out_date = st.date_input("Observed Date", value=date.today(), key="record_out_date")

        link_decision = st.checkbox("Link to a Decision")
        link_dec_id = None
        if link_decision and decisions:
            link_dec_opts = {
                f"{d['id']} — {d.get('title', '')}": d["id"] for d in decisions
            }
            link_dec_label = st.selectbox(
                "Decision to link", list(link_dec_opts.keys()), key="link_dec"
            )
            link_dec_id = link_dec_opts[link_dec_label]

        submitted = st.form_submit_button("💾 Record Outcome", disabled=not connected)

    if submitted:
        if not out_desc.strip():
            st.warning("Outcome description is required.")
        else:
            try:
                from db.history import record_actual_outcome, link_outcome_to_decision
                outcome_data = {
                    "id": out_id.strip(),
                    "description": out_desc.strip(),
                    "observed_at": out_date.isoformat(),
                }
                saved = record_actual_outcome(graph, outcome_data)
                st.success(f"✅ Outcome recorded: **{saved.get('id', out_id)}**")

                if link_decision and link_dec_id:
                    link_outcome_to_decision(graph, saved.get("id", out_id), link_dec_id)
                    st.info(f"Linked to decision **{link_dec_id}**.")

            except Exception as exc:
                st.error(f"Failed to record outcome: {exc}")

    # ── Existing actual outcomes ───────────────────────────────────────────
    st.divider()
    st.subheader("📋 Existing Actual Outcomes")
    if connected:
        actual_outcomes = []
        try:
            from db.history import get_actual_outcomes
            actual_outcomes = get_actual_outcomes(graph)
        except Exception as exc:
            st.error(f"Failed to load outcomes: {exc}")

        if actual_outcomes:
            import pandas as pd
            odf = pd.DataFrame(actual_outcomes)
            display_cols = [c for c in ["id", "description", "observed_at", "is_actual"] if c in odf.columns]
            if "observed_at" in odf.columns:
                odf["observed_at"] = odf["observed_at"].apply(format_datetime)
            st.dataframe(odf[display_cols], use_container_width=True, hide_index=True)
        else:
            empty_state("No actual outcomes recorded yet.")
    else:
        empty_state("Connect to FalkorDB to view outcomes.")


# ---------------------------------------------------------------------------
# Global footer
# ---------------------------------------------------------------------------

st.sidebar.divider()
st.sidebar.caption(
    "EchoForge v0.4 · MIT Licence\n"
    "Built with FalkorDB, LangChain & Streamlit"
)
