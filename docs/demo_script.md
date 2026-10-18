# EchoForge Demo Script

> ⚠️ All data shown (NovaTech Systems, people, projects, decisions) is entirely fictional.

Total duration: ~5 minutes 15 seconds

---

## Setup (before recording)

Run these commands in your terminal before starting the screen recording:

```bash
# Terminal 1 — start FalkorDB
docker-compose up -d falkordb

# Wait ~5 seconds for FalkorDB to be ready, then:

# Terminal 2 — install deps and initialize
pip install -r requirements.txt
python scripts/init_db.py

# Launch the app
streamlit run app/main.py
```

Open **http://localhost:8501** in your browser. Verify the green "✅ Connected to FalkorDB" banner appears on the Dashboard. You are ready to record.

---

## Scene 1: Dashboard Overview (0:00 – 0:45)

**What to show:**

1. Open the app at `http://localhost:8501`. The **🏠 Dashboard** page is already selected.
2. Point to the green banner: *"Connected to FalkorDB — this is a real graph database, not mock data."*
3. Hover over the four metric tiles:
   - **Actual Decisions: 1** — `DEC-001`, the real historical decision
   - **Projects Affected: 3** — Phoenix API, Atlas Analytics, Mercury DevTools
   - **Scenario Branches: 1** — `BRANCH-001`, the pre-seeded hypothetical
   - **Agent Runs: 0** — no agents have run yet (will grow during the demo)
4. Scroll down to the **📋 Decision History** table — show `DEC-001` with its title and date.
5. Scroll further to the **🌐 Knowledge Graph Overview** — an interactive PyVis graph showing Decision, Project, Person, and ScenarioBranch nodes. Hover over `DEC-001` to show the tooltip.

**Narrate:** *"EchoForge stores the NovaTech Systems decision graph in FalkorDB. Every node and relationship you see was loaded by parameterized Cypher queries — no in-memory mock data."*

---

## Scene 2: Decision Inspector (0:45 – 1:30)

**What to show:**

1. Click **🔍 Decision Inspector** in the sidebar navigation.
2. The selectbox shows `DEC-001 — Migrate production database from PostgreSQL 12 to PostgreSQL 15`. Select it.
3. The info panel shows the decision description, made-at date (2024-03-15), and `is_actual: True`.
4. Expand the **🔎 Evidence (3 items)** expander:
   - `EV-001` — PostgreSQL 12 EOL announcement (source: PostgreSQL.org)
   - `EV-002` — 23% query improvement benchmark (source: Internal benchmark report)
   - `EV-003` — Atlas Analytics 2-week integration estimate
5. Scroll to **🎯 Affected Entities (2)**:
   - `PROJ-001` Phoenix API (depth 1)
   - `PROJ-002` Atlas Analytics (depth 1)
6. Show the **Impact Summary** metrics row.
7. Scroll to the **🌐 Decision Graph** — a focused graph showing `DEC-001` connected to its projects and evidence nodes via labeled edges (`AFFECTS`, `SUPPORTED_BY`).

**Narrate:** *"The graph traversal engine follows `AFFECTS*1..5` relationships in Cypher to discover all downstream entities at each depth level."*

---

## Scene 3: Scenario Creator (1:30 – 2:30)

**What to show:**

1. Click **🌿 Scenario Creator** in the sidebar.
2. Under **Source Decision**, `DEC-001` is pre-selected (or select it manually).
3. Fill in:
   - **Branch Name:** `Two Weeks Earlier`
   - **Description:** `What if the migration had been executed on 2024-03-01 instead of 2024-03-15, giving the Atlas Analytics team two additional weeks of runway?`
4. Under **🔄 Changed Assumptions**, fill in Assumption 1:
   - **Field / Parameter:** `migration_date`
   - **Original Value:** `2024-03-15`
   - **New Value:** `2024-03-01`
5. Click **🌿 Create Branch** (primary button). Watch the spinner.
6. When the green success banner appears with a branch ID (e.g., `BRANCH-XXXXXXXX`), point to it: *"A new ScenarioBranch node was just created in FalkorDB via a MERGE Cypher query."*
7. The Branch ID auto-populates in the **🤖 Run Scenario Analysis** text field.
8. Click **▶️ Run Scenario Analysis**. Watch the spinner: *"Running ScenarioAgent → CriticAgent…"*
9. When complete, show the coordinator run ID in the success banner.
10. Expand **🔮 ScenarioAgent Results** — show the `predictions` array with 3 items, each having `content`, `confidence`, and `branch_id`.
11. Expand **🧐 CriticAgent Results** — show `critique_findings`, `unsupported_claims`, `missing_evidence`.

**Narrate:** *"ScenarioAgent traversed the graph for context, generated 3 predictions, and persisted each as a Prediction node. CriticAgent then reviewed them against the evidence chain — both runs are now saved as AgentRun nodes in FalkorDB."*

---

## Scene 4: Comparison View (2:30 – 3:15)

**What to show:**

