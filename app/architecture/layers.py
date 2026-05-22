"""Layered architecture generation.

Systems are built layer-by-layer with valid inter-layer connection constraints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app.architecture.types import Layer, LayerType, Node, NodeType


# ── Layer Configuration ───────────────────────────────────────────────────────

@dataclass
class LayerConfig:
    """Configuration for a valid architectural layer."""

    layer_type: LayerType
    allowed_node_types: set[NodeType] = field(default_factory=set)
    allowed_outbound_layers: set[LayerType] = field(default_factory=set)
    allowed_inbound_layers: set[LayerType] = field(default_factory=set)
    direction: str = "TB"


LAYER_REGISTRY: dict[LayerType, LayerConfig] = {
    LayerType.CLIENT: LayerConfig(
        layer_type=LayerType.CLIENT,
        allowed_node_types={
            NodeType.CLIENT,
            NodeType.EXTERNAL,
        },
        allowed_outbound_layers={LayerType.EDGE, LayerType.SERVICE},
        allowed_inbound_layers=set(),
        direction="LR",
    ),
    LayerType.EDGE: LayerConfig(
        layer_type=LayerType.EDGE,
        allowed_node_types={
            NodeType.GATEKEEPER,
            NodeType.EDGE,
            NodeType.EXTERNAL,
        },
        allowed_outbound_layers={LayerType.SERVICE, LayerType.CLIENT},
        allowed_inbound_layers={LayerType.CLIENT, LayerType.SERVICE},
        direction="LR",
    ),
    LayerType.SERVICE: LayerConfig(
        layer_type=LayerType.SERVICE,
        allowed_node_types={
            NodeType.SERVICE,
            NodeType.WORKER,
            NodeType.ORCHESTRATOR,
            NodeType.RETRIEVER,
        },
        allowed_outbound_layers={
            LayerType.EDGE,
            LayerType.ASYNC,
            LayerType.DATA,
            LayerType.AI,
            LayerType.SERVICE,
            LayerType.OBSERVABILITY,
        },
        allowed_inbound_layers={
            LayerType.CLIENT,
            LayerType.EDGE,
            LayerType.ASYNC,
            LayerType.SERVICE,
            LayerType.AI,
        },
        direction="TB",
    ),
    LayerType.ASYNC: LayerConfig(
        layer_type=LayerType.ASYNC,
        allowed_node_types={
            NodeType.QUEUE,
            NodeType.EVENT_BUS,
            NodeType.STREAM,
        },
        allowed_outbound_layers={LayerType.SERVICE, LayerType.DATA},
        allowed_inbound_layers={LayerType.SERVICE, LayerType.AI},
        direction="TB",
    ),
    LayerType.DATA: LayerConfig(
        layer_type=LayerType.DATA,
        allowed_node_types={
            NodeType.DATABASE,
            NodeType.CACHE,
            NodeType.VECTOR_DB,
            NodeType.STORAGE,
        },
        allowed_outbound_layers={LayerType.SERVICE, LayerType.AI},
        allowed_inbound_layers={
            LayerType.SERVICE,
            LayerType.AI,
            LayerType.ASYNC,
        },
        direction="TB",
    ),
    LayerType.AI: LayerConfig(
        layer_type=LayerType.AI,
        allowed_node_types={
            NodeType.AI_MODEL,
            NodeType.EMBEDDING,
            NodeType.ORCHESTRATOR,
            NodeType.RETRIEVER,
            NodeType.EXTERNAL,
        },
        allowed_outbound_layers={
            LayerType.ASYNC,
            LayerType.DATA,
            LayerType.SERVICE,
            LayerType.OBSERVABILITY,
        },
        allowed_inbound_layers={
            LayerType.SERVICE,
            LayerType.ASYNC,
            LayerType.DATA,
            LayerType.AI,
        },
        direction="TB",
    ),
    LayerType.OBSERVABILITY: LayerConfig(
        layer_type=LayerType.OBSERVABILITY,
        allowed_node_types={
            NodeType.OBSERVABILITY,
            NodeType.EXTERNAL,
        },
        allowed_outbound_layers=set(),
        allowed_inbound_layers={
            LayerType.CLIENT,
            LayerType.EDGE,
            LayerType.SERVICE,
            LayerType.ASYNC,
            LayerType.DATA,
            LayerType.AI,
            LayerType.INFRA,
        },
        direction="LR",
    ),
    LayerType.INFRA: LayerConfig(
        layer_type=LayerType.INFRA,
        allowed_node_types={
            NodeType.INFRA,
            NodeType.EXTERNAL,
        },
        allowed_outbound_layers={LayerType.OBSERVABILITY},
        allowed_inbound_layers=set(),
        direction="LR",
    ),
}


# ── Layer Builder ─────────────────────────────────────────────────────────────

class LayerBuilder:
    """Assembles nodes into layers respecting architectural constraints."""

    def __init__(self) -> None:
        self._layers: dict[LayerType, Layer] = {
            lt: Layer(layer_type=lt, nodes=[], direction=LAYER_REGISTRY[lt].direction)
            for lt in LayerType
        }

    def add_node(self, node: Node) -> None:
        """Add a node to its designated layer."""
        config = LAYER_REGISTRY.get(node.layer)
        if not config:
            raise ValueError(f"Unknown layer type: {node.layer}")
        if node.type not in config.allowed_node_types:
            raise ValueError(
                f"Node type '{node.type.value}' is not allowed in layer '{node.layer.value}'. "
                f"Allowed: {[t.value for t in config.allowed_node_types]}"
            )
        self._layers[node.layer].nodes.append(node)

    def build(self) -> list[Layer]:
        """Return layers in canonical order, omitting empty ones."""
        order = [
            LayerType.CLIENT,
            LayerType.EDGE,
            LayerType.SERVICE,
            LayerType.ASYNC,
            LayerType.DATA,
            LayerType.AI,
            LayerType.OBSERVABILITY,
            LayerType.INFRA,
        ]
        return [self._layers[lt] for lt in order if self._layers[lt].nodes]

    def is_valid_layer_transition(
        self, source_layer: LayerType, target_layer: LayerType
    ) -> bool:
        """Check if an edge between two layers is architecturally valid."""
        src_cfg = LAYER_REGISTRY.get(source_layer)
        tgt_cfg = LAYER_REGISTRY.get(target_layer)
        if not src_cfg or not tgt_cfg:
            return False
        return target_layer in src_cfg.allowed_outbound_layers


# ── Layer-Aware Node Factory ─────────────────────────────────────────────────

@dataclass
class NodeTemplate:
    """Reusable template for creating a node in a specific layer."""

    label: str
    node_type: NodeType
    layer: LayerType
    technology: str = ""
    scaling: str = ""
    is_stateful: bool = False
    metadata: dict = field(default_factory=dict)

    def instantiate(self, node_id: str = "") -> Node:
        return Node(
            id=node_id or self.label.lower().replace(" ", "_").replace("-", "_"),
            label=self.label,
            type=self.node_type,
            layer=self.layer,
            technology=self.technology,
            scaling=self.scaling,
            is_stateful=self.is_stateful,
            metadata=self.metadata,
        )


def make_layered_nodes(templates: list[NodeTemplate]) -> list[Layer]:
    """Create a layered topology from a list of node templates."""
    builder = LayerBuilder()
    for tmpl in templates:
        builder.add_node(tmpl.instantiate())
    return builder.build()
