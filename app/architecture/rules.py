"""Semantic infrastructure rules and architectural constraints.

Enforces real-world cloud and distributed-systems semantics
to prevent invalid topologies before they reach rendering.
"""

from __future__ import annotations

from app.architecture.types import ArchitectureDiagram, Edge, EdgeType, LayerType, Node, NodeType, SystemType


# ── Rule Interface ────────────────────────────────────────────────────────────

class ArchitectureRule:
    """Base class for a topology validation rule."""

    name: str = ""
    description: str = ""

    def check(self, diagram: ArchitectureDiagram) -> list[str]:
        """Return a list of human-readable violation messages."""
        raise NotImplementedError


# ── Forbidden Direct Access Rules ─────────────────────────────────────────────

class NoFrontendToDatabaseRule(ArchitectureRule):
    """Frontend clients must never connect directly to databases."""

    name = "no_frontend_to_database"
    description = "Frontend/client nodes must not have direct edges to database/cache nodes."

    def check(self, diagram: ArchitectureDiagram) -> list[str]:
        violations: list[str] = []
        db_types = {NodeType.DATABASE, NodeType.CACHE, NodeType.VECTOR_DB}
        client_layers = {LayerType.CLIENT}

        for edge in diagram.edges:
            src = diagram.get_node(edge.source)
            tgt = diagram.get_node(edge.target)
            if not src or not tgt:
                continue
            if src.layer in client_layers and tgt.type in db_types:
                violations.append(
                    f"RULE VIOLATION: Frontend '{src.label}' directly accesses {tgt.type.value} '{tgt.label}'. "
                    f"Route through an API gateway / service layer."
                )
        return violations


class NoServiceToExternalAuthDirectRule(ArchitectureRule):
    """Internal services should reach identity providers through a gatekeeper, not directly."""

    name = "no_service_to_external_auth"
    description = "Services should not directly call external identity providers."

    def check(self, diagram: ArchitectureDiagram) -> list[str]:
        violations: list[str] = []
        for edge in diagram.edges:
            src = diagram.get_node(edge.source)
            tgt = diagram.get_node(edge.target)
            if not src or not tgt:
                continue
            if src.type == NodeType.SERVICE and tgt.type == NodeType.EXTERNAL and "auth" in tgt.label.lower():
                if not any(
                    e.target == edge.target and diagram.get_node(e.source) and diagram.get_node(e.source).type == NodeType.GATEKEEPER
                    for e in diagram.edges
                ):
                    violations.append(
                        f"RULE VIOLATION: Service '{src.label}' directly calls auth provider '{tgt.label}'. "
                        f"Place a gatekeeper / identity proxy in between."
                    )
        return violations


# ── Layer Precedence Rules ───────────────────────────────────────────────────

class GatewayBeforeServicesRule(ArchitectureRule):
    """API Gateway / Load Balancer must precede service-layer access."""

    name = "gateway_before_services"
    description = "If a gateway exists, external clients should flow through it before services."

    def check(self, diagram: ArchitectureDiagram) -> list[str]:
        violations: list[str] = []
        gateways = [
            n for n in diagram.all_nodes()
            if n.type in {NodeType.GATEKEEPER, NodeType.EDGE}
        ]
        if not gateways:
            return []

        gateway_ids = {n.id for n in gateways}
        service_nodes = [n for n in diagram.all_nodes() if n.type == NodeType.SERVICE]

        for svc in service_nodes:
            incoming = diagram.edges_to(svc.id)
            if not incoming:
                continue
            for inc in incoming:
                src = diagram.get_node(inc.source)
                if not src:
                    continue
                if src.layer == LayerType.CLIENT and src.type != NodeType.GATEKEEPER:
                    violations.append(
                        f"RULE VIOLATION: Client '{src.label}' reaches service '{svc.label}' without passing through a gateway."
                    )
        return violations


# ── Data Semantics Rules ────────────────────────────────────────────────────