1. Click **⚖️ Comparison View** in the sidebar.
2. Select:
   - **Actual Decision:** `DEC-001 — Migrate production database…`
   - **Hypothetical Branch:** the newly created `Two Weeks Earlier` branch (or `BRANCH-001` if using seeded data)
3. The side-by-side layout appears. Point out the left column:
   - Title, description, `ACTUAL` badge, evidence count, affected count.
4. Point out the right column:
   - Branch name, description, `HYPOTHETICAL` badge, assumption count, prediction count.
5. Expand **🔄 Changed Assumptions** on the right — show `migration_date: 2024-03-15 → 2024-03-01`.
6. Expand **🔮 Predictions** on the right — show the 3 persisted predictions with confidence labels.
7. Scroll to the **🔍 Impact Diff** section — show the three columns: Added Impacts, Removed Impacts, Assumption Changes.
8. Scroll to the **🌐 Branch Comparison Graph** — a dual-sided PyVis graph with actual decision nodes in blue/star shape and hypothetical nodes in red/diamond shape, connected by `HAS_BRANCH` and `CHANGES` edges.

**Narrate:** *"The diff is computed by set-comparing the AFFECTS traversals from both the actual and hypothetical decision nodes using FalkorDB graph queries."*

---

## Scene 5: Agent History (3:15 – 3:45)

**What to show:**

1. Click **🤖 Agent History** in the sidebar.
2. The Agent Runs table now shows at least 3 rows: `scenario`, `critic`, `coordinator`.
3. Use the **Filter by Agent Type** selectbox to select `scenario` — see only the ScenarioAgent run.
4. Switch to `coordinator` — see the Coordinator run with `output_data` showing sub-run IDs.
5. Scroll to the individual run cards below the table — expand one to show the JSON output including `predictions` list or `critique_findings`.

**Narrate:** *"Every agent persists its complete run as an AgentRun node in FalkorDB. Before each new run, agents query their own prior runs — this is the persistent memory layer."*

---

## Scene 6: Outcome Evaluation (3:45 – 4:30)

**What to show:**

1. Click **✅ Outcome Evaluation** in the sidebar.
2. Select:
   - **Branch to Evaluate:** the `Two Weeks Earlier` branch (or `BRANCH-001`)
   - **Reference Decision:** `DEC-001`
3. In the **Observed Outcome Description** text area, type:
   ```
   The early migration completed successfully on 2024-03-05 with only a 1-day delay. 
   The Atlas Analytics team had sufficient time to complete their integration work 
   before the original deadline.
   ```
4. Leave **Observed Date** as today.
5. Click **📊 Evaluate Predictions** (primary button). Watch the spinner: *"Running OutcomeEvaluator…"*
6. When complete, show the evaluation results table with `prediction_id`, `status` (supported/contradicted/inconclusive), `rationale`, and `confidence`.
7. Scroll down to **📝 Record Actual Outcome** — show the form but do not submit (explain it would record `is_actual=True`).
8. Scroll to **📋 Existing Actual Outcomes** — show `OUT-001` from the seed data.

**Narrate:** *"OutcomeEvaluator created an Outcome node in FalkorDB and linked each Prediction to it via EVALUATED_AGAINST with a status property."*

---

## Scene 7: Knowledge Graph (4:30 – 5:00)

**What to show:**

1. Return to **🏠 Dashboard** in the sidebar.
2. Scroll to the **🌐 Knowledge Graph Overview** at the bottom of the page.
3. The graph now shows additional nodes: `ScenarioBranch`, `Prediction`, `AgentRun` nodes that didn't exist at the start of the demo.
4. Interact with the graph:
   - Drag a node to rearrange the layout.
   - Hover over the `BRANCH-001` node to show the tooltip.
   - Hover over a `Prediction` node.
5. Note the **Agent Runs metric** on the Dashboard has increased from 0 to 3+.

**Narrate:** *"Every action in EchoForge was backed by a real FalkorDB query. The knowledge graph has grown during this session — new branches, predictions, and agent runs are now persistent nodes and relationships."*

---

## Closing (5:00 – 5:15)

**What to show:**

1. Open a new terminal window and run:
   ```bash
   python -c "from db.connection import test_connection; print('Connected:', test_connection())"
   ```
   Show `Connected: True`.
2. Optionally run:
   ```bash
   python scripts/verify_deliverables.py
   ```
   Show all `✅ PASS` lines.
3. Return to the browser and pause on the Dashboard.

**Narrate:** *"EchoForge is a complete Counterfactual Decision Lab — graph-native storage in FalkorDB, multi-agent coordination with persistent memory, and a 7-page Streamlit interface for exploring the full decision intelligence of an organization."*

---

## Appendix: Key Commands Reference

```bash
# Start FalkorDB
docker-compose up -d falkordb

# Initialize DB (schema + seed)
python scripts/init_db.py

# Run the app
streamlit run app/main.py

# Run full test suite
pytest tests/ -v --tb=short

# Verify all deliverables
python scripts/verify_deliverables.py

# Audit immutability
python scripts/audit_immutability.py
```
