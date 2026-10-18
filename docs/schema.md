# EchoForge — Graph Schema Reference

> ⚠️ All node data shown in examples (NovaTech Systems, DEC-001, PER-001, etc.) is fictional and used for demonstration purposes only.

---

## Node Types

### 1. `Decision`

Represents a real or hypothetical decision.  Real decisions have `is_actual=True` and are **immutable** — they can never be updated or deleted once written.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | String | ✅ | Unique identifier, e.g. `"DEC-001"` |
| `title` | String | ✅ | Short human-readable title |
| `description` | String | ✅ | Full description of the decision |
| `made_at` | String (ISO-8601) | ✅ | When the decision was made |
| `is_actual` | Boolean | ✅ | `true` = real historical record; `false` = hypothetical |
| `field` | String | No | (Hypothetical only) The assumption field that was changed |
| `original_value` | String | No | (Hypothetical only) Value before the change |
| `new_value` | String | No | (Hypothetical only) Value after the change |
| `source_decision_id` | String | No | (Hypothetical only) ID of the actual decision this diverges from |

**Immutability rule:** Any node with `is_actual=True` must never be mutated.  The `db.history.assert_not_actual()` guard enforces this at the service layer.

---

### 2. `Person`

An individual who made or was affected by a decision.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | String | ✅ | Unique identifier, e.g. `"PER-001"` |
| `name` | String | ✅ | Full name |
| `role` | String | No | Job title / role |
| `department` | String | No | Organisational department |
| `email` | String | No | Contact email |

---

### 3. `Project`

An organisational project affected by one or more decisions.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | String | ✅ | Unique identifier, e.g. `"PROJ-001"` |
| `name` | String | ✅ | Project name |
| `status` | String | No | `"active"`, `"completed"`, `"paused"`, `"cancelled"` |
| `budget` | String | No | Budget string (e.g. `"$500K"`) |
| `description` | String | No | Project description |
| `start_date` | String | No | ISO-8601 start date |
| `end_date` | String | No | ISO-8601 end date (if completed) |

---

### 4. `Evidence`

A document, data point, or artefact that supports a decision.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | String | ✅ | Unique identifier, e.g. `"EV-001"` |
| `content` | String | ✅ | Full text / summary of the evidence |
| `source` | String | ✅ | Origin of the evidence (e.g. `"Q4 budget report"`) |
| `created_at` | String (ISO-8601) | ✅ | When this evidence was recorded |
| `url` | String | No | Link to source document |

---

### 5. `ScenarioBranch`

A hypothetical "what-if" branch that diverges from an actual decision.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | String | ✅ | Unique identifier, e.g. `"BRANCH-AB12CD34"` |
| `name` | String | ✅ | Human-readable branch name |
| `description` | String | ✅ | What this branch is testing |
| `status` | String | ✅ | `"active"`, `"archived"`, `"draft"` |
| `created_at` | String (ISO-8601) | ✅ | When the branch was created |

---

### 6. `Prediction`

An agent-generated forecast about the outcome of a hypothetical branch.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | String | ✅ | Unique identifier, e.g. `"PRED-FF001122"` |
| `content` | String | ✅ | Full text of the prediction |
| `confidence` | Float (0–1) | ✅ | Agent's confidence score |
| `status` | String | ✅ | `"pending"`, `"supported"`, `"contradicted"`, `"inconclusive"` |
| `created_at` | String (ISO-8601) | ✅ | When the prediction was generated |
| `branch_id` | String | ✅ | ID of the source `ScenarioBranch` |

---

### 7. `Outcome`

A recorded result — either real (`is_actual=True`) or predicted (`is_actual=False`).

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | String | ✅ | Unique identifier, e.g. `"OUT-001"` |
| `description` | String | ✅ | Full description of the outcome |
| `observed_at` | String (ISO-8601) | ✅ | When the outcome was observed |
| `is_actual` | Boolean | ✅ | `true` = real-world observation; `false` = hypothetical |
| `branch_id` | String | No | (Hypothetical only) ID of the originating branch |

**Immutability rule:** Real outcomes (`is_actual=True`) use `ON CREATE SET` semantics — a second write with the same `id` is a no-op.

---

### 8. `AgentRun`

A persistent record of a single agent execution, written by each agent after it completes.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | String | ✅ | Unique identifier, e.g. `"COORD-AA11BB22"` |
| `agent_type` | String | ✅ | `"scenario"`, `"critic"`, `"evaluator"`, `"coordinator"` |
| `started_at` | String (ISO-8601) | ✅ | Pipeline start time |
| `completed_at` | String (ISO-8601) | ✅ | Pipeline completion time |
| `status` | String | ✅ | `"completed"` or `"failed"` |
| `summary` | String | ✅ | Single-line human-readable result |
| `input_data` | String (JSON) | No | Serialised input parameters |
| `output_data` | String (JSON) | No | Serialised output data |

---

## Relationship Types

