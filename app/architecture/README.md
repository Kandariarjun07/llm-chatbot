# Architecture Diagram Generation Engine

## Overview

This engine replaces the previous LLM-only diagram generation with a **structured, pattern-based pipeline** that reasons like a senior distributed-systems architect. It classifies the prompt, instantiates a production-grade topology template, validates it against semantic infrastructure rules, and renders clean Mermaid output.

## Design Goals

- **Stop buzzword hallucination**: Every node and edge is grounded in a known architectural pattern.
- **Layered reasoning**: Components are placed into canonical layers (Client → Edge → Service → Async → Data → AI → Observability → Infra).
- **Semantic validation**: Invalid flows (frontend → DB, queue bypass, Redis as primary store) are caught before rendering.
- **Real-world patterns**: 9 built-in templates covering CRUD SaaS, Realtime, AI SaaS, RAG, Agentic AI, Video Streaming, Event-Driven Ecommerce, Kubernetes, and Multi-Region systems.

---

## Pipeline Architecture

```
User Prompt
    |
    v
+------------------+
|  Classifier      |  <-- keyword heuristics + optional LLM fallback
+------------------+
    |
    v
+------------------+
|  Pattern Engine  |  <-- TopologyPattern with nodes + canonical edges
+------------------+
    |
    v
+------------------+
|  Layer Builder   |  <-- validates node types per layer, orders layers
+------------------+
    |
    v
+------------------+
|  Validator       |  <-- cycles, invalid flows, queue/cache/DB rules,
|                   |      bottleneck detection, AI pipeline checks
+------------------+
    |
    v
+------------------+
|  Auto-Fix        |  <-- best-effort corrections (optional)
+------------------+
    |
    v
+------------------+
|  Mermaid Renderer|  <-- subgraphs per layer, directional consistency,
|                   |      minimized crossings, semantic styling
+------------------+
    |
    v
  Output JSON
```

---

## Module Reference

| Module | Responsibility |
|--------|-------------|
| `types.py` | Core dataclasses: `Node`, `Edge`, `Layer`, `ArchitectureDiagram`, `ValidationReport`, enums for `NodeType`, `EdgeType`, `LayerType`, `SystemType`. |
| `rules.py` | Semantic infrastructure rules: no frontend→DB, gateway before services, Redis not persistent, vector DB usage, queue decoupling, RAG flow correctness, agentic planner/executor loops, etc. |
| `patterns.py` | `TopologyPattern` dataclass + 9 built-in templates. Each template defines node templates (layer, type, technology, scaling) and canonical edges. |
| `layers.py` | `LayerConfig` per `LayerType` (allowed node types, inbound/outbound constraints). `LayerBuilder` assembles nodes into ordered layers. |
| `classifier.py` | `classify_system_type()` using keyword heuristics. Optional `classify_with_llm()` fallback. |
| `validator.py` | `TopologyValidator` orchestrates: cycle detection (Tarjan/DFS), invalid flow detection, queue placement, cache usage, bottleneck detection, and runs all rules from `rules.py`. |
| `mermaid_renderer.py` | `MermaidRenderer` generates subgraph-per-layer flowcharts with semantic shapes, arrow styles, and CSS class definitions. |
| `generator.py` | `ArchitectureGenerator` ties the pipeline together: classify → pattern → layer → validate → auto-fix → render. |

---

## Built-In Patterns

1. **CRUD SaaS** — React SPA, API Gateway, Auth/App Services, RabbitMQ, PostgreSQL, Redis, S3.
2. **Realtime** — WebSocket servers, Presence Service, Redis Pub/Sub, Kafka, sticky-session LB.
3. **AI SaaS** — Inference Service, Model Registry, Celery Queue, OpenAI / self-hosted LLM.
4. **RAG Platform** — Upload/Query Services, Chunking, Embedding Worker, Context Builder, Vector DB.
5. **Agentic AI** — Planner, Executor, Tool Registry, Memory Store, Vector Memory, LLM, feedback loop.
6. **Video Streaming** — Manifest Service, Transcode Workers, CDN, S3, HLS/DASH players.
7. **Event-Driven Ecommerce** — Order/Inventory/Payment Services, Kafka saga, per-service DBs.
8. **Kubernetes Infra** — Ingress, Service Mesh (Istio), ArgoCD, CloudNativePG, Observability stack.
9. **Multi-Region** — Global DNS, regional LBs, replication worker, cross-region DB failover.

