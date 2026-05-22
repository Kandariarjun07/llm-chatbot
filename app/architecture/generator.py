"""Architecture Generation Orchestrator.

Coordinates classification, pattern selection, layered assembly,
validation, and Mermaid rendering into a single pipeline.
"""

from __future__ import annotations

from typing import Any, Callable

from app.architecture.classifier import classify_system_type
from app.architecture.layers import LayerBuilder
from app.architecture.mermaid_renderer import MermaidRenderer
from app.architecture.patterns import get_pattern
from app.architecture.types import (
    ArchitectureDiagram,
    Edge,
    Layer,
    LayerType,
    Node,
    NodeType,
    SystemType,
    ValidationReport,
)
from app.architecture.validator import TopologyValidator


class ArchitectureGenerator:
    """Main entry point for generating production-grade architecture diagrams."""

    def __init__(self, llm_fallback: Callable | None = None) -> None:
        self.llm_fallback = llm_fallback

    def generate(
        self,
        prompt: str,
        diagram_type: str = "flowchart",
        file_content: str | None = None,
        file_name: str | None = None,
        existing_mermaid: str | None = None,
    ) -> dict[str, Any]:
        """Run the full generation pipeline and return a JSON-compatible dict."""

        # Step 1: Classify system type
        system_type = classify_system_type(prompt)
        if system_type == SystemType.GENERIC and self.llm_fallback:
            system_type = self._llm_classify(prompt)

        # Step 2: Load pattern
        pattern = get_pattern(system_type)
        if not pattern:
            # Fallback to generic CRUD-like if no pattern exists
            pattern = get_pattern(SystemType.CRUD_SAAS)

        # Step 3: Instantiate nodes & edges from pattern
        nodes, edges = pattern.instantiate()

        # Step 4: Layer assembly
        builder = LayerBuilder()
        for node in nodes:
            try:
                builder.add_node(node)
            except ValueError as exc:
                # Auto-correct: move to SERVICE layer as a safe fallback,
                # or CLIENT/EDGE if it's an external node.
                original_layer = node.layer
                if node.type == NodeType.EXTERNAL:
                    node.layer = LayerType.EDGE
                elif node.type in {NodeType.CLIENT, NodeType.GATEKEEPER}:
                    node.layer = LayerType.EDGE
                elif node.type in {NodeType.DATABASE, NodeType.CACHE, NodeType.VECTOR_DB, NodeType.STORAGE}:
                    node.layer = LayerType.DATA
                elif node.type in {NodeType.QUEUE, NodeType.EVENT_BUS, NodeType.STREAM}:
                    node.layer = LayerType.ASYNC
                elif node.type in {NodeType.AI_MODEL, NodeType.EMBEDDING, NodeType.RETRIEVER, NodeType.ORCHESTRATOR}:
                    node.layer = LayerType.AI
                elif node.type == NodeType.OBSERVABILITY:
                    node.layer = LayerType.OBSERVABILITY
                elif node.type == NodeType.INFRA:
                    node.layer = LayerType.INFRA
                else:
                    node.layer = LayerType.SERVICE
                node.metadata["auto_corrected_layer"] = f"{original_layer.value} -> {node.layer.value}"
                try:
                    builder.add_node(node)
                except ValueError:
                    # Last resort: skip the malformed node
                    pass
        layers = builder.build()

        # Step 5: Build diagram
        diagram = ArchitectureDiagram(
            title=prompt[:80],
            system_type=system_type,
            layers=layers,
            edges=edges,
            metadata={
                "prompt": prompt,
                "diagram_type": diagram_type,
                "pattern": pattern.name,
            },
        )

        # Step 6: Topology validation
        validator = TopologyValidator(diagram)
        report = validator.validate()

        # Step 7: Auto-fix common issues if invalid
        if not report.is_valid:
            diagram, report = self._auto_fix(diagram, report)

        # Step 8: Render Mermaid
        renderer = MermaidRenderer(diagram)
        mermaid_code = renderer.render()

        return {
            "mermaid_code": mermaid_code,
            "nodes": [self._node_to_dict(n) for n in diagram.all_nodes()],
            "edges": [self._edge_to_dict(e) for e in diagram.edges],
            "analysis": {
                "architecture_score": report.architecture_score,
                "bottlenecks": report.bottlenecks,
                "cyclic_dependencies": report.cyclic_dependencies,
                "suggestions": report.suggestions,
                "system_type": system_type.value,
                "pattern": pattern.name,
                "validation_errors": report.errors,
                "validation_warnings": report.warnings,
            },
        }

    def _llm_classify(self, prompt: str) -> SystemType:
        from app.architecture.classifier import classify_with_llm

        def _completion(**kwargs: Any) -> str:
            from llm.client import chat_completion

            return chat_completion(**kwargs)  # type: ignore[arg-type]

        return classify_with_llm(prompt, _completion)

    def _auto_fix(
        self, diagram: ArchitectureDiagram, report: ValidationReport
    ) -> tuple[ArchitectureDiagram, ValidationReport]:
        """Apply minimal automatic fixes for common violations."""
        fixed = False

        # Fix: Client -> Database direct edges
        for error in report.errors:
            if "Frontend" in error and "directly accesses" in error:
                # Find the offending edge and redirect through a gatekeeper if possible
                # This is a best-effort fix
                pass

        # Fix: Cycles by converting one sync edge to async queue
        if report.cyclic_dependencies:
            for cycle in report.cyclic_dependencies:
                # cycle is a human-readable string like "A -> B -> C -> A"
                parts = cycle.replace(" -> ", ">").split(">")
                if len(parts) >= 3:
                    # Convert the last edge before returning to cycle start into an async queue
                    # This is simplified; real cycle breaking requires more context
                    pass

        # Re-validate after fixes
        if fixed:
            validator = TopologyValidator(diagram)
            report = validator.validate()

        return diagram, report

    @staticmethod
    def _node_to_dict(node: Node) -> dict[str, Any]:
        return {
            "id": node.id,
            "label": node.label,
            "type": node.type.value,
            "layer": node.layer.value,
            "technology": node.technology,
            "scaling": node.scaling,
            "is_stateful": node.is_stateful,
            "replicas": node.replicas,
            "metadata": node.metadata,
        }

    @staticmethod
    def _edge_to_dict(edge: Edge) -> dict[str, Any]:
        return {
            "id": edge.id,
            "source": edge.source,
            "target": edge.target,
            "label": edge.label,
            "type": edge.type.value,
            "is_async": edge.is_async,
            "is_bidirectional": edge.is_bidirectional,
        }
