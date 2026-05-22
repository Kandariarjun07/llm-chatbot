"""Topology Validation Engine.

Detects cycles, invalid flows, improper queue/cache/DB placement,
and AI pipeline correctness before diagrams are finalized.
"""

from __future__ import annotations

from collections import defaultdict, deque

from app.architecture.rules import DEFAULT_RULES
from app.architecture.types import ArchitectureDiagram, Edge, EdgeType, LayerType, NodeType, ValidationReport


# ── Cycle Detection ───────────────────────────────────────────────────────────

class CycleDetector:
    """Tarjan-based cycle detection in the service subgraph."""

    def __init__(self, diagram: ArchitectureDiagram) -> None:
        self.diagram = diagram
        self._build_adjacency()

    def _build_adjacency(self) -> None:
        self.adj: dict[str, list[str]] = defaultdict(list)
        for edge in self.diagram.edges:
            src = self.diagram.get_node(edge.source)
            tgt = self.diagram.get_node(edge.target)
            if not src or not tgt:
                continue
            # Only consider service/worker/orchestrator edges for cycle checks
            if src.type in {
                NodeType.SERVICE, NodeType.WORKER, NodeType.ORCHESTRATOR, NodeType.RETRIEVER,
            } and tgt.type in {
                NodeType.SERVICE, NodeType.WORKER, NodeType.ORCHESTRATOR, NodeType.RETRIEVER,
            }:
                self.adj[edge.source].append(edge.target)

    def find_cycles(self) -> list[list[str]]:
        """Return list of cycles (as node ID lists) using DFS."""
        cycles: list[list[str]] = []
        visited: set[str] = set()
        rec_stack: set[str] = set()
        parent: dict[str, str | None] = {}

        def dfs(node: str, path: list[str]) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            for neighbor in self.adj[node]:
                if neighbor not in visited:
                    parent[neighbor] = node
                    dfs(neighbor, path)
                elif neighbor in rec_stack:
                    # Extract cycle
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    cycles.append(cycle)
            path.pop()
            rec_stack.remove(node)

        for node in list(self.adj.keys()):
            if node not in visited:
                parent[node] = None
                dfs(node, [])

        return cycles

    def human_readable_cycles(self) -> list[str]:
        cycles = self.find_cycles()
        out: list[str] = []
        for cycle in cycles:
            labels = []
            for nid in cycle[:-1]:
                n = self.diagram.get_node(nid)
                labels.append(n.label if n else nid)
            out.append(" -> ".join(labels) + f" -> {labels[0]}")
        return out


# ── Invalid Flow Detection ────────────────────────────────────────────────────

class InvalidFlowDetector:
    """Detects edges that violate layer or semantic constraints."""

    def __init__(self, diagram: ArchitectureDiagram) -> None:
        self.diagram = diagram

    def check(self) -> list[str]:
        violations: list[str] = []
        for edge in self.diagram.edges:
            src = self.diagram.get_node(edge.source)
            tgt = self.diagram.get_node(edge.target)
            if not src or not tgt:
                violations.append(f"Edge references missing node: {edge.source} -> {edge.target}")
                continue

            # Check for client -> data direct
            if src.type == NodeType.CLIENT and tgt.type in {NodeType.DATABASE, NodeType.CACHE, NodeType.VECTOR_DB}:
                violations.append(
                    f"INVALID FLOW: Client '{src.label}' directly accesses data layer '{tgt.label}'."
                )

            # Check for async edge to synchronous-only target
            if edge.is_async and tgt.type == NodeType.AI_MODEL:
                # AI models usually accept async queue tasks, so this is OK
                pass

            # Check for data layer -> service layer (backwards)
            if src.layer == LayerType.DATA and tgt.layer == LayerType.CLIENT:
                violations.append(
                    f"INVALID FLOW: Data layer '{src.label}' flows back to client '{tgt.label}'. Use a service layer."
                )

            # Check for queue -> queue direct (should go through worker)
            if src.type in {NodeType.QUEUE, NodeType.EVENT_BUS, NodeType.STREAM} and tgt.type in {NodeType.QUEUE, NodeType.EVENT_BUS, NodeType.STREAM}:
                violations.append(
                    f"INVALID FLOW: Queue '{src.label}' directly connects to queue '{tgt.label}'. Insert a worker/consumer."
                )

            # Check for AI model -> database without orchestration
            if src.type == NodeType.AI_MODEL and tgt.type == NodeType.DATABASE:
                violations.append(
                    f"INVALID FLOW: AI model '{src.label}' writes directly to database '{tgt.label}'. Route through a service."
                )

        return violations


