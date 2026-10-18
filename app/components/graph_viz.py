"""EchoForge — Graph visualization components using PyVis.

Renders interactive graph visualizations of FalkorDB data inside Streamlit
pages via ``streamlit.components.v1.html``.

All functions are safe to call when the graph is empty or unavailable — they
will display an ``st.info`` message rather than raise an exception.
"""

from __future__ import annotations

import os

import streamlit as st
import streamlit.components.v1 as components

# ---------------------------------------------------------------------------
# Node / edge color palette
# ---------------------------------------------------------------------------

NODE_COLORS: dict[str, str] = {
    "Decision": "#4A90D9",
    "Person": "#7ED321",
    "Project": "#F5A623",
    "Evidence": "#9B59B6",
    "ScenarioBranch": "#E74C3C",
    "Prediction": "#1ABC9C",
    "Outcome": "#F39C12",
    "AgentRun": "#95A5A6",
}

_DEFAULT_COLOR = "#BDC3C7"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_network(height: str = "500px", directed: bool = True):
    """Return a configured PyVis Network instance.

    Raises ImportError if pyvis is not installed.
    """
    try:
        from pyvis.network import Network
    except ImportError as exc:
        raise ImportError(
            "The 'pyvis' package is not installed. Run: pip install pyvis"
        ) from exc
    net = Network(
        height=height,
        width="100%",
        directed=directed,
        notebook=False,
        bgcolor="#1E1E1E",
        font_color="#FFFFFF",
    )
    net.set_options("""
    {
      "nodes": {
        "borderWidth": 2,
        "shadow": true,
        "font": {"size": 14, "color": "#FFFFFF"}
      },
      "edges": {
        "arrows": {"to": {"enabled": true, "scaleFactor": 0.8}},
        "color": {"color": "#7F8C8D", "highlight": "#ECF0F1"},
        "smooth": {"type": "curvedCW", "roundness": 0.2},
        "font": {"size": 10, "color": "#BDC3C7", "align": "middle"}
      },
      "physics": {
        "enabled": true,
        "stabilization": {"iterations": 150}
      },
      "interaction": {
        "hover": true,
        "tooltipDelay": 200
      }
    }
    """)
    return net


def _render_net(net, height: str = "500px") -> None:
    """Render PyVis network in Streamlit without writing to disk.

    Uses ``generate_html()`` when available (pyvis >= 0.3.2) so no temp file
    is ever created — avoids ``[Errno 28] No space left on device`` errors on
    systems with a full /tmp or %TEMP% partition.  Falls back to the temp-file
    path if ``generate_html`` is absent.
    """
    h_px = int(height.replace("px", "").strip()) if "px" in height else 500

    # --- in-memory path (preferred) ---
    if hasattr(net, "generate_html"):
        try:
            html_content = net.generate_html(notebook=False)
            components.html(html_content, height=h_px + 30, scrolling=False)
            return
        except Exception:
            pass  # fall through to disk path

    # --- disk path fallback (only if generate_html unavailable) ---
    tmp_path = None
    try:
        import tempfile as _tf
        with _tf.NamedTemporaryFile(
            delete=False, suffix=".html", mode="w", encoding="utf-8"
        ) as fh:
            tmp_path = fh.name
        net.save_graph(tmp_path)
        with open(tmp_path, "r", encoding="utf-8") as fh:
            html_content = fh.read()
        components.html(html_content, height=h_px + 30, scrolling=False)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _extract_header_keys(header) -> list[str]:
    """Extract column name strings from FalkorDB header.

    FalkorDB returns ``result.header`` as a list of ``(type_int, col_name)``
    tuples.  Older code used ``header[i]`` directly as dict keys, which
    crashes because a tuple is unhashable as a dict key in some contexts and
    because it's the wrong value anyway.  This helper always returns plain
    ``str`` column names.
    """
    keys: list[str] = []
    for col in header:
        if isinstance(col, (list, tuple)):
            keys.append(str(col[1]))
        else:
            keys.append(str(col))
    return keys


