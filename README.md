# EchoForge - Counterfactual Decision Lab

A tool that lets teams replay past decisions under different assumptions and see what might have happened. Built with FalkorDB, Streamlit, and Python.

---

## What it does

Most teams make a decision, move on, and never look back. EchoForge is built for the times you want to ask: "what if we had decided differently?"

You give it a real decision, change one assumption, and it runs AI agents through your company knowledge graph to generate predictions, critique them, and compare them against what actually happened. Everything is stored in FalkorDB so the agents remember past runs and build on them over time.

The demo uses a fictional company called NovaTech Systems, but the tool is built for real decision data.

---

## Tech stack

- FalkorDB (graph database, Redis-compatible)
- Python 3.10+
- Streamlit (web interface)
- OpenAI GPT-4o-mini (optional, has deterministic fallback)
- PyVis (interactive graph rendering)
- LangChain
- Docker + Docker Compose

---

## Graph data model

### Node types

| Node | What it represents |
|------|-------------------|
| Decision | A real or hypothetical decision |
| Person | Someone who made or was affected by a decision |
| Project | A project impacted by decisions |
| Evidence | A document or data point that supported a decision |
| ScenarioBranch | A what-if branch diverging from a real decision |
| Prediction | An AI-generated prediction about a branch outcome |
| Outcome | The recorded real-world result |
| AgentRun | A log of one AI agent execution |

### Relationship types

| Relationship | Connects |
|-------------|----------|
| AFFECTS | Decision to Project or Person |
| SUPPORTED_BY | Decision or Project to Evidence |
| HAS_BRANCH | Decision to ScenarioBranch |
| CHANGES | ScenarioBranch to hypothetical Decision |
| GENERATED | ScenarioBranch to Prediction |
| EVALUATED_AGAINST | Prediction to Outcome |
| MADE_BY | Decision to Person |
| INVOLVES | Decision to Person |
| SPAWNED_FROM | Prediction to ScenarioBranch |
| RAN_FOR | AgentRun to ScenarioBranch |

---

## Cypher queries the project depends on

### Multi-hop impact traversal

```cypher
MATCH path = (d:Decision {id: $id})-[:AFFECTS*1..5]->(affected)
RETURN affected.id AS id,
       labels(affected)[0] AS label,
       affected.name AS name,
       length(path) AS depth,
       [n IN nodes(path) | n.id] AS path_ids
ORDER BY depth ASC
```

### Evidence chain for a decision

```cypher
MATCH (d:Decision {id: $id})-[:SUPPORTED_BY]->(e:Evidence)
RETURN e.id AS id, e.content AS content, e.source AS source,
       e.created_at AS created_at, 'direct' AS via
UNION
MATCH (d:Decision {id: $id})-[:AFFECTS]->(p:Project)-[:SUPPORTED_BY]->(e:Evidence)
RETURN e.id AS id, e.content AS content, e.source AS source,
       e.created_at AS created_at, 'via_project' AS via
```

### Agent memory retrieval

```cypher
MATCH (a:AgentRun {agent_type: $agent_type})
RETURN a.id AS id, a.agent_type AS agent_type,
       a.started_at AS started_at, a.status AS status, a.summary AS summary
ORDER BY a.started_at DESC
LIMIT 10
```

### Shortest path between nodes

```cypher
MATCH (a {id: $from_id}), (b {id: $to_id})
MATCH path = shortestPath((a)-[*1..10]->(b))
RETURN [n IN nodes(path) | n.id] AS node_ids,
       [n IN nodes(path) | labels(n)[0]] AS node_labels,
       [r IN relationships(path) | type(r)] AS rel_types
```

### Actual vs hypothetical impact comparison

```cypher
MATCH path = (d:Decision {id: $actual_id})-[:AFFECTS*1..5]->(n)
RETURN n.id AS id, labels(n)[0] AS label, n.name AS name, 'actual' AS side
UNION ALL
MATCH (b:ScenarioBranch {id: $branch_id})-[:CHANGES]->(h:Decision)
MATCH path = (h)-[:AFFECTS*1..5]->(n)
RETURN n.id AS id, labels(n)[0] AS label, n.name AS name, 'hypothetical' AS side
```

---

## Setup

### Requirements

- Python 3.10 or higher
- Docker (for FalkorDB)
- An OpenAI API key (optional - the app works without one using deterministic fallbacks)

### Quick start

