"""Architecture Pattern Engine.

Reusable topology templates for common production system archetypes.
Each pattern defines nodes, layers, and canonical edges.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app.architecture.layers import NodeTemplate
from app.architecture.types import Edge, EdgeType, Layer, LayerType, Node, NodeType, SystemType


@dataclass
class TopologyPattern:
    """A reusable architecture template."""

    system_type: SystemType
    name: str
    description: str
    node_templates: list[NodeTemplate] = field(default_factory=list)
    edge_templates: list[Edge] = field(default_factory=list)

    @staticmethod
    def _sanitize_id(raw: str) -> str:
        """Sanitize a raw label or ID to match NodeTemplate.instantiate() logic."""
        return raw.lower().replace(" ", "_").replace("-", "_")

    def instantiate(self) -> tuple[list[Node], list[Edge]]:
        """Generate concrete nodes and edges from the pattern."""
        nodes: list[Node] = []
        node_map: dict[str, Node] = {}

        for tmpl in self.node_templates:
            node = tmpl.instantiate()
            # Ensure unique IDs by appending index if duplicate
            base_id = node.id
            counter = 1
            while node.id in node_map:
                node.id = f"{base_id}_{counter}"
                counter += 1
            nodes.append(node)
            node_map[node.id] = node

        edges: list[Edge] = []
        for edge in self.edge_templates:
            # Resolve edge endpoints using sanitized IDs (same logic as node creation)
            source_id = self._sanitize_id(edge.source)
            target_id = self._sanitize_id(edge.target)
            if source_id in node_map and target_id in node_map:
                edges.append(
                    Edge(
                        source=source_id,
                        target=target_id,
                        label=edge.label,
                        type=edge.type,
                        is_async=edge.is_async,
                        metadata=edge.metadata,
                    )
                )

        return nodes, edges


# ── Helper Factories ─────────────────────────────────────────────────────────

def _node(label: str, node_type: NodeType, layer: LayerType, **kwargs) -> NodeTemplate:
    return NodeTemplate(label=label, node_type=node_type, layer=layer, **kwargs)


def _edge(src: str, tgt: str, label: str = "", edge_type: EdgeType = EdgeType.SYNC_HTTP, async_: bool = False) -> Edge:
    return Edge(source=src, target=tgt, label=label, type=edge_type, is_async=async_)


# ── 1. CRUD SaaS ────────────────────────────────────────────────────────────

CRUD_SAAS_PATTERN = TopologyPattern(
    system_type=SystemType.CRUD_SAAS,
    name="CRUD SaaS",
    description="Standard multi-tenant CRUD application with caching and async workers.",
    node_templates=[
        _node("React SPA", NodeType.CLIENT, LayerType.CLIENT, technology="React"),
        _node("Mobile App", NodeType.CLIENT, LayerType.CLIENT, technology="React Native"),
        _node("Cloudflare CDN", NodeType.EDGE, LayerType.EDGE, technology="Cloudflare"),
        _node("API Gateway", NodeType.GATEKEEPER, LayerType.EDGE, technology="Kong / AWS API Gateway"),
        _node("Auth Service", NodeType.SERVICE, LayerType.SERVICE, technology="FastAPI / Go", scaling="horizontal"),
        _node("App Service", NodeType.SERVICE, LayerType.SERVICE, technology="FastAPI / Node", scaling="horizontal", is_stateful=False),
        _node("Notification Worker", NodeType.WORKER, LayerType.SERVICE, technology="Celery / BullMQ", scaling="horizontal"),
        _node("RabbitMQ", NodeType.QUEUE, LayerType.ASYNC, technology="RabbitMQ"),
        _node("PostgreSQL", NodeType.DATABASE, LayerType.DATA, technology="PostgreSQL", is_stateful=True, scaling="vertical"),
        _node("Redis Cache", NodeType.CACHE, LayerType.DATA, technology="Redis", scaling="horizontal"),
        _node("S3 Buckets", NodeType.STORAGE, LayerType.DATA, technology="AWS S3"),
        _node("Prometheus + Grafana", NodeType.OBSERVABILITY, LayerType.OBSERVABILITY, technology="Prometheus/Grafana"),
        _node("Kubernetes", NodeType.INFRA, LayerType.INFRA, technology="Kubernetes"),
    ],
    edge_templates=[
        _edge("react_spa", "cloudflare_cdn", "HTTPS", EdgeType.SYNC_HTTP),
        _edge("mobile_app", "cloudflare_cdn", "HTTPS", EdgeType.SYNC_HTTP),
        _edge("cloudflare_cdn", "api_gateway", "route", EdgeType.SYNC_HTTP),
        _edge("api_gateway", "auth_service", "verify JWT", EdgeType.AUTH),
        _edge("api_gateway", "app_service", "proxy", EdgeType.DELEGATION),
        _edge("app_service", "redis_cache", "cache lookup", EdgeType.CACHE_LOOKUP),
        _edge("app_service", "postgresql", "CRUD", EdgeType.PERSISTENCE),
        _edge("app_service", "s3_buckets", "upload/download", EdgeType.DATA_FLOW),
        _edge("app_service", "rabbitmq", "publish", EdgeType.ASYNC_MESSAGE, async_=True),
        _edge("rabbitmq", "notification_worker", "consume", EdgeType.ASYNC_MESSAGE, async_=True),
        _edge("auth_service", "postgresql", "user data", EdgeType.PERSISTENCE),
        _edge("app_service", "prometheus_+_grafana", "metrics", EdgeType.DATA_FLOW, async_=True),
    ],
)

# ── 2. Realtime Systems ───────────────────────────────────────────────────────

REALTIME_PATTERN = TopologyPattern(
    system_type=SystemType.REALTIME,
    name="Realtime System",
    description="WebSocket-based realtime platform with presence, pub/sub, and horizontal scaling.",
    node_templates=[
        _node("Web Client", NodeType.CLIENT, LayerType.CLIENT, technology="React"),
        _node("Mobile Client", NodeType.CLIENT, LayerType.CLIENT, technology="React Native"),
        _node("CDN", NodeType.EDGE, LayerType.EDGE, technology="Cloudflare"),
        _node("Load Balancer", NodeType.GATEKEEPER, LayerType.EDGE, technology="NGINX / HAProxy", metadata={"sticky": "true"}),
        _node("WebSocket Server", NodeType.SERVICE, LayerType.SERVICE, technology="Socket.io / ws", scaling="horizontal", is_stateful=False),
        _node("Presence Service", NodeType.SERVICE, LayerType.SERVICE, technology="Node / Go", scaling="horizontal"),
        _node("API Service", NodeType.SERVICE, LayerType.SERVICE, technology="FastAPI", scaling="horizontal"),
        _node("Redis Pub/Sub", NodeType.STREAM, LayerType.ASYNC, technology="Redis PubSub"),
        _node("Kafka", NodeType.EVENT_BUS, LayerType.ASYNC, technology="Apache Kafka"),
        _node("PostgreSQL", NodeType.DATABASE, LayerType.DATA, technology="PostgreSQL", is_stateful=True),
        _node("Redis Cache", NodeType.CACHE, LayerType.DATA, technology="Redis"),
        _node("Prometheus + Grafana", NodeType.OBSERVABILITY, LayerType.OBSERVABILITY),
    ],
    edge_templates=[
        _edge("web_client", "cdn", "static assets", EdgeType.SYNC_HTTP),
        _edge("web_client", "load_balancer", "WS connect", EdgeType.SYNC_HTTP),
        _edge("mobile_client", "load_balancer", "WS connect", EdgeType.SYNC_HTTP),
        _edge("load_balancer", "websocket_server", "sticky session", EdgeType.DELEGATION),
        _edge("websocket_server", "redis_pub/sub", "broadcast", EdgeType.ASYNC_EVENT, async_=True),
        _edge("websocket_server", "presence_service", "heartbeat", EdgeType.SYNC_RPC),
        _edge("presence_service", "redis_cache", "presence state", EdgeType.DATA_FLOW),
        _edge("api_service", "postgresql", "CRUD", EdgeType.PERSISTENCE),
        _edge("api_service", "redis_cache", "cache", EdgeType.CACHE_LOOKUP),
        _edge("kafka", "api_service", "event consume", EdgeType.ASYNC_EVENT, async_=True),
        _edge("websocket_server", "prometheus_+_grafana", "metrics", EdgeType.DATA_FLOW, async_=True),
    ],
)

# ── 3. AI SaaS ──────────────────────────────────────────────────────────────

AI_SAAS_PATTERN = TopologyPattern(
    system_type=SystemType.AI_SAAS,
    name="AI SaaS",
    description="AI-powered SaaS with inference API, async jobs, and model versioning.",
    node_templates=[
        _node("Web UI", NodeType.CLIENT, LayerType.CLIENT, technology="Next.js"),
        _node("API Gateway", NodeType.GATEKEEPER, LayerType.EDGE, technology="Kong"),
        _node("Billing Middleware", NodeType.SERVICE, LayerType.EDGE, technology="Stripe Webhooks"),
        _node("User Service", NodeType.SERVICE, LayerType.SERVICE, technology="FastAPI", scaling="horizontal"),
        _node("Inference Service", NodeType.SERVICE, LayerType.SERVICE, technology="FastAPI / Triton", scaling="horizontal"),
        _node("Model Registry", NodeType.SERVICE, LayerType.SERVICE, technology="MLflow", scaling="vertical"),
        _node("Job Worker", NodeType.WORKER, LayerType.SERVICE, technology="Celery", scaling="horizontal"),
        _node("Celery Queue", NodeType.QUEUE, LayerType.ASYNC, technology="Redis / RabbitMQ"),
        _node("PostgreSQL", NodeType.DATABASE, LayerType.DATA, technology="PostgreSQL", is_stateful=True),
        _node("Model Artifact Store", NodeType.STORAGE, LayerType.DATA, technology="S3 / GCS"),
        _node("OpenAI / Claude", NodeType.EXTERNAL, LayerType.AI, technology="OpenAI API"),
        _node("Self-hosted LLM", NodeType.AI_MODEL, LayerType.AI, technology="vLLM / TGI", scaling="horizontal"),
        _node("Prometheus + Grafana", NodeType.OBSERVABILITY, LayerType.OBSERVABILITY),
    ],
    edge_templates=[
        _edge("web_ui", "api_gateway", "HTTPS", EdgeType.SYNC_HTTP),
        _edge("api_gateway", "billing_middleware", "rate limit", EdgeType.AUTH),
        _edge("api_gateway", "user_service", "proxy", EdgeType.DELEGATION),
        _edge("api_gateway", "inference_service", "proxy", EdgeType.DELEGATION),
        _edge("inference_service", "self-hosted_llm", "inference", EdgeType.INFERENCE),
        _edge("inference_service", "openai_/_claude", "fallback inference", EdgeType.INFERENCE),
        _edge("inference_service", "model_registry", "fetch model", EdgeType.DATA_FLOW),
        _edge("inference_service", "celery_queue", "enqueue job", EdgeType.ASYNC_MESSAGE, async_=True),
        _edge("celery_queue", "job_worker", "consume", EdgeType.ASYNC_MESSAGE, async_=True),
        _edge("job_worker", "model_artifact_store", "artifact", EdgeType.DATA_FLOW),
        _edge("user_service", "postgresql", "user data", EdgeType.PERSISTENCE),
        _edge("inference_service", "postgresql", "job state", EdgeType.PERSISTENCE),
        _edge("model_registry", "model_artifact_store", "versioned blobs", EdgeType.DATA_FLOW),
        _edge("inference_service", "prometheus_+_grafana", "metrics", EdgeType.DATA_FLOW, async_=True),
    ],
)

# ── 4. RAG Platform ─────────────────────────────────────────────────────────

RAG_PLATFORM_PATTERN = TopologyPattern(
    system_type=SystemType.RAG_PLATFORM,
    name="RAG Platform",
    description="Retrieval-Augmented Generation with embedding pipeline, vector DB, and retriever context builder.",
    node_templates=[
        _node("Web App", NodeType.CLIENT, LayerType.CLIENT, technology="React"),
        _node("API Gateway", NodeType.GATEKEEPER, LayerType.EDGE, technology="Kong"),
        _node("Upload Service", NodeType.SERVICE, LayerType.SERVICE, technology="FastAPI", scaling="horizontal"),
        _node("Query Service", NodeType.SERVICE, LayerType.SERVICE, technology="FastAPI", scaling="horizontal"),
        _node("Embedding Worker", NodeType.WORKER, LayerType.SERVICE, technology="Celery", scaling="horizontal"),
        _node("Context Builder", NodeType.RETRIEVER, LayerType.SERVICE, technology="Python", scaling="horizontal"),
        _node("Chunking Service", NodeType.SERVICE, LayerType.SERVICE, technology="Python", scaling="horizontal"),
        _node("Task Queue", NodeType.QUEUE, LayerType.ASYNC, technology="RabbitMQ"),
        _node("PostgreSQL", NodeType.DATABASE, LayerType.DATA, technology="PostgreSQL", is_stateful=True),
        _node("Pinecone / Weaviate", NodeType.VECTOR_DB, LayerType.DATA, technology="Pinecone"),
        _node("S3", NodeType.STORAGE, LayerType.DATA, technology="AWS S3"),
        _node("OpenAI Embeddings", NodeType.EMBEDDING, LayerType.AI, technology="OpenAI text-embedding-3"),
        _node("LLM", NodeType.AI_MODEL, LayerType.AI, technology="GPT-4 / Claude"),
        _node("Prometheus + Grafana", NodeType.OBSERVABILITY, LayerType.OBSERVABILITY),
    ],
    edge_templates=[
        _edge("web_app", "api_gateway", "HTTPS", EdgeType.SYNC_HTTP),
        _edge("api_gateway", "upload_service", "proxy", EdgeType.DELEGATION),
        _edge("api_gateway", "query_service", "proxy", EdgeType.DELEGATION),
        _edge("upload_service", "s3", "store file", EdgeType.DATA_FLOW),
        _edge("upload_service", "task_queue", "enqueue", EdgeType.ASYNC_MESSAGE, async_=True),
        _edge("task_queue", "chunking_service", "consume", EdgeType.ASYNC_MESSAGE, async_=True),
        _edge("chunking_service", "embedding_worker", "chunks", EdgeType.DATA_FLOW),
        _edge("embedding_worker", "openai_embeddings", "embed", EdgeType.EMBEDDING_FLOW),
        _edge("openai_embeddings", "pinecone_/_weaviate", "upsert vectors", EdgeType.EMBEDDING_FLOW),
        _edge("pinecone_/_weaviate", "context_builder", "search", EdgeType.DATA_FLOW),
        _edge("query_service", "context_builder", "query", EdgeType.SYNC_RPC),
        _edge("context_builder", "llm", "prompt + context", EdgeType.INFERENCE),
        _edge("query_service", "postgresql", "conversation history", EdgeType.PERSISTENCE),
        _edge("upload_service", "prometheus_+_grafana", "metrics", EdgeType.DATA_FLOW, async_=True),
    ],
)

# ── 5. Agentic AI ───────────────────────────────────────────────────────────

AGENTIC_AI_PATTERN = TopologyPattern(
    system_type=SystemType.AGENTIC_AI,
    name="Agentic AI System",
    description="Planner / executor loop with memory, tool registry, and feedback cycles.",
    node_templates=[
        _node("Chat UI", NodeType.CLIENT, LayerType.CLIENT, technology="Next.js"),
        _node("API Gateway", NodeType.GATEKEEPER, LayerType.EDGE, technology="Kong"),
        _node("Session Manager", NodeType.SERVICE, LayerType.SERVICE, technology="FastAPI", scaling="horizontal"),
        _node("Planner", NodeType.ORCHESTRATOR, LayerType.SERVICE, technology="Python / LangGraph", scaling="horizontal"),
        _node("Executor", NodeType.SERVICE, LayerType.SERVICE, technology="Python", scaling="horizontal"),
        _node("Tool Registry", NodeType.SERVICE, LayerType.SERVICE, technology="FastAPI"),
        _node("Task Queue", NodeType.QUEUE, LayerType.ASYNC, technology="RabbitMQ"),
        _node("PostgreSQL", NodeType.DATABASE, LayerType.DATA, technology="PostgreSQL", is_stateful=True),
        _node("Memory Store", NodeType.CACHE, LayerType.DATA, technology="Redis", is_stateful=False, metadata={"type": "short_term_memory"}),
        _node("Vector Memory", NodeType.VECTOR_DB, LayerType.DATA, technology="Pinecone", metadata={"type": "long_term_memory"}),
        _node("LLM", NodeType.AI_MODEL, LayerType.AI, technology="GPT-4 / Claude"),
        _node("Code Interpreter", NodeType.EXTERNAL, LayerType.AI, technology="E2B / Sandbox"),
        _node("Prometheus + Grafana", NodeType.OBSERVABILITY, LayerType.OBSERVABILITY),
    ],
    edge_templates=[
        _edge("chat_ui", "api_gateway", "HTTPS", EdgeType.SYNC_HTTP),
        _edge("api_gateway", "session_manager", "proxy", EdgeType.DELEGATION),
        _edge("session_manager", "planner", "user intent", EdgeType.SYNC_RPC),
        _edge("planner", "llm", "plan generation", EdgeType.INFERENCE),
        _edge("planner", "executor", "dispatch tasks", EdgeType.CONTROL_FLOW),
        _edge("executor", "tool_registry", "discover tools", EdgeType.SYNC_RPC),
        _edge("executor", "code_interpreter", "run code", EdgeType.DATA_FLOW),
        _edge("executor", "memory_store", "read/write state", EdgeType.DATA_FLOW),
        _edge("executor", "vector_memory", "recall", EdgeType.DATA_FLOW),
        _edge("executor", "planner", "results feedback", EdgeType.CONTROL_FLOW),
        _edge("executor", "task_queue", "enqueue", EdgeType.ASYNC_MESSAGE, async_=True),
        _edge("task_queue", "executor", "retry", EdgeType.ASYNC_MESSAGE, async_=True),
        _edge("planner", "postgresql", "persist plan", EdgeType.PERSISTENCE),
        _edge("session_manager", "prometheus_+_grafana", "metrics", EdgeType.DATA_FLOW, async_=True),
    ],
)

# ── 6. Video Streaming ────────────────────────────────────────────────────────

VIDEO_STREAMING_PATTERN = TopologyPattern(
    system_type=SystemType.VIDEO_STREAMING,
    name="Video Streaming Platform",
    description="Adaptive bitrate streaming with CDN, transcoding workers, and manifest serving.",
    node_templates=[
        _node("Web Player", NodeType.CLIENT, LayerType.CLIENT, technology="HLS.js / DASH"),
        _node("Mobile Player", NodeType.CLIENT, LayerType.CLIENT, technology="ExoPlayer / AVPlayer"),
        _node("CDN", NodeType.EDGE, LayerType.EDGE, technology="Akamai / CloudFront"),
        _node("API Gateway", NodeType.GATEKEEPER, LayerType.EDGE, technology="AWS API Gateway"),
        _node("Manifest Service", NodeType.SERVICE, LayerType.SERVICE, technology="Go / Node", scaling="horizontal"),
        _node("Upload Service", NodeType.SERVICE, LayerType.SERVICE, technology="FastAPI", scaling="horizontal"),
        _node("Transcode Worker", NodeType.WORKER, LayerType.SERVICE, technology="FFmpeg / Elemental", scaling="horizontal"),
        _node("Transcode Queue", NodeType.QUEUE, LayerType.ASYNC, technology="SQS / RabbitMQ"),
        _node("PostgreSQL", NodeType.DATABASE, LayerType.DATA, technology="PostgreSQL", is_stateful=True),
        _node("Media Store", NodeType.STORAGE, LayerType.DATA, technology="S3"),
        _node("Prometheus + Grafana", NodeType.OBSERVABILITY, LayerType.OBSERVABILITY),
    ],
    edge_templates=[
        _edge("web_player", "cdn", "HLS manifest + segments", EdgeType.DATA_FLOW),
        _edge("mobile_player", "cdn", "HLS manifest + segments", EdgeType.DATA_FLOW),
        _edge("web_player", "api_gateway", "auth + analytics", EdgeType.SYNC_HTTP),
        _edge("api_gateway", "manifest_service", "proxy", EdgeType.DELEGATION),
        _edge("manifest_service", "cdn", "invalidate", EdgeType.DATA_FLOW),
        _edge("manifest_service", "postgresql", "video metadata", EdgeType.PERSISTENCE),
        _edge("upload_service", "media_store", "raw upload", EdgeType.DATA_FLOW),
        _edge("upload_service", "transcode_queue", "enqueue", EdgeType.ASYNC_MESSAGE, async_=True),
        _edge("transcode_queue", "transcode_worker", "consume", EdgeType.ASYNC_MESSAGE, async_=True),
        _edge("transcode_worker", "media_store", "write variants", EdgeType.DATA_FLOW),
        _edge("transcode_worker", "postgresql", "update status", EdgeType.PERSISTENCE),
        _edge("manifest_service", "prometheus_+_grafana", "metrics", EdgeType.DATA_FLOW, async_=True),
    ],
)

# ── 7. Event-Driven Ecommerce ───────────────────────────────────────────────

EVENT_DRIVEN_ECOMMERCE_PATTERN = TopologyPattern(
    system_type=SystemType.EVENT_DRIVEN_ECOMMERCE,
    name="Event-Driven Ecommerce",
    description="Saga-pattern ecommerce with order, inventory, payment services and event bus.",
    node_templates=[
        _node("Web Store", NodeType.CLIENT, LayerType.CLIENT, technology="Next.js"),
        _node("Mobile App", NodeType.CLIENT, LayerType.CLIENT, technology="React Native"),
        _node("CDN", NodeType.EDGE, LayerType.EDGE, technology="Cloudflare"),
        _node("API Gateway", NodeType.GATEKEEPER, LayerType.EDGE, technology="Kong"),
        _node("Order Service", NodeType.SERVICE, LayerType.SERVICE, technology="FastAPI", scaling="horizontal"),
        _node("Inventory Service", NodeType.SERVICE, LayerType.SERVICE, technology="FastAPI", scaling="horizontal"),
        _node("Payment Service", NodeType.SERVICE, LayerType.SERVICE, technology="FastAPI", scaling="horizontal"),
        _node("Shipping Worker", NodeType.WORKER, LayerType.SERVICE, technology="Celery", scaling="horizontal"),
        _node("Notification Worker", NodeType.WORKER, LayerType.SERVICE, technology="Celery", scaling="horizontal"),
        _node("Kafka", NodeType.EVENT_BUS, LayerType.ASYNC, technology="Apache Kafka"),
        _node("Order DB", NodeType.DATABASE, LayerType.DATA, technology="PostgreSQL", is_stateful=True),
        _node("Inventory DB", NodeType.DATABASE, LayerType.DATA, technology="PostgreSQL", is_stateful=True),
        _node("Payment DB", NodeType.DATABASE, LayerType.DATA, technology="PostgreSQL", is_stateful=True),
        _node("Redis Cache", NodeType.CACHE, LayerType.DATA, technology="Redis"),
        _node("Stripe", NodeType.EXTERNAL, LayerType.EDGE, technology="Stripe API"),
        _node("Prometheus + Grafana", NodeType.OBSERVABILITY, LayerType.OBSERVABILITY),
    ],
    edge_templates=[
        _edge("web_store", "cdn", "static", EdgeType.SYNC_HTTP),
        _edge("web_store", "api_gateway", "HTTPS", EdgeType.SYNC_HTTP),
        _edge("mobile_app", "api_gateway", "HTTPS", EdgeType.SYNC_HTTP),
        _edge("api_gateway", "order_service", "proxy", EdgeType.DELEGATION),
        _edge("order_service", "kafka", "OrderCreated", EdgeType.ASYNC_EVENT, async_=True),
        _edge("order_service", "order_db", "write", EdgeType.PERSISTENCE),
        _edge("kafka", "inventory_service", "OrderCreated", EdgeType.ASYNC_EVENT, async_=True),
        _edge("kafka", "payment_service", "OrderCreated", EdgeType.ASYNC_EVENT, async_=True),
        _edge("inventory_service", "inventory_db", "reserve", EdgeType.PERSISTENCE),
        _edge("inventory_service", "kafka", "InventoryReserved / Failed", EdgeType.ASYNC_EVENT, async_=True),
        _edge("payment_service", "stripe", "charge", EdgeType.SYNC_HTTP),
        _edge("payment_service", "payment_db", "record", EdgeType.PERSISTENCE),
        _edge("payment_service", "kafka", "PaymentConfirmed / Failed", EdgeType.ASYNC_EVENT, async_=True),
        _edge("kafka", "shipping_worker", "PaymentConfirmed", EdgeType.ASYNC_EVENT, async_=True),
        _edge("kafka", "notification_worker", "events", EdgeType.ASYNC_EVENT, async_=True),
        _edge("order_service", "redis_cache", "cache", EdgeType.CACHE_LOOKUP),
        _edge("order_service", "prometheus_+_grafana", "metrics", EdgeType.DATA_FLOW, async_=True),
    ],
)

# ── 8. Kubernetes-Native Infra ──────────────────────────────────────────────

KUBERNETES_INFRA_PATTERN = TopologyPattern(
    system_type=SystemType.KUBERNETES_INFRA,
    name="Kubernetes-Native Infrastructure",
    description="Cloud-native platform with ingress, service mesh, operators, and GitOps.",
    node_templates=[
        _node("Developer", NodeType.CLIENT, LayerType.CLIENT, technology="CLI / IDE"),
        _node("Git Repo", NodeType.EXTERNAL, LayerType.CLIENT, technology="GitHub"),
        _node("ArgoCD", NodeType.SERVICE, LayerType.EDGE, technology="ArgoCD"),
        _node("Ingress Controller", NodeType.GATEKEEPER, LayerType.EDGE, technology="NGINX Ingress"),
        _node("Cert Manager", NodeType.GATEKEEPER, LayerType.EDGE, technology="cert-manager"),
        _node("API Service", NodeType.SERVICE, LayerType.SERVICE, technology="FastAPI", scaling="horizontal"),
        _node("Worker Service", NodeType.WORKER, LayerType.SERVICE, technology="Celery", scaling="horizontal"),
        _node("Service Mesh Proxy", NodeType.EDGE, LayerType.SERVICE, technology="Istio Envoy", metadata={"sidecar": "true"}),
        _node("Kafka", NodeType.EVENT_BUS, LayerType.ASYNC, technology="Strimzi / Kafka"),
        _node("PostgreSQL", NodeType.DATABASE, LayerType.DATA, technology="CloudNativePG", is_stateful=True),
        _node("Redis", NodeType.CACHE, LayerType.DATA, technology="Redis Cluster"),
        _node("S3", NodeType.STORAGE, LayerType.DATA, technology="MinIO / S3"),
        _node("Prometheus + Grafana", NodeType.OBSERVABILITY, LayerType.OBSERVABILITY),
        _node("Loki", NodeType.OBSERVABILITY, LayerType.OBSERVABILITY, technology="Grafana Loki"),
        _node("Jaeger", NodeType.OBSERVABILITY, LayerType.OBSERVABILITY, technology="Jaeger"),
        _node("Kubernetes Control Plane", NodeType.INFRA, LayerType.INFRA, technology="Kubernetes"),
    ],
    edge_templates=[
        _edge("developer", "git_repo", "push", EdgeType.DATA_FLOW),
        _edge("git_repo", "argocd", "webhook", EdgeType.ASYNC_EVENT, async_=True),
        _edge("argocd", "kubernetes_control_plane", "apply manifests", EdgeType.CONTROL_FLOW),
        _edge("ingress_controller", "api_service", "route", EdgeType.DELEGATION),
        _edge("ingress_controller", "cert_manager", "TLS", EdgeType.AUTH),
        _edge("api_service", "service_mesh_proxy", "mTLS", EdgeType.AUTH),
        _edge("worker_service", "service_mesh_proxy", "mTLS", EdgeType.AUTH),
        _edge("api_service", "kafka", "publish", EdgeType.ASYNC_EVENT, async_=True),
        _edge("kafka", "worker_service", "consume", EdgeType.ASYNC_EVENT, async_=True),
        _edge("api_service", "postgresql", "CRUD", EdgeType.PERSISTENCE),
        _edge("api_service", "redis", "cache", EdgeType.CACHE_LOOKUP),
        _edge("worker_service", "s3", "blobs", EdgeType.DATA_FLOW),
        _edge("api_service", "prometheus_+_grafana", "metrics", EdgeType.DATA_FLOW, async_=True),
        _edge("api_service", "jaeger", "traces", EdgeType.DATA_FLOW, async_=True),
        _edge("api_service", "loki", "logs", EdgeType.DATA_FLOW, async_=True),
    ],
)

# ── 9. Multi-Region Distributed ───────────────────────────────────────────────

MULTI_REGION_PATTERN = TopologyPattern(
    system_type=SystemType.MULTI_REGION,
    name="Multi-Region Distributed System",
    description="Globally distributed system with regional failover, replication, and conflict resolution.",
    node_templates=[
        _node("Global DNS", NodeType.EDGE, LayerType.EDGE, technology="Route53 / Cloudflare"),
        _node("WAF", NodeType.GATEKEEPER, LayerType.EDGE, technology="AWS WAF / Cloudflare"),
        _node("US-East LB", NodeType.GATEKEEPER, LayerType.EDGE, technology="AWS ALB", metadata={"region": "us-east-1"}),
        _node("EU-West LB", NodeType.GATEKEEPER, LayerType.EDGE, technology="AWS ALB", metadata={"region": "eu-west-1"}),
        _node("US-East API", NodeType.SERVICE, LayerType.SERVICE, technology="FastAPI", scaling="horizontal", metadata={"region": "us-east-1"}),
        _node("EU-West API", NodeType.SERVICE, LayerType.SERVICE, technology="FastAPI", scaling="horizontal", metadata={"region": "eu-west-1"}),
        _node("Replication Worker", NodeType.WORKER, LayerType.SERVICE, technology="Debezium / Custom", scaling="horizontal"),
        _node("Kafka", NodeType.EVENT_BUS, LayerType.ASYNC, technology="MSK / Confluent"),
        _node("US-East DB", NodeType.DATABASE, LayerType.DATA, technology="PostgreSQL", is_stateful=True, metadata={"region": "us-east-1", "role": "primary"}),
        _node("EU-West DB", NodeType.DATABASE, LayerType.DATA, technology="PostgreSQL", is_stateful=True, metadata={"region": "eu-west-1", "role": "replica"}),
        _node("Global Cache", NodeType.CACHE, LayerType.DATA, technology="Redis Cluster"),
        _node("S3", NodeType.STORAGE, LayerType.DATA, technology="S3 Cross-Region Replication"),
        _node("Prometheus + Grafana", NodeType.OBSERVABILITY, LayerType.OBSERVABILITY),
    ],
    edge_templates=[
        _edge("global_dns", "waf", "georoute", EdgeType.SYNC_HTTP),
        _edge("waf", "us-east_lb", "route", EdgeType.SYNC_HTTP),
        _edge("waf", "eu-west_lb", "route", EdgeType.SYNC_HTTP),
        _edge("us-east_lb", "us-east_api", "proxy", EdgeType.DELEGATION),
        _edge("eu-west_lb", "eu-west_api", "proxy", EdgeType.DELEGATION),
        _edge("us-east_api", "us-east_db", "read/write", EdgeType.PERSISTENCE),
        _edge("eu-west_api", "eu-west_db", "read", EdgeType.PERSISTENCE),
        _edge("us-east_db", "replication_worker", "CDC", EdgeType.DATA_FLOW, async_=True),
        _edge("replication_worker", "eu-west_db", "replicate", EdgeType.DATA_FLOW, async_=True),
        _edge("us-east_api", "global_cache", "cache", EdgeType.CACHE_LOOKUP),
        _edge("eu-west_api", "global_cache", "cache", EdgeType.CACHE_LOOKUP),
        _edge("us-east_api", "kafka", "events", EdgeType.ASYNC_EVENT, async_=True),
        _edge("kafka", "eu-west_api", "consume", EdgeType.ASYNC_EVENT, async_=True),
        _edge("us-east_api", "s3", "store", EdgeType.DATA_FLOW),
        _edge("us-east_api", "prometheus_+_grafana", "metrics", EdgeType.DATA_FLOW, async_=True),
    ],
)

# ── Pattern Registry ──────────────────────────────────────────────────────────

PATTERN_REGISTRY: dict[SystemType, TopologyPattern] = {
    SystemType.CRUD_SAAS: CRUD_SAAS_PATTERN,
    SystemType.REALTIME: REALTIME_PATTERN,
    SystemType.AI_SAAS: AI_SAAS_PATTERN,
    SystemType.RAG_PLATFORM: RAG_PLATFORM_PATTERN,
    SystemType.AGENTIC_AI: AGENTIC_AI_PATTERN,
    SystemType.VIDEO_STREAMING: VIDEO_STREAMING_PATTERN,
    SystemType.EVENT_DRIVEN_ECOMMERCE: EVENT_DRIVEN_ECOMMERCE_PATTERN,
    SystemType.KUBERNETES_INFRA: KUBERNETES_INFRA_PATTERN,
    SystemType.MULTI_REGION: MULTI_REGION_PATTERN,
}


def get_pattern(system_type: SystemType) -> TopologyPattern | None:
    return PATTERN_REGISTRY.get(system_type)