def _row_to_dict(keys: list[str], row) -> dict:
    """Convert one FalkorDB result row to a plain Python dict."""
    result_dict: dict = {}
    for i, key in enumerate(keys):
        val = row[i] if i < len(row) else None
        # FalkorDB Node objects expose their data via .properties
        if hasattr(val, "properties"):
            result_dict[key] = val.properties
        else:
            result_dict[key] = val
    return result_dict


def _result_to_list(result) -> list[dict]:
    """Convert a FalkorDB QueryResult to a list of plain Python dicts."""
    if result is None or result.result_set is None:
        return []
    try:
        header = result.header
    except Exception:
        return []
    try:
        keys = _extract_header_keys(header)
    except Exception:
        return []
    return [_row_to_dict(keys, row) for row in result.result_set]


# ---------------------------------------------------------------------------
# Public render functions
# ---------------------------------------------------------------------------

def render_decision_graph(graph, decision_id: str, height: str = "500px") -> None:
    """Render an interactive graph for a Decision and its direct neighbors.

    Queries FalkorDB for nodes reachable via ``AFFECTS``, ``SUPPORTED_BY``,
    and ``HAS_BRANCH`` from the given decision.  Nodes are colored by label.
    Edges are labeled with relationship type.

    Displays ``st.info`` if no data is available or ``pyvis`` is missing.

    Parameters
    ----------
    graph:
        Connected FalkorDB Graph object.
    decision_id:
        ``id`` of the Decision node to visualize.
    height:
        CSS height string for the network panel (default ``"500px"``).
    """
    try:
        net = _get_network(height=height)
    except ImportError as exc:
        st.warning(f"Graph visualization unavailable: {exc}")
        return

    try:
        # Fetch decision node itself
        dec_cypher = (
            "MATCH (d:Decision {id: $id}) "
            "RETURN d.id AS id, d.title AS title, labels(d)[0] AS label"
        )
        dec_result = graph.query(dec_cypher, {"id": decision_id})
        dec_rows = _result_to_list(dec_result)

        if not dec_rows:
            st.info("No graph data available for this decision.")
            return

        added_nodes: set[str] = set()

        for row in dec_rows:
            nid = row.get("id", decision_id)
            label = row.get("label", "Decision")
            title = row.get("title") or nid
            color = NODE_COLORS.get(label, _DEFAULT_COLOR)
            net.add_node(nid, label=f"[{label}]\n{title[:30]}", color=color,
                         title=f"{label}: {title}", size=25, shape="dot")
            added_nodes.add(nid)

        # Fetch neighbors via AFFECTS, SUPPORTED_BY, HAS_BRANCH
        neighbor_cypher = (
            "MATCH (d:Decision {id: $id})-[r]->(n) "
            "WHERE type(r) IN ['AFFECTS', 'SUPPORTED_BY', 'HAS_BRANCH'] "
            "RETURN d.id AS src, n.id AS dst, "
            "COALESCE(n.title, n.name, n.id) AS dst_name, "
            "labels(n)[0] AS dst_label, type(r) AS rel_type"
        )
        nb_result = graph.query(neighbor_cypher, {"id": decision_id})
        nb_rows = _result_to_list(nb_result)

        for row in nb_rows:
            dst = row.get("dst")
            if not dst:
                continue
            dst_label = row.get("dst_label", "Node")
            dst_name = (row.get("dst_name") or dst)[:30]
            color = NODE_COLORS.get(dst_label, _DEFAULT_COLOR)
            if dst not in added_nodes:
                net.add_node(dst, label=f"[{dst_label}]\n{dst_name}",
                             color=color, title=f"{dst_label}: {dst_name}",
                             size=18, shape="dot")
                added_nodes.add(dst)
            src = row.get("src", decision_id)
            net.add_edge(src, dst, label=row.get("rel_type", ""), width=2)

        if len(added_nodes) <= 1:
            st.info("No connected nodes found for this decision.")
            return

        _render_net(net, height=height)

    except Exception as exc:
        st.error(f"Graph render error: {exc}")