```bash
# 1. Clone the repo
git clone https://github.com/Dreamcatcher23/EchoForge.git
cd EchoForge

# 2. Start FalkorDB
docker-compose up -d falkordb

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables
cp .env.example .env
# Edit .env and add your OpenAI key if you have one

# 5. Initialize the database
python scripts/init_db.py

# 6. Run the app
streamlit run app/main.py
```

Open http://localhost:8501 in your browser.

### Run everything with Docker Compose

```bash
docker-compose up -d
# Then seed the database on first run:
docker-compose exec echoforge python scripts/init_db.py
```

### Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| FALKORDB_HOST | No | localhost | FalkorDB host |
| FALKORDB_PORT | No | 6379 | FalkorDB port |
| FALKORDB_GRAPH_NAME | No | echoforge | Graph name |
| OPENAI_API_KEY | No | - | OpenAI key for AI agents |
| OPENAI_MODEL | No | gpt-4o-mini | Model to use |

---

## Running tests

```bash
# All tests
pytest tests/ -v

# Unit tests only (no database needed)
pytest tests/ -v -k "not TestBranchIsolation and not TestOutcomeEvaluation and not TestEndToEndSmoke"

# Integration tests (requires FalkorDB running)
pytest tests/test_integration.py -v
```

---

## How the agents work

**ScenarioAgent** runs first. It reads the source decision from the graph, does a multi-hop traversal to find all affected entities and evidence, then generates a set of predictions about what would happen under the new assumptions. It stores each prediction as a node in FalkorDB.

**CriticAgent** runs second. It loads the predictions from FalkorDB, checks them against the evidence chain, and flags any that lack support or make claims beyond what the evidence shows.

**OutcomeEvaluator** runs when you have a real outcome to compare against. It loads all predictions for a branch and evaluates each one as supported, contradicted, or inconclusive based on what actually happened.

**Coordinator** manages both pipelines. It also queries its own prior runs from FalkorDB before starting, so it has context about what simulations have already been run.

---

## Project structure

```
EchoForge/
├── app/
│   ├── main.py                  # 7-page Streamlit app
│   └── components/
│       ├── graph_viz.py         # PyVis graph rendering
│       └── ui_helpers.py        # Shared UI components
├── agents/
│   ├── base_agent.py            # Base class with FalkorDB memory
│   ├── coordinator.py           # Pipeline orchestrator
│   ├── scenario_agent.py        # Generates predictions
│   ├── critic_agent.py          # Reviews predictions
│   └── outcome_evaluator.py     # Evaluates predictions vs reality
├── core/
│   └── comparison.py            # Actual vs hypothetical diff
├── db/
│   ├── connection.py            # FalkorDB connection
│   ├── history.py               # Immutability layer
│   ├── branch_service.py        # Branch management
│   ├── traversal.py             # Multi-hop traversal engine
│   ├── queries.py               # All Cypher queries
│   ├── schema.py                # Index creation
│   └── seed.py                  # Demo data
├── docs/
│   ├── schema.md                # Full schema reference
│   ├── submission.md            # Hackathon submission notes
│   └── demo_script.md           # Demo walkthrough
├── scripts/
│   ├── init_db.py               # Database setup script
│   ├── audit_immutability.py    # Checks immutability guards
│   └── verify_deliverables.py   # Checks all files are present
├── tests/
│   ├── test_connection.py
│   ├── test_history.py
│   ├── test_traversal.py
│   ├── test_agents.py
│   └── test_integration.py
├── .env.example
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

---

## Demo walkthrough
https://www.youtube.com/watch?v=QUNKiMk4Z6E

The seed data uses a fictional company called NovaTech Systems. The core decision is DEC-001: migrating their production database from PostgreSQL 12 to PostgreSQL 15 on March 15, 2024. It finished with a 3-day delay.

The what-if scenario is: what if they had done the migration two weeks earlier, on March 1? Would the delay have been avoided?

1. Open the Dashboard and confirm FalkorDB is connected
2. Go to Decision Inspector, select DEC-001, and look at the evidence and affected projects
3. Go to Scenario Creator, set the source to DEC-001, name the branch "Two Weeks Earlier", change migration_date from 2024-03-15 to 2024-03-01, create the branch, and run the scenario analysis
4. Go to Comparison View to see the actual vs hypothetical side by side
5. Go to Agent History to see the AgentRun nodes stored in FalkorDB
6. Go to Outcome Evaluation, enter what actually happened, and see which predictions were right

---

## License

MIT