| Type | From → To | Cardinality | Properties | Description |
|------|-----------|-------------|------------|-------------|
| `AFFECTS` | `Decision → Project\|Person` | Many-to-many | — | Decision directly impacts this entity |
| `SUPPORTED_BY` | `Decision\|Project → Evidence` | Many-to-many | — | Entity is supported by this evidence |
| `HAS_BRANCH` | `Decision → ScenarioBranch` | One-to-many | `created_at` | Actual decision has this hypothetical branch |
| `CHANGES` | `ScenarioBranch → Decision` | One-to-many | `field`, `created_at` | Branch introduces this hypothetical decision |
| `GENERATED` | `ScenarioBranch → Prediction` | One-to-many | `created_at` | Branch produced this prediction |
| `EVALUATED_AGAINST` | `Prediction → Outcome` \| `Outcome → Decision` | Many-to-one | `status`, `created_at` | Evaluation link with status |
| `MADE_BY` | `Decision → Person` | Many-to-one | — | Decision was made by this person |
| `INVOLVES` | `Decision → Person` | Many-to-many | `role` | Person was involved in or affected by the decision |
| `SPAWNED_FROM` | `Prediction → ScenarioBranch` | Many-to-one | — | Prediction originated in this branch |
| `RAN_FOR` | `AgentRun → ScenarioBranch` | Many-to-one | — | Agent run was executed for this branch |

---

## Key Cypher Query Examples

### 1. Fetch all actual decisions ordered by date

```cypher
-- Returns all real historical decisions, ordered chronologically.
MATCH (d:Decision {is_actual: true})
RETURN d.id AS id, d.title AS title, d.description AS description,
       d.made_at AS made_at, d.is_actual AS is_actual
ORDER BY d.made_at ASC
```

---

### 2. Multi-hop AFFECTS traversal (up to 3 hops)

```cypher
-- Find all entities reachable from DEC-001 via AFFECTS relationships,
-- up to 3 hops deep, ordered by traversal depth.
MATCH path = (d:Decision {id: $decision_id})-[:AFFECTS*1..3]->(affected)
RETURN affected.id AS id,
       labels(affected)[0] AS label,
       affected.name AS name,
       length(path) AS depth,
       [n IN nodes(path) | n.id] AS path_ids
ORDER BY depth ASC
```

*Parameters:* `decision_id = "DEC-001"`

---

### 3. Get evidence chain for a decision (direct + via projects)

```cypher
-- Direct evidence
MATCH (d:Decision {id: $id})-[:SUPPORTED_BY]->(e:Evidence)
RETURN e.id AS id, e.content AS content, e.source AS source,
       e.created_at AS created_at, 'direct' AS via

UNION

-- Evidence reachable via affected projects
MATCH (d:Decision {id: $id})-[:AFFECTS]->(p:Project)-[:SUPPORTED_BY]->(e:Evidence)
RETURN e.id AS id, e.content AS content, e.source AS source,
       e.created_at AS created_at, 'via_project' AS via
```

*Parameters:* `id = "DEC-001"`

---

### 4. Create a ScenarioBranch (idempotent MERGE)

```cypher
-- Creates a branch node using MERGE so the operation is safe to re-run.
-- ON CREATE SET ensures properties are only written on first creation.
MERGE (b:ScenarioBranch {id: $id})
ON CREATE SET
  b.name        = $name,
  b.description = $description,
  b.status      = 'active',
  b.created_at  = $created_at
RETURN b.id AS id, b.name AS name, b.description AS description,
       b.status AS status, b.created_at AS created_at
```

*Parameters:* `id`, `name`, `description`, `created_at`

---

### 5. Link a Decision to a Branch (HAS_BRANCH)

```cypher
-- Creates a HAS_BRANCH relationship without modifying the Decision node.
-- The Decision's properties are untouched — only a new relationship is added.
MATCH (d:Decision {id: $dec_id})
MATCH (b:ScenarioBranch {id: $branch_id})
MERGE (d)-[r:HAS_BRANCH]->(b)
ON CREATE SET r.created_at = $created_at
```

*Parameters:* `dec_id = "DEC-001"`, `branch_id = "BRANCH-AB12CD34"`, `created_at`

---

### 6. Record an actual outcome (immutable write)

```cypher
-- MERGE on id means re-running is safe.
-- ON CREATE SET ensures an existing outcome is NEVER overwritten.
MERGE (o:Outcome {id: $id})
ON CREATE SET
  o.description = $description,
  o.observed_at = $observed_at,
  o.is_actual   = true
RETURN o.id AS id, o.description AS description,
       o.observed_at AS observed_at, o.is_actual AS is_actual
```

*Parameters:* `id = "OUT-001"`, `description`, `observed_at`

---

### 7. Get all predictions for a branch (two relationship patterns)

```cypher
-- Covers predictions linked via SPAWNED_FROM or EVALUATED_AGAINST.
MATCH (p:Prediction)
WHERE (p)-[:SPAWNED_FROM]->(:ScenarioBranch {id: $branch_id})
   OR (p)-[:EVALUATED_AGAINST]->(:ScenarioBranch {id: $branch_id})
RETURN p.id AS id, p.content AS content, p.confidence AS confidence,
       p.created_at AS created_at, p.status AS status
```

*Parameters:* `branch_id = "BRANCH-AB12CD34"`