def render_branch_comparison_graph(
    graph,
    actual_decision_id: str,
    branch_id: str,
    height: str = "600px",
) -> None:
    """Render a comparison graph showing actual vs. hypothetical branch nodes.

    Actual decision nodes use solid, brighter styling; hypothetical nodes
    use a distinct color with dashed border simulation (lighter opacity).

    Parameters
    ----------
    graph:
        Connected FalkorDB Graph object.
    actual_decision_id:
        ``id`` of the actual Decision.
    branch_id:
        ``id`` of the ScenarioBranch to compare against.
    height:
        CSS height string (default ``"600px"``).
    """
    try:
        net = _get_network(height=height)
    except ImportError as exc:
        st.warning(f"Graph visualization unavailable: {exc}")
        return

    try:
        added_nodes: set[str] = set()

        # --- Actual decision subtree ---
        actual_cypher = (
            "MATCH (d:Decision {id: $id})-[r:AFFECTS|SUPPORTED_BY]->(n) "
            "RETURN d.id AS src, n.id AS dst, "
            "COALESCE(n.title, n.name, n.id) AS dst_name, "
            "labels(n)[0] AS dst_label, type(r) AS rel_type, "
            "d.title AS src_name"
        )
        actual_rows = _result_to_list(graph.query(actual_cypher, {"id": actual_decision_id}))

        dec_row_cypher = (
            "MATCH (d:Decision {id: $id}) RETURN d.title AS title"
        )
        dec_title_rows = _result_to_list(graph.query(dec_row_cypher, {"id": actual_decision_id}))
        dec_title = (dec_title_rows[0].get("title") or actual_decision_id) if dec_title_rows else actual_decision_id

        if actual_decision_id not in added_nodes:
            net.add_node(actual_decision_id,
                         label=f"[Decision]\n{dec_title[:25]}",
                         color=NODE_COLORS["Decision"],
                         title=f"ACTUAL: {dec_title}",
                         size=28, shape="star", borderWidth=3)
            added_nodes.add(actual_decision_id)

        for row in actual_rows:
            dst = row.get("dst")
            if not dst:
                continue
            dst_label = row.get("dst_label", "Node")
            dst_name = (row.get("dst_name") or dst)[:25]
            color = NODE_COLORS.get(dst_label, _DEFAULT_COLOR)
            if dst not in added_nodes:
                net.add_node(dst, label=f"[{dst_label}]\n{dst_name}",
                             color=color, title=f"ACTUAL {dst_label}: {dst_name}",
                             size=18, shape="dot")
                added_nodes.add(dst)
            net.add_edge(actual_decision_id, dst,
                         label=row.get("rel_type", ""), color="#4A90D9", width=2)

        # --- Branch / hypothetical subtree ---
        branch_cypher = (
            "MATCH (b:ScenarioBranch {id: $bid})-[:CHANGES]->(h:Decision) "
            "OPTIONAL MATCH (h)-[r:AFFECTS]->(n) "
            "RETURN b.id AS branch_id, b.name AS branch_name, "
            "h.id AS hyp_id, h.title AS hyp_title, "
            "n.id AS dst, COALESCE(n.title, n.name, n.id) AS dst_name, "
            "labels(n)[0] AS dst_label, type(r) AS rel_type"
        )
        branch_rows = _result_to_list(graph.query(branch_cypher, {"bid": branch_id}))

        branch_name_cypher = (
            "MATCH (b:ScenarioBranch {id: $bid}) RETURN b.name AS name"
        )
        bn_rows = _result_to_list(graph.query(branch_name_cypher, {"bid": branch_id}))
        branch_name = (bn_rows[0].get("name") or branch_id) if bn_rows else branch_id

        if branch_id not in added_nodes:
            net.add_node(branch_id,
                         label=f"[Branch]\n{branch_name[:25]}",
                         color=NODE_COLORS["ScenarioBranch"],
                         title=f"HYPOTHETICAL BRANCH: {branch_name}",
                         size=24, shape="diamond", borderWidth=3)
            added_nodes.add(branch_id)

        for row in branch_rows:
            hyp_id = row.get("hyp_id")
            if hyp_id and hyp_id not in added_nodes:
                hyp_title = (row.get("hyp_title") or hyp_id)[:25]
                net.add_node(hyp_id,
                             label=f"[HYP]\n{hyp_title}",
                             color="#C0392B",
                             title=f"HYPOTHETICAL Decision: {hyp_title}",
                             size=18, shape="dot", opacity=0.85)
                added_nodes.add(hyp_id)
                net.add_edge(branch_id, hyp_id, label="CHANGES",
                             color="#E74C3C", width=2, dashes=True)

            dst = row.get("dst")
            if dst and hyp_id:
                dst_label = row.get("dst_label", "Node")
                dst_name = (row.get("dst_name") or dst)[:25]
                color = NODE_COLORS.get(dst_label, _DEFAULT_COLOR)
                if dst not in added_nodes:
                    net.add_node(dst, label=f"[{dst_label}]\n{dst_name}",
                                 color=color,
                                 title=f"HYP {dst_label}: {dst_name}",
                                 size=15, shape="dot", opacity=0.75)
                    added_nodes.add(dst)
                net.add_edge(hyp_id, dst, label=row.get("rel_type", ""),
                             color="#E74C3C", width=1, dashes=True)

        # Link actual → branch via HAS_BRANCH
        net.add_edge(actual_decision_id, branch_id,
                     label="HAS_BRANCH", color="#F39C12", width=2)

        if len(added_nodes) <= 2:
            st.info("No comparison graph data available.")
            return

        _render_net(net, height=height)

    except Exception as exc:
        st.error(f"Branch comparison graph render error: {exc}")