---

## Validation Rules

- **NoFrontendToDatabaseRule**: Clients never touch DBs directly.
- **GatewayBeforeServicesRule**: External clients must pass through a gateway.
- **RedisNotPersistentRule**: Redis cannot be the sole persistent store.
- **VectorDbUsageRule**: Vector DBs receive embedding flows, not raw relational data.
- **DatabaseOwnershipRule**: Warn when too many services share one DB.
- **QueueDecouplingRule**: Producers and consumers should not have direct sync edges if a queue exists.
- **AsyncInferenceQueueRule**: LLM inference should have async queue paths.
- **StatelessScalingRule**: Horizontally-scaled services must not be stateful.
- **WebSocketScalingRule**: WebSocket systems need sticky sessions or pub/sub state.
- **RAGFlowRule**: RAG systems must show retriever → context builder → LLM.
- **PlannerExecutorLoopRule**: Agentic systems must have planner, executor, and feedback loop.

---

## Mermaid Improvements

- **Subgraphs per layer**: Each `LayerType` becomes a Mermaid `subgraph`.
- **Semantic shapes**:
  - Client: rounded rectangle `([...])`
  - Database: cylinder `[(...)]`
  - Cache: standard rectangle (dashed stroke via class)
  - Queue/Event Bus: rhombus `{{...}}`
  - AI Model: circle `((...))`
  - Stream: curved path `[/.../]`
- **Arrow styles**:
  - Async / Auth: `-.->`
  - Sync HTTP / RPC: `-->`
- **CSS classDefs**: Color-coded by node type for visual hierarchy.
- **Directional consistency**: `TB` for service/data layers, `LR` for client/edge/observability.

---

## API Integration

`api/diagram_routes.py` now:

1. Calls `ArchitectureGenerator.generate()` first.
2. Only falls back to LLM when:
   - The user uploads code or an existing diagram (refinement mode).
   - The classifier returns `GENERIC` and the optional LLM classifier is enabled.
3. Analysis endpoint uses `TopologyValidator` directly, with LLM as a fallback for empty payloads.

This means:
- **Fast, deterministic output** for common architectures (no API latency for pattern-based generation).
- **LLM enhancement only when needed** (code import, custom/evolving diagrams).
- **Higher correctness** because the validator rejects invalid topologies before they are shown.

---

## Extending the Engine

### Add a new pattern

```python
from app.architecture.patterns import TopologyPattern, PATTERN_REGISTRY
from app.architecture.types import SystemType

MY_PATTERN = TopologyPattern(
    system_type=SystemType.MY_TYPE,
    name="My System",
    description="...",
    node_templates=[...],
    edge_templates=[...],
)

PATTERN_REGISTRY[SystemType.MY_TYPE] = MY_PATTERN
```

### Add a new validation rule

```python
from app.architecture.rules import ArchitectureRule

class MyRule(ArchitectureRule):
    name = "my_rule"
    description = "..."
    def check(self, diagram):
        return ["violation message"] if bad else []

DEFAULT_RULES.append(MyRule())
```

---

## Future Roadmap

1. **Interactive evolution**: Accept existing Mermaid, diff against pattern, suggest incremental changes.
2. **Cost estimation**: Add cloud-cost heuristics per node type.
3. **Threat modeling**: Auto-generate STRIDE annotations per edge.
4. **Terraform export**: Generate IaC stubs from the topology.
5. **Dynamic scaling**: Recommend replica counts based on projected load.