---

### 8. Compare actual vs. hypothetical affected entities

```cypher
-- ACTUAL side: entities affected by the real decision
MATCH path = (d:Decision {id: $actual_id})-[:AFFECTS*1..5]->(n)
RETURN n.id AS id, labels(n)[0] AS label, n.name AS name,
       length(path) AS depth, 'actual' AS side

UNION ALL

-- HYPOTHETICAL side: entities affected by hypothetical decisions in the branch
MATCH (b:ScenarioBranch {id: $branch_id})-[:CHANGES]->(h:Decision)
MATCH path = (h)-[:AFFECTS*1..5]->(n)
RETURN n.id AS id, labels(n)[0] AS label, n.name AS name,
       length(path) AS depth, 'hypothetical' AS side
```

*Parameters:* `actual_id = "DEC-001"`, `branch_id = "BRANCH-AB12CD34"`

---

### 9. Store an AgentRun node (MERGE with ON MATCH update)

```cypher
-- Uses MERGE so coordinator can update a run in-place after completion.
-- ON CREATE SET initialises; ON MATCH SET updates status and output on completion.
MERGE (a:AgentRun {id: $id})
ON CREATE SET
  a.agent_type   = $agent_type,
  a.started_at   = $started_at,
  a.completed_at = $completed_at,
  a.status       = $status,
  a.summary      = $summary,
  a.input_data   = $input_data,
  a.output_data  = $output_data
ON MATCH SET
  a.completed_at = $completed_at,
  a.status       = $status,
  a.summary      = $summary,
  a.output_data  = $output_data
RETURN a.id AS id, a.agent_type AS agent_type,
       a.started_at AS started_at, a.completed_at AS completed_at,
       a.status AS status, a.summary AS summary
```

*Parameters:* `id`, `agent_type`, `started_at`, `completed_at`, `status`, `summary`, `input_data`, `output_data`

---

### 10. Evaluation link: Prediction → Outcome

```cypher
-- Links a Prediction to an Outcome with a status property on the relationship.
-- ON CREATE SET ensures a duplicate evaluation does not overwrite the first.
MATCH (p:Prediction {id: $pred_id})
MATCH (o:Outcome {id: $out_id})
MERGE (p)-[r:EVALUATED_AGAINST]->(o)
ON CREATE SET r.status = $status, r.created_at = $created_at
RETURN true AS linked
```

*Parameters:* `pred_id`, `out_id`, `status ∈ {supported, contradicted, inconclusive}`, `created_at`

---

### 11. Retrieve prior coordinator runs for agent memory

```cypher
-- Retrieves the N most recent coordinator runs, ordered newest first.
-- Used by the Coordinator before each pipeline run to provide context
-- about previously executed simulations (agent memory pattern).
MATCH (a:AgentRun {agent_type: $agent_type})
RETURN a.id AS id, a.agent_type AS agent_type,
       a.started_at AS started_at, a.completed_at AS completed_at,
       a.status AS status, a.summary AS summary,
       a.input_data AS input_data, a.output_data AS output_data
ORDER BY a.started_at DESC
LIMIT 10
```

*Parameters:* `agent_type = "coordinator"`

---

### 12. Shortest path between any two nodes

```cypher
-- Finds the shortest directed path between two nodes identified by their
-- id property, following any relationship type up to 10 hops.
MATCH (a {id: $from_id}), (b {id: $to_id})
MATCH path = shortestPath((a)-[*1..10]->(b))
RETURN
  [n IN nodes(path) | n.id]            AS node_ids,
  [n IN nodes(path) | labels(n)[0]]    AS node_labels,
  [r IN relationships(path) | type(r)] AS rel_types
```

*Parameters:* `from_id = "DEC-001"`, `to_id = "PROJ-002"`

---

## Immutability Enforcement

The service layer in [`db/history.py`](../db/history.py) enforces the following rule on **every write path**:

> A node with `is_actual = true` must **never** be mutated or deleted.

The guard function [`assert_not_actual(node_dict, operation)`](../db/history.py) is called before any mutating operation and raises `HistoryViolationError` if the node is an actual-history record.

All write queries for actual nodes use `MERGE … ON CREATE SET` semantics so that a second write to the same `id` is a guaranteed no-op.

---

## Index Recommendations

For production workloads, create these indexes to accelerate the most common queries:

```cypher
-- Decision lookups
CREATE INDEX ON :Decision(id)
CREATE INDEX ON :Decision(is_actual)
CREATE INDEX ON :Decision(made_at)

-- Branch lookups
CREATE INDEX ON :ScenarioBranch(id)
CREATE INDEX ON :ScenarioBranch(status)

-- Prediction lookups
CREATE INDEX ON :Prediction(branch_id)
CREATE INDEX ON :Prediction(status)

-- AgentRun lookups
CREATE INDEX ON :AgentRun(agent_type)
CREATE INDEX ON :AgentRun(started_at)

-- Person / Project
CREATE INDEX ON :Person(id)
CREATE INDEX ON :Project(id)
```

These are created automatically by [`db/schema.py`](../db/schema.py) on first run.