def render_full_knowledge_graph(graph, height: str = "700px") -> None:
    """Render all Decision, Person, Project, and ScenarioBranch nodes.

    Limits to 50 nodes to avoid browser performance issues.  Displays a
    note if the graph was truncated.

    Parameters
    ----------
    graph:
        Connected FalkorDB Graph object.
    height:
        CSS height string (default ``"700px"``).
    """
    try:
        net = _get_network(height=height)
    except ImportError as exc:
        st.warning(f"Graph visualization unavailable: {exc}")
        return

    try:
        # Fetch nodes
        node_cypher = (
            "MATCH (n) "
            "WHERE labels(n)[0] IN ['Decision', 'Person', 'Project', 'ScenarioBranch'] "
            "RETURN n.id AS id, labels(n)[0] AS label, "
            "COALESCE(n.title, n.name, n.id) AS display_name "
            "LIMIT 50"
        )
        node_rows = _result_to_list(graph.query(node_cypher))

        if not node_rows:
            st.info("No graph data available.")
            return

        added_nodes: set[str] = set()
        for row in node_rows:
            nid = row.get("id")
            if not nid:
                continue
            label = row.get("label", "Node")
            name = (row.get("display_name") or nid)[:30]
            color = NODE_COLORS.get(label, _DEFAULT_COLOR)
            net.add_node(nid, label=f"[{label}]\n{name}",
                         color=color, title=f"{label}: {name}",
                         size=20, shape="dot")
            added_nodes.add(nid)

        # Fetch edges among those nodes
        edge_cypher = (
            "MATCH (a)-[r]->(b) "
            "WHERE a.id IN $ids AND b.id IN $ids "
            "RETURN a.id AS src, b.id AS dst, type(r) AS rel_type "
            "LIMIT 200"
        )
        ids_list = list(added_nodes)
        edge_rows = _result_to_list(graph.query(edge_cypher, {"ids": ids_list}))

        for row in edge_rows:
            src = row.get("src")
            dst = row.get("dst")
            if src and dst and src in added_nodes and dst in added_nodes:
                net.add_edge(src, dst, label=row.get("rel_type", ""), width=1)

        # Truncation note
        count_cypher = (
            "MATCH (n) "
            "WHERE labels(n)[0] IN ['Decision', 'Person', 'Project', 'ScenarioBranch'] "
            "RETURN count(n) AS total"
        )
        count_rows = _result_to_list(graph.query(count_cypher))
        total = count_rows[0].get("total", 0) if count_rows else 0
        if total > 50:
            st.caption(
                f"ℹ️ Graph truncated to 50 of {total} nodes for performance."
            )

        _render_net(net, height=height)

    except Exception as exc:
        st.error(f"Knowledge graph render error: {exc}")