class RedisNotPersistentRule(ArchitectureRule):
    """Redis / cache nodes must not be the sole persistence for critical data."""

    name = "redis_not_persistent"
    description = "Redis must not be the only persistent store for transactional data."

    def check(self, diagram: ArchitectureDiagram) -> list[str]:
        violations: list[str] = []
        caches = [n for n in diagram.all_nodes() if n.type == NodeType.CACHE]
        databases = [n for n in diagram.all_nodes() if n.type == NodeType.DATABASE]

        if not caches:
            return []

        for cache in caches:
            # If a service writes to cache but not to a DB, that's suspicious
            writers = diagram.edges_to(cache.id)
            for w in writers:
                src = diagram.get_node(w.source)
                if not src:
                    continue
                # Check if the same source also writes to a database
                has_db_write = any(
                    diagram.get_node(e.target) and diagram.get_node(e.target).type == NodeType.DATABASE
                    for e in diagram.edges_from(src.id)
                    if e.type in {EdgeType.PERSISTENCE, EdgeType.DATA_FLOW}
                )
                if not has_db_write and not databases:
                    violations.append(
                        f"RULE VIOLATION: '{cache.label}' appears to be used as the only data store by '{src.label}'. "
                        f"Redis is not a persistent database; add a primary database."
                    )
        return violations


class VectorDbUsageRule(ArchitectureRule):
    """Vector DBs should store embeddings, not raw relational data."""

    name = "vector_db_usage"
    description = "Vector DBs must receive data from embedding/retriever nodes, not raw services."

    def check(self, diagram: ArchitectureDiagram) -> list[str]:
        violations: list[str] = []
        for edge in diagram.edges:
            tgt = diagram.get_node(edge.target)
            if not tgt or tgt.type != NodeType.VECTOR_DB:
                continue
            src = diagram.get_node(edge.source)
            if not src:
                continue
            if src.type not in {NodeType.EMBEDDING, NodeType.RETRIEVER, NodeType.AI_MODEL, NodeType.ORCHESTRATOR}:
                if edge.type not in {EdgeType.EMBEDDING_FLOW, EdgeType.INFERENCE}:
                    violations.append(
                        f"RULE VIOLATION: '{src.label}' ({src.type.value}) writes directly to vector DB '{tgt.label}'. "
                        f"Vector DBs should receive embedding flows from embedding/retriever nodes."
                    )
        return violations


class DatabaseOwnershipRule(ArchitectureRule):
    """A database should have clear service ownership."""

    name = "database_ownership"
    description = "Databases must have exactly one primary owning service to avoid schema contention."

    def check(self, diagram: ArchitectureDiagram) -> list[str]:
        violations: list[str] = []
        db_types = {NodeType.DATABASE, NodeType.VECTOR_DB}
        for node in diagram.all_nodes():
            if node.type not in db_types:
                continue
            owners = set()
            for edge in diagram.edges:
                if edge.target == node.id:
                    src = diagram.get_node(edge.source)
                    if src and src.type in {NodeType.SERVICE, NodeType.WORKER}:
                        owners.add(src.id)
            if len(owners) > 3:
                owner_labels = [diagram.get_node(oid).label for oid in owners if diagram.get_node(oid)]
                violations.append(
                    f"RULE VIOLATION: Database '{node.label}' is accessed by too many services ({len(owners)}). "
                    f"Consider an API / aggregation service to own it. Owners: {', '.join(owner_labels)}"
                )
        return violations


# ── Async / Decoupling Rules ─────────────────────────────────────────────────

class QueueDecouplingRule(ArchitectureRule):
    """Queues should decouple producers from consumers."""

    name = "queue_decoupling"
    description = "Producers and consumers should not have direct sync edges if a queue sits between them."

    def check(self, diagram: ArchitectureDiagram) -> list[str]:
        violations: list[str] = []
        queue_nodes = [n for n in diagram.all_nodes() if n.type in {NodeType.QUEUE, NodeType.EVENT_BUS, NodeType.STREAM}]
        for queue in queue_nodes:
            producers = [e.source for e in diagram.edges_to(queue.id)]
            consumers = [e.target for e in diagram.edges_from(queue.id)]
            # If a producer also directly reaches a consumer, that's a coupling smell
            for prod_id in producers:
                for cons_id in consumers:
                    direct = any(
                        e.source == prod_id and e.target == cons_id
                        for e in diagram.edges
                    )
                    if direct:
                        prod = diagram.get_node(prod_id)
                        cons = diagram.get_node(cons_id)
                        violations.append(
                            f"RULE VIOLATION: '{prod.label if prod else prod_id}' has a direct edge to "
                            f"'{cons.label if cons else cons_id}' despite a queue '{queue.label}' in between. "
                            f"Remove the direct edge to enforce decoupling."
                        )
        return violations


