import json
import re
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth_routes import get_current_user
from app.db import get_diagrams, get_diagram, upsert_diagram, delete_diagram
from app.architecture.generator import ArchitectureGenerator
from app.architecture.types import ArchitectureDiagram, Edge, Node
from app.architecture.validator import TopologyValidator
from llm.client import chat_completion

router = APIRouter(prefix="/diagram", tags=["diagram"])

# ── Pydantic Request/Response Models ──────────────────────────────────────────

class DiagramItem(BaseModel):
    id: str = Field(..., min_length=1)
    title: str = Field(default="Untitled Diagram")
    diagramType: str = Field(default="flowchart")
    createdAt: float
    updatedAt: float
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    mermaidCode: str = Field(default="")
    metadata: dict[str, Any] = Field(default_factory=dict)

class DiagramGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    diagram_type: str = "flowchart"
    file_content: str | None = None
    file_name: str | None = None
    existing_mermaid: str | None = None

class DiagramAnalyzeRequest(BaseModel):
    mermaid_code: str = Field(default="")
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)

# ── CRUD Handlers ─────────────────────────────────────────────────────────────

@router.get("/history", response_model=list[DiagramItem])
async def list_diagrams(user: dict[str, Any] = Depends(get_current_user)) -> list[dict]:
    uid = user["user_id"]
    return await get_diagrams(uid)

@router.get("/history/{diag_id}", response_model=DiagramItem)
async def get_diagram_details(diag_id: str, user: dict[str, Any] = Depends(get_current_user)) -> dict:
    uid = user["user_id"]
    diag = await get_diagram(uid, diag_id)
    if not diag:
        raise HTTPException(status_code=404, detail="Diagram not found")
    return diag

@router.post("/history")
async def save_diagram(body: DiagramItem, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, str]:
    await upsert_diagram(
        user["user_id"],
        {
            "id": body.id,
            "title": body.title,
            "diagramType": body.diagramType,
            "createdAt": body.createdAt,
            "updatedAt": body.updatedAt,
            "nodes": body.nodes,
            "edges": body.edges,
            "mermaidCode": body.mermaidCode,
            "metadata": body.metadata,
        },
    )
    return {"status": "saved"}

@router.delete("/history/{diag_id}")
async def remove_diagram(diag_id: str, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, str]:
    if await delete_diagram(user["user_id"], diag_id):
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Diagram not found")

# ── AI Orchestration Handlers ─────────────────────────────────────────────────

