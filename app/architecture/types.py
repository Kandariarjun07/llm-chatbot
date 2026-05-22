"""Core types and data models for the architecture generation engine."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class NodeType(str, Enum):
    """Semantic node classification for infrastructure components."""

    CLIENT = "client"
    GATEKEEPER = "gatekeeper"
    EDGE = "edge"
    SERVICE = "service"
    WORKER = "worker"
    DATABASE = "database"
    CACHE = "cache"
    QUEUE = "queue"
    EVENT_BUS = "event_bus"
    STREAM = "stream"
    STORAGE = "storage"
    AI_MODEL = "ai_model"
    EMBEDDING = "embedding"
    VECTOR_DB = "vector_db"
    RETRIEVER = "retriever"
    ORCHESTRATOR = "orchestrator"
    OBSERVABILITY = "observability"
    INFRA = "infra"
    EXTERNAL = "external"


class EdgeType(str, Enum):
    """Semantic edge classification for component relationships."""

    SYNC_HTTP = "sync_http"
    SYNC_RPC = "sync_rpc"
    ASYNC_MESSAGE = "async_message"
    ASYNC_EVENT = "async_event"
    DATA_FLOW = "data_flow"
    CONTROL_FLOW = "control_flow"
    PERSISTENCE = "persistence"
    CACHE_LOOKUP = "cache_lookup"
    DELEGATION = "delegation"
    AUTH = "auth"
    INFERENCE = "inference"
    EMBEDDING_FLOW = "embedding_flow"


class LayerType(str, Enum):
    """Architectural layers ordered from external to internal."""

    CLIENT = "client"
    EDGE = "edge"
    SERVICE = "service"
    ASYNC = "async"
    DATA = "data"
    AI = "ai"
    OBSERVABILITY = "observability"
    INFRA = "infra"


class SystemType(str, Enum):
    """High-level system classifications for pattern matching."""

    CRUD_SAAS = "crud_saas"
    REALTIME = "realtime"
    AI_SAAS = "ai_saas"
    RAG_PLATFORM = "rag_platform"
    AGENTIC_AI = "agentic_ai"
    VIDEO_STREAMING = "video_streaming"
    EVENT_DRIVEN_ECOMMERCE = "event_driven_ecommerce"
    KUBERNETES_INFRA = "kubernetes_infra"
    MULTI_REGION = "multi_region"
    GENERIC = "generic"


@dataclass
class Node:
    """A component in the architecture diagram."""

    id: str
    label: str
    type: NodeType
    layer: LayerType
    metadata: dict[str, Any] = field(default_factory=dict)
    owner: str = ""
    scaling: str = ""  # e.g., "horizontal", "vertical", "stateful", "serverless"
    is_stateful: bool = False
    replicas: int | None = None
    technology: str = ""  # e.g., "PostgreSQL", "FastAPI", "React"

    def __post_init__(self) -> None:
        if not self.id:
            self.id = f"node_{uuid.uuid4().hex[:8]}"


@dataclass
class Edge:
    """A directed relationship between two components."""

    source: str
    target: str
    label: str = ""
    type: EdgeType = EdgeType.SYNC_HTTP
    is_async: bool = False
    is_bidirectional: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        base = f"e_{self.source}_{self.target}"
        if self.label:
            return f"{base}_{self.label.lower().replace(' ', '_')}"
        return base


@dataclass
class Layer:
    """A collection of nodes at the same architectural layer."""

    layer_type: LayerType
    nodes: list[Node] = field(default_factory=list)
    direction: str = "TB"  # Mermaid direction within subgraph


@dataclass
class ArchitectureDiagram:
    """Complete architecture representation."""

    title: str
    system_type: SystemType
    layers: list[Layer] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def all_nodes(self) -> list[Node]:
        nodes: list[Node] = []
        for layer in self.layers:
            nodes.extend(layer.nodes)
        return nodes

    def get_node(self, node_id: str) -> Node | None:
        for node in self.all_nodes():
            if node.id == node_id:
                return node
        return None

    def nodes_in_layer(self, layer_type: LayerType) -> list[Node]:
        for layer in self.layers:
            if layer.layer_type == layer_type:
                return layer.nodes
        return []

    def edges_from(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.source == node_id]

    def edges_to(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.target == node_id]

    def add_layer(self, layer: Layer) -> None:
        self.layers.append(layer)

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)


@dataclass
class ValidationReport:
    """Result of topology validation."""

    is_valid: bool
    architecture_score: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    bottlenecks: list[str] = field(default_factory=list)
    cyclic_dependencies: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def merge(self, other: ValidationReport) -> ValidationReport:
        return ValidationReport(
            is_valid=self.is_valid and other.is_valid,
            architecture_score=min(self.architecture_score, other.architecture_score),
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
            bottlenecks=self.bottlenecks + other.bottlenecks,
            cyclic_dependencies=self.cyclic_dependencies + other.cyclic_dependencies,
            suggestions=self.suggestions + other.suggestions,
        )