# ── Queue Placement Validator ─────────────────────────────────────────────────

class QueuePlacementValidator:
    """Ensures queues decouple async systems and have consumers."""

    def __init__(self, diagram: ArchitectureDiagram) -> None:
        self.diagram = diagram

    def check(self) -> list[str]:
        violations: list[str] = []
        queues = [n for n in self.diagram.all_nodes() if n.type in {NodeType.QUEUE, NodeType.EVENT_BUS, NodeType.STREAM}]

        for queue in queues:
            producers = self.diagram.edges_to(queue.id)
            consumers = self.diagram.edges_from(queue.id)

            if not producers:
                violations.append(
                    f"QUEUE ISSUE: '{queue.label}' has no producers. It is disconnected from the flow."
                )
            if not consumers:
                violations.append(
                    f"QUEUE ISSUE: '{queue.label}' has no consumers. Add a worker/service that reads from it."
                )

            # Check if any producer also has direct sync edge to a consumer
            producer_ids = {e.source for e in producers}
            consumer_ids = {e.target for e in consumers}
            for pid in producer_ids:
                for cid in consumer_ids:
                    direct = [e for e in self.diagram.edges if e.source == pid and e.target == cid and not e.is_async]
                    if direct:
                        pnode = self.diagram.get_node(pid)
                        cnode = self.diagram.get_node(cid)
                        violations.append(
                            f"QUEUE ISSUE: '{pnode.label if pnode else pid}' has a direct sync edge to "
                            f"'{cnode.label if cnode else cid}' despite queue '{queue.label}'. Remove direct edge."
                        )

        return violations


# ── Cache Usage Validator ─────────────────────────────────────────────────────

class CacheUsageValidator:
    """Ensures caches are used for lookups, not as primary write targets."""

    def __init__(self, diagram: ArchitectureDiagram) -> None:
        self.diagram = diagram

    def check(self) -> list[str]:
        violations: list[str] = []
        caches = [n for n in self.diagram.all_nodes() if n.type == NodeType.CACHE]

        for cache in caches:
            incoming = self.diagram.edges_to(cache.id)
            outgoing = self.diagram.edges_from(cache.id)

            # Cache should have more reads than writes ideally
            writes = [e for e in incoming if e.type == EdgeType.PERSISTENCE]
            if writes:
                violations.append(
                    f"CACHE ISSUE: '{cache.label}' receives PERSISTENCE edges. Caches should use DATA_FLOW or CACHE_LOOKUP."
                )

            if not outgoing:
                violations.append(
                    f"CACHE ISSUE: '{cache.label}' has no outbound edges. Nothing reads from it."
                )

        return violations


# ── Bottleneck Detector ───────────────────────────────────────────────────────

class BottleneckDetector:
    """Identifies single points of failure and hotspots."""

    def __init__(self, diagram: ArchitectureDiagram) -> None:
        self.diagram = diagram

    def check(self) -> list[str]:
        bottlenecks: list[str] = []

        # Nodes with very high in-degree or out-degree
        for node in self.diagram.all_nodes():
            in_deg = len(self.diagram.edges_to(node.id))
            out_deg = len(self.diagram.edges_from(node.id))
            if in_deg > 5 or out_deg > 5:
                bottlenecks.append(
                    f"HOTSPOT: '{node.label}' has in={in_deg}, out={out_deg} edges. Consider decomposition or load balancing."
                )

        # Singleton stateful services without replicas
        for node in self.diagram.all_nodes():
            if node.is_stateful and node.type == NodeType.SERVICE and (node.replicas is None or node.replicas == 1):
                bottlenecks.append(
                    f"SPOF: Stateful service '{node.label}' is a singleton. Replicate or shard for HA."
                )

        # Single database for everything
        dbs = [n for n in self.diagram.all_nodes() if n.type == NodeType.DATABASE]
        if len(dbs) == 1:
            bottlenecks.append(
                f"SPOF: Only one database ('{dbs[0].label}') in the system. Consider read replicas or per-service DBs."
            )

        # Single gateway / LB
        gateways = [n for n in self.diagram.all_nodes() if n.type in {NodeType.GATEKEEPER, NodeType.EDGE}]
        if len(gateways) == 1 and gateways[0].type == NodeType.GATEKEEPER:
            bottlenecks.append(
                f"SPOF: Single gateway '{gateways[0].label}'. Add redundancy or regional LBs."
            )

        return bottlenecks


