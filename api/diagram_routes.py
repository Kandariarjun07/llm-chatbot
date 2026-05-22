import json
import time
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth_routes import get_current_user
from app.db import get_diagrams, get_diagram, upsert_diagram, delete_diagram
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
    return get_diagrams(uid)

@router.get("/history/{diag_id}", response_model=DiagramItem)
async def get_diagram_details(diag_id: str, user: dict[str, Any] = Depends(get_current_user)) -> dict:
    uid = user["user_id"]
    diag = get_diagram(uid, diag_id)
    if not diag:
        raise HTTPException(status_code=404, detail="Diagram not found")
    return diag

@router.post("/history")
async def save_diagram(body: DiagramItem, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, str]:
    upsert_diagram(
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
    if delete_diagram(user["user_id"], diag_id):
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Diagram not found")

# ── AI Orchestration Handlers ─────────────────────────────────────────────────

@router.post("/generate")
async def generate_diagram(req: DiagramGenerateRequest, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Generates a complete system architecture diagram from a text prompt or imported code files."""
    system_prompt = (
        "You are an expert Principal AI Software Architect.\n"
        "Your task is to generate clean, syntax-perfect Mermaid.js flowchart markdown AND its equivalent canonical node-edge graph representation.\n"
        "You MUST respond ONLY with a single JSON object. Do not include markdown code block tags around the JSON.\n\n"
        "The output JSON object MUST conform EXACTLY to this schema:\n"
        "{\n"
        '  "mermaid_code": "A string of valid Mermaid flowchart syntax. Use flowchart TD, flowchart LR, graph TD, etc. Avoid parenthesis inside node names to prevent syntax errors. Always put node text labels in double quotes. Example: A[\\\"UI Module\\\"] --> B[\\\"Auth Service\\\"]",\n'
        '  "nodes": [\n'
        '    {"id": "node_id", "label": "Human Readable Label", "type": "client | service | database | cloud | queue | gatekeeper"}\n'
        "  ],\n"
        '  "edges": [\n'
        '    {"id": "e_source_target", "source": "source_id", "target": "target_id", "label": "Optional Link Text"}\n'
        "  ],\n"
        '  "analysis": {\n'
        '    "architecture_score": 85,\n'
        '    "bottlenecks": ["List of scale/coupling/single-point-of-failure issues identified in this design"],\n'
        '    "cyclic_dependencies": ["List of cycles e.g. Service A -> Service B -> Service A"],\n'
        '    "suggestions": ["Architectural improvement proposals"]\n'
        "  }\n"
        "}\n\n"
        "Classification rules for 'type' of nodes:\n"
        "- 'client': User Interfaces, frontends, browsers, mobile applications, SPAs.\n"
        "- 'service': REST API servers, microservices, backend computing services, docker containers, worker processes.\n"
        "- 'database': Databases (PostgreSQL, MongoDB), caches (Redis, Memcached), persistent storage buckets.\n"
        "- 'cloud': Third-party external APIs, SaaS interfaces (Stripe, Twilio, Sendgrid), CDNs, DNS resolvers.\n"
        "- 'queue': Message queues, event brokers, publishers, Kafka, RabbitMQ, SQS.\n"
        "- 'gatekeeper': Authentication servers (Firebase Auth, Auth0), API Gateways, Firewalls, Load Balancers.\n"
    )

    user_query = f"Prompt: {req.prompt}\n"
    user_query += f"Diagram type: {req.diagram_type}\n"
    
    if req.file_content:
        user_query += f"\nUploaded code context:\nFile Name: {req.file_name or 'unnamed'}\n```\n{req.file_content}\n```\n"
    
    if req.existing_mermaid:
        user_query += f"\nExisting Mermaid diagram to evolve/edit:\n```mermaid\n{req.existing_mermaid}\n```\n"

    llm_response_text = ""
    try:
        # Call LLM. We will prioritize Gemini for better structured output and compliance
        llm_response_text = chat_completion(
            messages=[{"role": "user", "content": user_query}],
            model_choice="Gemini",
            system=system_prompt,
            temperature=0.2
        )
        
        if not llm_response_text:
            raise ValueError("Empty response received from AI model.")

        if llm_response_text.startswith("Error:"):
            raise ValueError(llm_response_text)
        
        # Clean response string to extract JSON (robust regex-based extraction)
        import re
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
        
        parsed_json = json.loads(clean_text)
        
        # Resilient schema check and defaults mapping
        if not isinstance(parsed_json, dict):
            parsed_json = {}
        
        if "mermaid_code" not in parsed_json:
            parsed_json["mermaid_code"] = ""
        if "nodes" not in parsed_json or not isinstance(parsed_json["nodes"], list):
            parsed_json["nodes"] = []
        if "edges" not in parsed_json or not isinstance(parsed_json["edges"], list):
            parsed_json["edges"] = []
        if "analysis" not in parsed_json or not isinstance(parsed_json["analysis"], dict):
            parsed_json["analysis"] = {
                "architecture_score": 80,
                "bottlenecks": [],
                "cyclic_dependencies": [],
                "suggestions": []
            }
            
        return parsed_json
        
    except Exception as e:
        # Fallback response in case of JSON parse errors or API failures
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate structured diagram from AI: {str(e)} (LLM Response: {llm_response_text[:300]}...)"
        )

@router.post("/analyze")
async def analyze_diagram(req: DiagramAnalyzeRequest, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Analyzes a diagram's Mermaid syntax and layout architecture, reporting on coupling, cycles, and bottlenecks."""
    system_prompt = (
        "You are an expert Principal AI Software Architect.\n"
        "Your task is to analyze the provided Mermaid diagram architecture and return a structured JSON report.\n"
        "The output JSON object MUST conform EXACTLY to this schema:\n"
        "{\n"
        '  "architecture_score": 0 to 100 integer,\n'
        '  "bottlenecks": ["List of single point of failures, data bottlenecks, or coupling issues"],\n'
        '  "cyclic_dependencies": ["List of any circular service calls found"],\n'
        '  "suggestions": ["Constructive suggestions for improved scalability, high-availability, or modularity"]\n'
        "}\n"
        "Respond ONLY with valid JSON. Do not write text outside the JSON structure."
    )

    user_query = f"Evaluate this system architecture:\n```mermaid\n{req.mermaid_code}\n```\n"
    if req.nodes:
        user_query += f"\nGraph Nodes: {json.dumps(req.nodes)}\n"
    if req.edges:
        user_query += f"\nGraph Edges: {json.dumps(req.edges)}\n"

    llm_response_text = ""
    try:
        llm_response_text = chat_completion(
            messages=[{"role": "user", "content": user_query}],
            model_choice="Gemini",
            system=system_prompt,
            temperature=0.1
        )
        
        if not llm_response_text:
            raise ValueError("Empty response received from AI model.")

        if llm_response_text.startswith("Error:"):
            raise ValueError(llm_response_text)
        
        # Clean response string to extract JSON (robust regex-based extraction)
        import re
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
        
        parsed_json = json.loads(clean_text)
        
        # Resilient schema check and defaults mapping
        if not isinstance(parsed_json, dict):
            parsed_json = {}
        
        if "architecture_score" not in parsed_json:
            parsed_json["architecture_score"] = 80
        if "bottlenecks" not in parsed_json or not isinstance(parsed_json["bottlenecks"], list):
            parsed_json["bottlenecks"] = []
        if "cyclic_dependencies" not in parsed_json or not isinstance(parsed_json["cyclic_dependencies"], list):
            parsed_json["cyclic_dependencies"] = []
        if "suggestions" not in parsed_json or not isinstance(parsed_json["suggestions"], list):
            parsed_json["suggestions"] = []
            
        return parsed_json
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to analyze diagram: {str(e)} (LLM Response: {llm_response_text[:300]}...)"
        )