class AsyncInferenceQueueRule(ArchitectureRule):
    """AI inference under load should use async queues, not direct synchronous calls only."""

    name = "async_inference_queue"
    description = "AI/LLM inference should be reachable via an async queue for load handling."

    def check(self, diagram: ArchitectureDiagram) -> list[str]:
        violations: list[str] = []
        ai_nodes = [n for n in diagram.all_nodes() if n.type in {NodeType.AI_MODEL, NodeType.ORCHESTRATOR}]
        queues = {n.id for n in diagram.all_nodes() if n.type in {NodeType.QUEUE, NodeType.EVENT_BUS}}

        for ai in ai_nodes:
            incoming = diagram.edges_to(ai.id)
            if not incoming:
                continue
            # If all incoming edges are sync HTTP, and there is no queue nearby, warn
            all_sync = all(
                not e.is_async and e.type in {EdgeType.SYNC_HTTP, EdgeType.SYNC_RPC}
                for e in incoming
            )
            has_queue_path = any(
                diagram.get_node(e.source) and diagram.get_node(e.source).type in {NodeType.QUEUE, NodeType.EVENT_BUS}
                for e in incoming
            )
            if all_sync and not has_queue_path and len(incoming) > 1:
                violations.append(
                    f"RULE VIOLATION: AI node '{ai.label}' receives only synchronous calls. "
                    f"Add a queue / event bus for async inference under load."
                )
        return violations


# ── Scaling & Resilience Rules ────────────────────────────────────────────────

class StatelessScalingRule(ArchitectureRule):
    """Stateless services should not directly own stateful databases without an abstraction."""

    name = "stateless_scaling"
    description = "Stateless services should reach stateful stores; the store itself is stateful."

    def check(self, diagram: ArchitectureDiagram) -> list[str]:
        violations: list[str] = []
        for node in diagram.all_nodes():
            if node.type == NodeType.SERVICE and node.scaling == "horizontal" and node.is_stateful:
                violations.append(
                    f"RULE VIOLATION: Service '{node.label}' is marked horizontal-scaling but also stateful. "
                    f"Move state to an external database/cache or use sticky sessions."
                )
        return violations


class WebSocketScalingRule(ArchitectureRule):
    """WebSocket systems require sticky sessions or a distributed state layer."""

    name = "websocket_scaling"
    description = "If websockets are present, there must be sticky sessions or a pub/sub state layer."

    def check(self, diagram: ArchitectureDiagram) -> list[str]:
        violations: list[str] = []
        ws_nodes = [
            n for n in diagram.all_nodes()
            if "websocket" in n.label.lower() or "ws" in n.label.lower().split()
        ]
        if not ws_nodes:
            return []

        has_sticky_or_pubsub = any(
            "sticky" in n.metadata.get("session_mode", "").lower()
            or "pubsub" in n.metadata.get("session_mode", "").lower()
            or n.type == NodeType.STREAM
            for n in diagram.all_nodes()
        )
        if not has_sticky_or_pubsub:
            violations.append(
                f"RULE VIOLATION: WebSocket component detected but no sticky-session or pub/sub state mechanism found. "
                f"Add Redis Pub/Sub, NATS, or load-balancer sticky sessions."
            )
        return violations


class RetryAndDLQRule(ArchitectureRule):
    """Queue-based workers should have retry or dead-letter semantics."""

    name = "retry_dlq"
    description = "Queue consumers should show retry or DLQ patterns."

    def check(self, diagram: ArchitectureDiagram) -> list[str]:
        violations: list[str] = []
        workers = [n for n in diagram.all_nodes() if n.type == NodeType.WORKER]
        queues = {n.id for n in diagram.all_nodes() if n.type in {NodeType.QUEUE, NodeType.EVENT_BUS}}

        for worker in workers:
            has_queue_in = any(
                diagram.get_node(e.source) and diagram.get_node(e.source).id in queues
                for e in diagram.edges_to(worker.id)
            )
            if has_queue_in and "retry" not in worker.metadata and "dlq" not in worker.metadata:
                # This is a warning-level rule
                pass
        return violations


