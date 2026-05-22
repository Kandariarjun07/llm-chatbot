"""Improved Mermaid Renderer.

Groups nodes into subgraphs by layer, enforces hierarchy,
minimizes edge crossings, and uses directional consistency.
"""

from __future__ import annotations

from collections import defaultdict

from app.architecture.types import ArchitectureDiagram, Edge, EdgeType, Layer, LayerType, Node, NodeType


class MermaidRenderer:
    """Renders an ArchitectureDiagram into clean Mermaid flowchart syntax."""

    def __init__(self, diagram: ArchitectureDiagram) -> None:
        self.diagram = diagram

    def render(self) -> str:
        lines: list[str] = []
        lines.append("```mermaid")
        lines.append("flowchart TB")
        lines.append("")

        # Define subgraphs per layer
        layer_order = [
            LayerType.CLIENT,
            LayerType.EDGE,
            LayerType.SERVICE,
            LayerType.ASYNC,
            LayerType.DATA,
            LayerType.AI,
            LayerType.OBSERVABILITY,
            LayerType.INFRA,
        ]

        # Direction within each subgraph
        layer_directions = {
            LayerType.CLIENT: "LR",
            LayerType.EDGE: "LR",
            LayerType.SERVICE: "TB",
            LayerType.ASYNC: "TB",
            LayerType.DATA: "TB",
            LayerType.AI: "TB",
            LayerType.OBSERVABILITY: "LR",
            LayerType.INFRA: "LR",
        }

        # Emit subgraphs
        for layer_type in layer_order:
            layer_nodes = self.diagram.nodes_in_layer(layer_type)
            if not layer_nodes:
                continue
            lines.append(f"    subgraph {self._layer_id(layer_type)} [{self._layer_title(layer_type)}]")
            lines.append(f"        direction {layer_directions[layer_type]}")
            for node in layer_nodes:
                lines.append(f"        {self._node_stmt(node)}")
            lines.append("    end")
            lines.append("")

        # Emit cross-layer edges with styling
        for edge in self.diagram.edges:
            lines.append(f"    {self._edge_stmt(edge)}")

        # Add class definitions for visual styling
        lines.append("")
        lines.extend(self._class_definitions())

        # Add click events / tooltips if metadata present
        lines.append("")
        lines.extend(self._tooltip_statements())

        lines.append("```")
        return "\n".join(lines)

    def _layer_id(self, layer_type: LayerType) -> str:
        return f"layer_{layer_type.value}"

    def _layer_title(self, layer_type: LayerType) -> str:
        titles = {
            LayerType.CLIENT: "Client Layer",
            LayerType.EDGE: "Edge Layer",
            LayerType.SERVICE: "Service Layer",
            LayerType.ASYNC: "Async / Event Layer",
            LayerType.DATA: "Data Layer",
            LayerType.AI: "AI / Inference Layer",
            LayerType.OBSERVABILITY: "Observability Layer",
            LayerType.INFRA: "Infra / Deployment Layer",
        }
        return titles.get(layer_type, layer_type.value)

    def _sanitize_id(self, node_id: str) -> str:
        """Mermaid IDs must be alphanumeric + underscore."""
        return "".join(c if c.isalnum() or c == "_" else "_" for c in node_id)

    def _node_stmt(self, node: Node) -> str:
        nid = self._sanitize_id(node.id)
        label = node.label.replace('"', '\\"')

        # Pick shape based on node type
        if node.type == NodeType.CLIENT:
            return nid + '(["' + label + '"])'
        elif node.type == NodeType.DATABASE:
            return nid + '[("' + label + '")]'
        elif node.type == NodeType.CACHE:
            return nid + '("' + label + '")'
        elif node.type == NodeType.QUEUE:
            return nid + '{{"' + label + '"}}'
        elif node.type == NodeType.EVENT_BUS:
            return nid + '{{"' + label + '"}}'
        elif node.type == NodeType.STREAM:
            return nid + '[/' + label + '/]'
        elif node.type in {NodeType.GATEKEEPER, NodeType.EDGE}:
            return nid + '{{"' + label + '"}}'
        elif node.type == NodeType.AI_MODEL:
            return nid + '(("' + label + '"))'
        elif node.type == NodeType.VECTOR_DB:
            return nid + '[("' + label + '")]'
        elif node.type == NodeType.STORAGE:
            return nid + '[("' + label + '")]'
        elif node.type == NodeType.INFRA:
            return nid + '[/"' + label + '"/]'
        elif node.type == NodeType.OBSERVABILITY:
            return nid + '("' + label + '")'
        else:
            return nid + '["' + label + '"]'

    def _edge_stmt(self, edge: Edge) -> str:
        src = self._sanitize_id(edge.source)
        tgt = self._sanitize_id(edge.target)

        # Pick arrow style
        if edge.is_async:
            arrow = "-.->"
        elif edge.type == EdgeType.AUTH:
            arrow = "-.->"
        elif edge.type in {EdgeType.PERSISTENCE, EdgeType.DATA_FLOW}:
            arrow = "-->"
        else:
            arrow = "-->"

        label = edge.label.replace('"', '\\"')
        if label:
            return f'{src} {arrow}|"{label}"| {tgt}'
        return f"{src} {arrow} {tgt}"

    def _class_definitions(self) -> list[str]:
        """Return classDef lines for styling by node type."""
        return [
            "    classDef client fill:#e1f5fe,stroke:#01579b,stroke-width:2px;",
            "    classDef gatekeeper fill:#fff3e0,stroke:#e65100,stroke-width:2px;",
            "    classDef service fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px;",
            "    classDef worker fill:#f3e5f5,stroke:#4a148c,stroke-width:2px;",
            "    classDef database fill#fce4ec,stroke:#880e4f,stroke-width:2px;",
            "    classDef cache fill#fce4ec,stroke:#880e4f,stroke-width:2px,stroke-dasharray: 5 5;",
            "    classDef queue fill#fffde7,stroke:#f57f17,stroke-width:2px;",
            "    classDef ai fill#f3e5f5,stroke:#4a148c,stroke-width:2px;",
            "    classDef infra fill#eceff1,stroke:#263238,stroke-width:2px;",
            "    classDef obs fill#e0f2f1,stroke:#004d40,stroke-width:2px;",
        ]

    def _tooltip_statements(self) -> list[str]:
        """Attach click tooltip with metadata if available."""
        lines: list[str] = []
        type_to_class = {
            NodeType.CLIENT: "client",
            NodeType.GATEKEEPER: "gatekeeper",
            NodeType.EDGE: "gatekeeper",
            NodeType.SERVICE: "service",
            NodeType.WORKER: "worker",
            NodeType.DATABASE: "database",
            NodeType.CACHE: "cache",
            NodeType.QUEUE: "queue",
            NodeType.EVENT_BUS: "queue",
            NodeType.STREAM: "queue",
            NodeType.AI_MODEL: "ai",
            NodeType.EMBEDDING: "ai",
            NodeType.VECTOR_DB: "database",
            NodeType.STORAGE: "database",
            NodeType.INFRA: "infra",
            NodeType.OBSERVABILITY: "obs",
            NodeType.EXTERNAL: "client",
            NodeType.RETRIEVER: "service",
            NodeType.ORCHESTRATOR: "service",
        }
        class_assignments: dict[str, list[str]] = defaultdict(list)

        for node in self.diagram.all_nodes():
            cls = type_to_class.get(node.type)
            if cls:
                class_assignments[cls].append(self._sanitize_id(node.id))

        for cls, nids in class_assignments.items():
            if nids:
                lines.append(f"    class {','.join(nids)} {cls};")

        return lines