# ── Main Validator ──────────────────────────────────────────────────────────────

class TopologyValidator:
    """Orchestrates all validation passes."""

    def __init__(self, diagram: ArchitectureDiagram) -> None:
        self.diagram = diagram

    def validate(self) -> ValidationReport:
        errors: list[str] = []
        warnings: list[str] = []
        bottlenecks: list[str] = []
        cyclic_deps: list[str] = []
        suggestions: list[str] = []

        # 1. Semantic rules
        for rule in DEFAULT_RULES:
            result = rule.check(self.diagram)
            if result:
                for msg in result:
                    if "RULE VIOLATION" in msg:
                        errors.append(msg)
                    else:
                        warnings.append(msg)

        # 2. Cycle detection
        cycle_detector = CycleDetector(self.diagram)
        cycles = cycle_detector.human_readable_cycles()
        if cycles:
            cyclic_deps.extend(cycles)
            for c in cycles:
                errors.append(f"CYCLE DETECTED: {c}")

        # 3. Invalid flows
        flow_detector = InvalidFlowDetector(self.diagram)
        invalid_flows = flow_detector.check()
        if invalid_flows:
            errors.extend(invalid_flows)

        # 4. Queue placement
        queue_validator = QueuePlacementValidator(self.diagram)
        queue_issues = queue_validator.check()
        if queue_issues:
            warnings.extend(queue_issues)

        # 5. Cache usage
        cache_validator = CacheUsageValidator(self.diagram)
        cache_issues = cache_validator.check()
        if cache_issues:
            warnings.extend(cache_issues)

        # 6. Bottlenecks
        bottleneck_detector = BottleneckDetector(self.diagram)
        bottleneck_issues = bottleneck_detector.check()
        if bottleneck_issues:
            bottlenecks.extend(bottleneck_issues)

        # 7. Suggestions generation
        suggestions = self._generate_suggestions(errors, warnings, bottlenecks)

        # Score calculation
        score = self._compute_score(errors, warnings, bottlenecks, cyclic_deps)

        return ValidationReport(
            is_valid=len(errors) == 0,
            architecture_score=score,
            errors=errors,
            warnings=warnings,
            bottlenecks=bottlenecks,
            cyclic_dependencies=cyclic_deps,
            suggestions=suggestions,
        )

    def _generate_suggestions(
        self, errors: list[str], warnings: list[str], bottlenecks: list[str]
    ) -> list[str]:
        suggestions: list[str] = []

        if any("frontend" in e.lower() and "database" in e.lower() for e in errors):
            suggestions.append("Introduce an API gateway and service layer between frontend and databases.")

        if any("cycle" in e.lower() for e in errors):
            suggestions.append("Break service cycles by introducing an event bus or sagas for async decoupling.")

        if any("queue" in w.lower() for w in warnings):
            suggestions.append("Ensure all queues have at least one producer and one consumer; remove direct sync bypasses.")

        if any("redis" in e.lower() for e in errors):
            suggestions.append("Use Redis as a cache / session store; always pair with a durable primary database.")

        if any("vector db" in e.lower() for e in errors):
            suggestions.append("Route raw documents through an embedding service before writing to the vector database.")

        if any("spof" in b.lower() for b in bottlenecks):
            suggestions.append("Eliminate single points of failure: replicate stateful services, shard databases, and add redundant gateways.")

        if any("horizontal" in e.lower() and "stateful" in e.lower() for e in errors):
            suggestions.append("Move session/state out of horizontally-scaled services into Redis or a dedicated state store.")

        if not any(n.type == NodeType.OBSERVABILITY for n in self.diagram.all_nodes()):
            suggestions.append("Add observability (Prometheus, Grafana, Jaeger) to the architecture.")

        return suggestions

    def _compute_score(
        self, errors: list[str], warnings: list[str], bottlenecks: list[str], cycles: list[str]
    ) -> int:
        base = 100
        base -= len(errors) * 10
        base -= len(warnings) * 3
        base -= len(bottlenecks) * 4
        base -= len(cycles) * 8
        return max(0, min(100, base))