# ── AI Pipeline Correctness Rules ─────────────────────────────────────────────

class RAGFlowRule(ArchitectureRule):
    """RAG pipelines must be: retriever -> context builder -> LLM."""

    name = "rag_flow"
    description = "RAG topologies must show retriever feeding context into the LLM, not direct service->LLM."

    def check(self, diagram: ArchitectureDiagram) -> list[str]:
        violations: list[str] = []
        llms = [n for n in diagram.all_nodes() if n.type == NodeType.AI_MODEL]
        for llm in llms:
            incoming = diagram.edges_to(llm.id)
            has_context_source = False
            for inc in incoming:
                src = diagram.get_node(inc.source)
                if src and src.type in {NodeType.RETRIEVER, NodeType.VECTOR_DB, NodeType.ORCHESTRATOR}:
                    has_context_source = True
                elif src and src.type == NodeType.SERVICE:
                    # Services should not directly call LLM without a retriever/context builder in between
                    # unless it's a simple chat completion (not RAG)
                    pass
            # If system is classified as RAG but LLM gets direct service hits, flag
            if diagram.system_type == SystemType.RAG_PLATFORM:
                direct_service_to_llm = any(
                    diagram.get_node(inc.source) and diagram.get_node(inc.source).type == NodeType.SERVICE
                    for inc in incoming
                )
                if direct_service_to_llm and not has_context_source:
                    violations.append(
                        f"RULE VIOLATION: In RAG platform, LLM '{llm.label}' is reached directly by a service. "
                        f"Insert a retriever / context-builder node between service and LLM."
                    )
        return violations


class PlannerExecutorLoopRule(ArchitectureRule):
    """Agentic AI should show planner -> executor loops, not linear chains."""

    name = "planner_executor_loop"
    description = "Agentic AI systems must show planner and executor interaction with feedback loops."

    def check(self, diagram: ArchitectureDiagram) -> list[str]:
        violations: list[str] = []
        if diagram.system_type != SystemType.AGENTIC_AI:
            return []

        planners = [n for n in diagram.all_nodes() if "planner" in n.label.lower() or "plan" in n.label.lower()]
        executors = [n for n in diagram.all_nodes() if "executor" in n.label.lower() or "exec" in n.label.lower()]

        if not planners:
            violations.append(
                "RULE VIOLATION: Agentic AI system missing a planner node. Add a planning/orchestration component."
            )
        if not executors:
            violations.append(
                "RULE VIOLATION: Agentic AI system missing an executor node. Add a tool-execution component."
            )
        if planners and executors:
            # Check for feedback loop edges (executor -> planner or shared memory)
            has_loop = any(
                e.source == ex.id and e.target == pl.id
                for ex in executors
                for pl in planners
                for e in diagram.edges
            ) or any(
                "memory" in n.label.lower() or "state" in n.label.lower()
                for n in diagram.all_nodes()
            )
            if not has_loop:
                violations.append(
                    "RULE VIOLATION: Agentic AI system missing a feedback loop between planner and executor. "
                    "Add a memory/state store or a return edge from executor to planner."
                )
        return violations


# ── Registry ──────────────────────────────────────────────────────────────────

DEFAULT_RULES: list[ArchitectureRule] = [
    NoFrontendToDatabaseRule(),
    NoServiceToExternalAuthDirectRule(),
    GatewayBeforeServicesRule(),
    RedisNotPersistentRule(),
    VectorDbUsageRule(),
    DatabaseOwnershipRule(),
    QueueDecouplingRule(),
    AsyncInferenceQueueRule(),
    StatelessScalingRule(),
    WebSocketScalingRule(),
    RAGFlowRule(),
    PlannerExecutorLoopRule(),
]