@router.post("/generate")
async def generate_diagram(req: DiagramGenerateRequest, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Generates a production-grade architecture diagram using the pattern engine + LLM enhancement."""
    generator = ArchitectureGenerator()

    # Step 1: Generate structured topology via the architecture engine
    result = generator.generate(
        prompt=req.prompt,
        diagram_type=req.diagram_type,
        file_content=req.file_content,
        file_name=req.file_name,
        existing_mermaid=req.existing_mermaid,
    )

    # Step 2: Optional LLM enhancement for custom/evolving diagrams
    # If the user uploaded code or an existing diagram, ask the LLM to refine the engine output
    if req.file_content or req.existing_mermaid:
        result = await _llm_enhance_diagram(result, req)

    return result


async def _llm_enhance_diagram(
    base_result: dict[str, Any], req: DiagramGenerateRequest
) -> dict[str, Any]:
    """Use LLM to refine the engine-generated diagram when code or existing diagrams are provided."""
    system_prompt = (
        "You are an expert Principal AI Software Architect.\n"
        "You are given a machine-generated architecture diagram (Mermaid + node-edge graph).\n"
        "Your job is to refine it based on additional code context or an existing diagram,\n"
        "and return ONLY a JSON object matching this schema:\n"
        "{\n"
        '  "mermaid_code": "string",\n'
        '  "nodes": [{"id": "...", "label": "...", "type": "..."}],\n'
        '  "edges": [{"id": "...", "source": "...", "target": "...", "label": "..."}],\n'
        '  "analysis": {"architecture_score": 80, "bottlenecks": [], "cyclic_dependencies": [], "suggestions": []}\n'
        "}\n"
        "Rules: preserve the layered subgraph structure; fix any Mermaid syntax issues; "
        "do not hallucinate components not supported by the context.\n"
    )

    user_query = f"Base diagram:\n{json.dumps(base_result, indent=2)}\n\n"
    if req.file_content:
        user_query += f"Code context ({req.file_name or 'unnamed'}):\n```\n{req.file_content}\n```\n"
    if req.existing_mermaid:
        user_query += f"Existing diagram:\n```mermaid\n{req.existing_mermaid}\n```\n"

    llm_response_text = ""
    try:
        llm_response_text = chat_completion(
            messages=[{"role": "user", "content": user_query}],
            model_choice="Gemini",
            system=system_prompt,
            temperature=0.2,
        )

        if not llm_response_text or llm_response_text.startswith("Error:"):
            # Return the base result if LLM fails
            return base_result

        clean_text = llm_response_text.strip()
        json_match = re.search(r'(\{.*\})', clean_text, re.DOTALL)
        if json_match:
            clean_text = json_match.group(1)
        else:
            if clean_text.startswith("```json"):
                clean_text = clean_text[7:]
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3]
            clean_text = clean_text.strip()

        parsed = json.loads(clean_text)
        if not isinstance(parsed, dict):
            return base_result

        # Merge LLM output with base result, preferring LLM fields when present
        for key in ["mermaid_code", "nodes", "edges", "analysis"]:
            if key in parsed and parsed[key]:
                base_result[key] = parsed[key]

        return base_result

    except Exception:
        # On any failure, return the engine-generated result
        return base_result

@router.post("/analyze")
async def analyze_diagram(req: DiagramAnalyzeRequest, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Analyzes a diagram using the structured TopologyValidator, with LLM as optional fallback."""
    # Build a temporary ArchitectureDiagram from the request payload
    nodes: list[Node] = []
    edges: list[Edge] = []

    for n in req.nodes:
        try:
            from app.architecture.types import NodeType, LayerType

            nodes.append(
                Node(
                    id=str(n.get("id", "")),
                    label=str(n.get("label", "")),
                    type=NodeType(n.get("type", "service")),
                    layer=LayerType(n.get("layer", "service")),
                    technology=str(n.get("technology", "")),
                    scaling=str(n.get("scaling", "")),
                    is_stateful=bool(n.get("is_stateful", False)),
                    metadata=n.get("metadata", {}),
                )
            )
        except Exception:
            # Skip malformed nodes
            continue

    for e in req.edges:
        try:
            from app.architecture.types import EdgeType

            edges.append(
                Edge(
                    source=str(e.get("source", "")),
                    target=str(e.get("target", "")),
                    label=str(e.get("label", "")),
                    type=EdgeType(e.get("type", "sync_http")),
                    is_async=bool(e.get("is_async", False)),
                    is_bidirectional=bool(e.get("is_bidirectional", False)),
                    metadata=e.get("metadata", {}),
                )
            )
        except Exception:
            continue

    from app.architecture.layers import LayerBuilder

    builder = LayerBuilder()
    for node in nodes:
        try:
            builder.add_node(node)
        except ValueError:
            continue

    diagram = ArchitectureDiagram(
        title="Analyzed Diagram",
        system_type=__import__("app.architecture.types", fromlist=["SystemType"]).SystemType.GENERIC,
        layers=builder.build(),
        edges=edges,
    )

    validator = TopologyValidator(diagram)
    report = validator.validate()

    # Optional LLM fallback for narrative depth when the validator has little to say
    if not report.errors and not report.warnings and not report.bottlenecks:
        return await _llm_analyze_fallback(req)

    return {
        "architecture_score": report.architecture_score,
        "bottlenecks": report.bottlenecks,
        "cyclic_dependencies": report.cyclic_dependencies,
        "suggestions": report.suggestions,
        "validation_errors": report.errors,
        "validation_warnings": report.warnings,
        "engine": "TopologyValidator",
    }


async def _llm_analyze_fallback(req: DiagramAnalyzeRequest) -> dict[str, Any]:
    """Use LLM for analysis when the structured validator has no findings."""
    system_prompt = (
        "You are an expert Principal AI Software Architect.\n"
        "Analyze the provided Mermaid diagram and return ONLY this JSON:\n"
        "{\n"
        '  "architecture_score": 0 to 100,\n'
        '  "bottlenecks": [...],\n'
        '  "cyclic_dependencies": [...],\n'
        '  "suggestions": [...]\n'
        "}\n"
    )
    user_query = f"```mermaid\n{req.mermaid_code}\n```\n"
    if req.nodes:
        user_query += f"Nodes: {json.dumps(req.nodes)}\n"
    if req.edges:
        user_query += f"Edges: {json.dumps(req.edges)}\n"

    try:
        text = chat_completion(
            messages=[{"role": "user", "content": user_query}],
            model_choice="Gemini",
            system=system_prompt,
            temperature=0.1,
        )
        if not text or text.startswith("Error:"):
            raise ValueError("LLM failed")

        clean = text.strip()
        m = re.search(r'(\{.*\})', clean, re.DOTALL)
        if m:
            clean = m.group(1)
        elif clean.startswith("```json"):
            clean = clean[7:].rsplit("```", 1)[0].strip()

        parsed = json.loads(clean)
        if not isinstance(parsed, dict):
            parsed = {}

        return {
            "architecture_score": parsed.get("architecture_score", 80),
            "bottlenecks": parsed.get("bottlenecks", []),
            "cyclic_dependencies": parsed.get("cyclic_dependencies", []),
            "suggestions": parsed.get("suggestions", []),
            "engine": "LLM",
        }
    except Exception:
        return {
            "architecture_score": 80,
            "bottlenecks": [],
            "cyclic_dependencies": [],
            "suggestions": ["Add more service nodes to enable structured analysis."],
            "engine": "fallback",
        }
