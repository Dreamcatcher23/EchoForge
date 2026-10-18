# EchoForge — Hackathon Submission

> ⚠️ All organizational data (NovaTech Systems, Alice Chen, Bob Ramirez, etc.) is entirely fictional and created solely for demonstration purposes.

---

## What is EchoForge?

EchoForge is a **Counterfactual Decision Lab** — a system that enables teams to replay past decisions under altered assumptions and rigorously evaluate what *might* have happened. It stores an immutable graph of real decisions, evidence, people, projects, and outcomes in **FalkorDB**, then creates isolated hypothetical "branches" where autonomous AI agents generate predictions, critique reasoning chains, and evaluate results against observed reality.

At its core, EchoForge answers a critical business question: *"If we had decided differently, what would the downstream consequences have been?"* By combining graph-native knowledge representation with coordinated multi-agent AI pipelines, EchoForge transforms historical decision data into an interactive reasoning engine.

The application presents a 7-page Streamlit interface covering the full counterfactual analysis lifecycle: from inspecting individual decisions and their evidence chains, to creating hypothetical branches, running agent-driven scenario analysis, comparing actual vs. hypothetical impact, and evaluating agent predictions against real outcomes. Every agent action is persisted as an `AgentRun` node in FalkorDB, creating a durable shared memory that accumulates knowledge across sessions. The result is a living "Company Brain" — a queryable, visual record of what was decided, why, what happened, and what would have happened differently.

---

## Contribution to Hackathon Tracks

### Track 1: Agents That Act on Connected Data

EchoForge agents do not operate on isolated data records — they reason over the **connected graph topology** of an organization's decision history.

When `ScenarioAgent` runs for a branch, it first executes [`traversal.get_affected_entities(graph, decision_id)`](../db/traversal.py) — a multi-hop Cypher query that follows `AFFECTS*1..5` relationships outward from the source decision, discovering all downstream projects, people, and other entities at each depth level:

```cypher
MATCH path = (d:Decision {id: $id})-[:AFFECTS*1..5]->(affected)
RETURN affected.id AS id, labels(affected)[0] AS label,
       affected.name AS name, length(path) AS depth,
       [n IN nodes(path) | n.id] AS path_ids
ORDER BY depth ASC
```

It also calls [`traversal.get_evidence_chain(graph, decision_id)`](../db/traversal.py), which traverses two paths simultaneously — `(Decision)-[:SUPPORTED_BY]->(Evidence)` and `(Decision)-[:AFFECTS]->(Project)-[:SUPPORTED_BY]->(Evidence)` — to assemble the complete evidential context grounding the agent's predictions.

`CriticAgent` calls [`queries.get_predictions_for_branch(graph, branch_id)`](../db/queries.py) to retrieve already-persisted predictions, then applies them against the evidence chain to identify unsupported claims and missing evidence. The `OutcomeEvaluator` uses the same graph-traversal infrastructure to load predictions before comparing them to the observed outcome string.

All agent reasoning is therefore **structurally grounded in the graph topology** — the shape and depth of connected entities directly controls what predictions are made and how they are critiqued.

---

### Track 2: Agent Memory and Coordination

EchoForge implements **persistent shared agent memory via FalkorDB `AgentRun` nodes**.

Every agent (ScenarioAgent, CriticAgent, OutcomeEvaluator, and the Coordinator itself) inherits from [`BaseAgent`](../agents/base_agent.py), which calls [`queries.save_agent_run(graph, run_data)`](../db/queries.py) at the end of every execution. This persists the run as an `AgentRun` node with properties: `id`, `agent_type`, `started_at`, `completed_at`, `status`, `summary`, `input_data` (JSON), and `output_data` (JSON).

Before each new run, [`BaseAgent.get_prior_runs(limit=5)`](../agents/base_agent.py) calls [`queries.get_agent_runs_by_type(graph, agent_type, limit=limit)`](../db/queries.py) to retrieve the most recent prior runs of the same agent type:

```cypher
MATCH (a:AgentRun {agent_type: $agent_type})
RETURN a.id, a.agent_type, a.started_at, a.completed_at,
       a.status, a.summary, a.input_data, a.output_data
ORDER BY a.started_at DESC
LIMIT 5
```

This gives every agent **awareness of its own history** without any in-process shared state — coordination happens purely through the graph.

The [`Coordinator`](../agents/coordinator.py) orchestrates the two-stage scenario pipeline:

1. **`run_scenario_pipeline(graph, branch_id, decision_id)`** → instantiates `ScenarioAgent`, calls `.run(branch_id, decision_id)`, then instantiates `CriticAgent` and calls `.run(branch_id, decision_id, scenario_run_id=...)`, passing the scenario run ID as context.
2. **`run_evaluation_pipeline(graph, branch_id, decision_id, observed_outcome)`** → instantiates `OutcomeEvaluator` and calls `.run(...)`.

After each pipeline, the Coordinator itself calls [`queries.save_agent_run`](../db/queries.py) with `agent_type="coordinator"`, storing the sub-run IDs in `output_data`. It also pre-loads prior coordinator runs via `queries.get_agent_runs_by_type(graph, "coordinator", limit=10)` before every new pipeline — giving it memory of all previous simulation sessions. The Dashboard page in [`app/main.py`](../app/main.py) calls [`queries.get_agent_runs(graph)`](../db/queries.py) to display all accumulated agent run history.

---

### Track 3: Company Brain

EchoForge's graph schema encodes the **full decision intelligence of an organization** across 8 node types and 10 relationship types.

**Node types:**

| Label | Role in the Knowledge Graph |
|-------|----------------------------|
| `Decision` | A real (`is_actual=True`) or hypothetical (`is_actual=False`) decision |
| `Person` | An individual who made or was affected by a decision |
| `Project` | An organizational project impacted by decisions |
| `Evidence` | Supporting data or documentation for a decision |
| `ScenarioBranch` | A "what-if" branch diverging from an actual decision |
| `Prediction` | An agent-generated prediction about a branch outcome |
| `Outcome` | A recorded result — actual or hypothetical |
| `AgentRun` | A persistent record of one agent execution |

The fictional **NovaTech Systems** organization is represented with 4 people (Alice Chen — CTO, Bob Ramirez — Engineering Lead, Carol Singh — Database Architect, David Park — Project Manager), 3 projects (Phoenix API, Atlas Analytics, Mercury DevTools), and the key decision `DEC-001` — migrating production database from PostgreSQL 12 to PostgreSQL 15 on 2024-03-15.

The graph enables **counterfactual reasoning** because `DEC-001` (`is_actual=True`) is linked via `HAS_BRANCH → BRANCH-001 → CHANGES → DEC-002` (`is_actual=False`). The hypothetical branch `DEC-002` poses: "What if the migration had been executed two weeks earlier, on 2024-03-01?" Agents traverse from `DEC-002` exactly as they would from `DEC-001`, generating parallel impact chains that can be directly compared. The immutability layer in [`db/history.py`](../db/history.py) ensures `DEC-001` and `OUT-001` can never be mutated — preserving the integrity of the historical record while enabling unrestricted hypothetical reasoning.

---

## Technical Architecture

```
┌────────────────────────────────────────────────────┐
│               Streamlit UI (app/main.py)            │
│  Dashboard · Inspector · Scenario · Comparison      │
│  Predictions · Agent History · Outcome Evaluation   │
│  PyVis graph visualisations (app/components/)       │
└──────────────┬───────────────────────────┬──────────┘
               │                           │
     DB queries│                   Agent pipeline
               ▼                           ▼
┌──────────────────────┐    ┌──────────────────────────┐
│  Python service layer │    │  Multi-agent coordinator  │
│  db/connection.py     │    │  agents/coordinator.py    │
│  db/history.py        │    │  agents/scenario_agent.py │
│  db/branch_service.py │    │  agents/critic_agent.py   │
│  db/traversal.py      │    │  agents/outcome_evaluator │
│  db/queries.py        │    │  (OpenAI optional)        │
│  core/comparison.py   │    └──────────────────────────┘
└──────────────┬────────┘
               │  Parameterized Cypher queries
               ▼
┌──────────────────────────────────┐
│           FalkorDB               │
│   (Redis-compatible graph DB)    │
│   port 6379 / graph: echoforge   │
└──────────────────────────────────┘
```

---

## FalkorDB Integration

EchoForge uses the following FalkorDB-specific features:

- **Parameterized Cypher queries** — all 30+ query functions in [`db/queries.py`](../db/queries.py), [`db/history.py`](../db/history.py), [`db/traversal.py`](../db/traversal.py), and [`db/branch_service.py`](../db/branch_service.py) pass all variable data via `graph.query(cypher, params)` — no f-string injection of user data.
- **Multi-hop graph traversal** — `AFFECTS*1..5` variable-depth traversal in [`traversal.get_affected_entities`](../db/traversal.py) and `shortestPath((a)-[*1..10]->(b))` in [`traversal.get_dependency_path`](../db/traversal.py).
- **MERGE for idempotent writes** — all node and relationship creation uses `MERGE` with `ON CREATE SET` guards, making `seed_database()` and `create_branch()` fully re-runnable.
- **Graph-backed agent memory** — `AgentRun` nodes stored and queried with `ORDER BY started_at DESC LIMIT N` provide persistent cross-session memory.
- **Immutability via graph properties** — `is_actual=True` flags on `Decision` and `Outcome` nodes are enforced at the application layer by [`db/history.py`](../db/history.py)'s `assert_not_actual()` guard.
- **FalkorDB Python client** — `falkordb.FalkorDB(host, port)` + `client.select_graph(name)` from the `falkordb` package.

---

## Demo Scenario: NovaTech Systems Database Migration

The seeded demo represents NovaTech Systems' decision to migrate their production database from PostgreSQL 12 to PostgreSQL 15 in Q1 2024.

1. **Alice Chen (CTO)** made `DEC-001` on 2024-03-15: *"Migrate production database from PostgreSQL 12 to PostgreSQL 15"*.
2. The decision was **supported by** two evidence nodes: an EOL announcement (`EV-001`) and an internal benchmark showing 23% query improvement (`EV-002`).
3. The decision **affected** `PROJ-001` (Phoenix API) and `PROJ-002` (Atlas Analytics).
4. The actual outcome `OUT-001` shows the migration completed on 2024-04-20 with a **3-day delay** caused by Atlas Analytics integration issues.
5. `BRANCH-001` ("Early Migration Scenario") asks: *"What if we had migrated two weeks earlier, on 2024-03-01?"* — represented as `DEC-002` (`is_actual=False`) linked via `BRANCH-001 -[:CHANGES]-> DEC-002`.
6. Running `ScenarioAgent` on `BRANCH-001` traverses from `DEC-002`, discovers the same downstream entities, and generates 3 predictions about the counterfactual outcome.
7. `CriticAgent` reviews those predictions against the evidence chain, identifying whether each is well-supported.

---

## Setup Instructions

```bash
# 1. Clone the repository and enter the directory
cd EchoForge

# 2. Start FalkorDB
docker-compose up -d falkordb

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env   # edit .env if needed

# 5. Initialize and seed the database, then run the app
python scripts/init_db.py
streamlit run app/main.py
```

---

## Repository Structure

```
EchoForge/
├── app/
│   ├── main.py                  # 7-page Streamlit application
│   └── components/
│       ├── graph_viz.py         # PyVis interactive graph panels
│       └── ui_helpers.py        # Reusable Streamlit widgets
├── agents/
│   ├── base_agent.py            # Abstract agent base with FalkorDB memory
│   ├── coordinator.py           # Multi-agent pipeline orchestrator
│   ├── scenario_agent.py        # Prediction generator
│   ├── critic_agent.py          # Prediction critic
│   └── outcome_evaluator.py     # Prediction evaluator
├── core/
│   └── comparison.py            # Actual vs. hypothetical diff engine
├── db/
│   ├── connection.py            # FalkorDB connection factory
│   ├── history.py               # Immutability guard + actual-history reads
│   ├── branch_service.py        # Branch lifecycle (create/list/inspect)
│   ├── traversal.py             # Multi-hop Cypher traversal engine
│   ├── queries.py               # All parameterized Cypher query functions
│   ├── schema.py                # Index and constraint creation
│   └── seed.py                  # Fictional NovaTech Systems demo data
├── docs/
│   ├── schema.md                # Full schema reference + Cypher examples
│   ├── submission.md            # This file
│   └── demo_script.md           # Screen-recording walkthrough
├── scripts/
│   ├── init_db.py               # One-shot DB initializer
│   ├── audit_immutability.py    # Immutability audit script
│   ├── verify_deliverables.py   # Deliverable presence checker
│   ├── run_tests.sh             # Test runner (Linux/macOS)
│   └── run_tests.bat            # Test runner (Windows)
├── tests/
│   ├── test_connection.py       # FalkorDB connection tests
│   ├── test_history.py          # Immutability guard tests
│   ├── test_traversal.py        # Traversal engine tests
│   ├── test_agents.py           # Agent base class + coordinator tests
│   └── test_integration.py      # End-to-end integration tests
├── .env.example                 # Environment variable template
├── .gitignore
├── docker-compose.yml           # FalkorDB + EchoForge app services
├── Dockerfile
├── pyproject.toml
└── requirements.txt
```
