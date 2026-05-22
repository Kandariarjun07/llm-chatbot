"""Architecture Classifier.

Classifies a free-text prompt into a known SystemType using keyword
heuristics and an optional LLM fallback for ambiguous cases.
"""

from __future__ import annotations

from app.architecture.types import SystemType


# ── Keyword Heuristics ────────────────────────────────────────────────────────

CLASSIFIER_MAP: dict[SystemType, list[str]] = {
    SystemType.CRUD_SAAS: [
        "crud", "saas", "cms", "blog", "dashboard", "admin panel", "erp",
        "inventory management", "hrms", "booking", "appointment", "tenant",
        "multi-tenant", "b2b", "b2c", "subscription",
    ],
    SystemType.REALTIME: [
        "realtime", "real-time", "websocket", "socket", "live", "presence",
        "chat", "messaging", "notification", "push", "collaborative", "whiteboard",
        "game", "gaming", "multiplayer", "live update",
    ],
    SystemType.AI_SAAS: [
        "ai saas", "ai platform", "llm api", "inference api", "model serving",
        "fine-tuning", "model registry", "ml platform", "prediction api",
        "classifier service", "ai gateway",
    ],
    SystemType.RAG_PLATFORM: [
        "rag", "retrieval augmented", "retrieval-augmented", "knowledge base",
        "document qa", "chat with pdf", "semantic search", "embeddings pipeline",
        "vector search", "chunking", "indexing", "context retrieval",
    ],
    SystemType.AGENTIC_AI: [
        "agent", "agentic", "autonomous", "planner", "executor", "tool use",
        "function calling", "re-act", "react pattern", "langchain", "crew",
        "multi-agent", "swarm", "orchestrator", "ai workflow",
    ],
    SystemType.VIDEO_STREAMING: [
        "video", "streaming", "hls", "dash", "vod", "live stream",
        "transcoding", "encoder", "media server", "ott", "broadcast",
        "adaptive bitrate", "manifest", "segment",
    ],
    SystemType.EVENT_DRIVEN_ECOMMERCE: [
        "ecommerce", "e-commerce", "marketplace", "shop", "store", "order",
        "payment", "checkout", "cart", "inventory", "shipping", "saga",
        "event driven", "event-driven", "cqrs", "event sourcing",
    ],
    SystemType.KUBERNETES_INFRA: [
        "kubernetes", "k8s", "helm", "argo", "gitops", "cicd", "ci/cd",
        "ingress", "service mesh", "istio", "cluster", "container",
        "operator", "pod", "deployment", "namespace",
    ],
    SystemType.MULTI_REGION: [
        "multi-region", "multi region", "global", "geo", "failover",
        "disaster recovery", "dr", "cross region", "replication", "cdc",
        "active-active", "active-passive", "edge computing", "cdn global",
    ],
}


def classify_system_type(prompt: str) -> SystemType:
    """Classify prompt into a SystemType using keyword matching."""
    prompt_lower = prompt.lower()
    scores: dict[SystemType, int] = {st: 0 for st in SystemType}

    for system_type, keywords in CLASSIFIER_MAP.items():
        for kw in keywords:
            if kw in prompt_lower:
                scores[system_type] += 1

    # Tie-break: prefer more specific types over GENERIC
    best = max(scores, key=lambda st: scores[st])
    if scores[best] == 0:
        return SystemType.GENERIC
    return best


def classify_with_llm(prompt: str, chat_completion_fn) -> SystemType:
    """Optional LLM fallback for ambiguous prompts.

    *chat_completion_fn* should accept messages and system prompt and return text.
    """
    system = (
        "You are an architecture classifier. Respond ONLY with one of these exact labels:\n"
        "CRUD_SAAS, REALTIME, AI_SAAS, RAG_PLATFORM, AGENTIC_AI, "
        "VIDEO_STREAMING, EVENT_DRIVEN_ECOMMERCE, KUBERNETES_INFRA, MULTI_REGION, GENERIC\n"
        "No extra text."
    )
    user = f"Classify this architecture description: {prompt}"
    try:
        text = chat_completion_fn(
            messages=[{"role": "user", "content": user}],
            system=system,
            temperature=0.0,
        )
        text = text.strip().upper().replace(" ", "_")
        return SystemType(text)
    except Exception:
        return SystemType.GENERIC
