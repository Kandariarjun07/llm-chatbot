import os
from functools import lru_cache
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        return False

try:
    from pydantic import BaseModel, Field
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False

    class BaseModel:
        def __init__(self, **data):
            for key, value in data.items():
                setattr(self, key, value)

    def Field(default=None, **kwargs):
        return default


load_dotenv()


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


class AppSettings(BaseModel):
    groq_api_key: str | None = Field(default=None)
    gemini_api_key: str | None = Field(default=None)
    together_api_key: str | None = Field(default=None)
    deepgram_api_key: str | None = Field(default=None)
    aicredits_api_key: str | None = Field(default=None)
    cerebras_api_key: str | None = Field(default=None)
    cerebras_model: str = Field(default="gpt-oss-120b")
    aicredits_base_url: str = Field(default="https://api.aicredits.in/v1")
    aicredits_model: str = Field(default="google/gemma-4-26b-a4b-it")
    aicredits_inr_limit: float = Field(default=5.0)
    aicredits_inr_per_1k_input_tokens: float = Field(default=0.005)
    aicredits_inr_per_1k_output_tokens: float = Field(default=0.020)
    llm_provider: str = Field(default="vertex_gemini")
    vertex_ai_project_id: str | None = Field(default=None)
    vertex_ai_location: str = Field(default="us-central1")
    vertex_ai_gemini_model: str = Field(default="gemini-2.5-flash")
    gemini_api_model: str = Field(default="gemini-2.5-flash")
    groq_llama_model: str = Field(default="llama-3.1-8b-instant")
    groq_think_model: str = Field(default="openai/gpt-oss-120b")
    groq_compound_model: str = Field(default="openai/gpt-oss-safeguard-20b")
    cloudflare_account_id: str | None = Field(default=None)
    cloudflare_auth_token: str | None = Field(default=None)
    cloudflare_model: str = Field(default="@cf/moonshotai/kimi-k2.6")
    together_model: str = Field(default="mistralai/Mistral-Small-24B-Instruct-2501")
    auth_provider: str = Field(default="firebase")
    firebase_web_api_key: str | None = Field(default=None)
    firebase_project_id: str | None = Field(default=None)
    firebase_storage_bucket: str | None = Field(default=None)
    app_storage_backend: str = Field(default="firebase")
    appwrite_endpoint: str = Field(default="https://cloud.appwrite.io/v1")
    appwrite_project_id: str | None = Field(default=None)
    appwrite_api_key: str | None = Field(default=None)
    appwrite_storage_bucket_id: str | None = Field(default=None)
    appwrite_file_permissions: str | None = Field(default=None)
    oidc_provider_name: str = Field(default="Enterprise SSO")
    oidc_discovery_url: str | None = Field(default=None)
    oidc_client_id: str | None = Field(default=None)
    oidc_client_secret: str | None = Field(default=None)
    oidc_redirect_uri: str | None = Field(default=None)
    oidc_scopes: str = Field(default="openid profile email")
    oidc_allowed_domains: str | None = Field(default=None)
    oidc_allowed_emails: str | None = Field(default=None)

    # ── Supabase / PostgreSQL ────────────────────────────────────
    supabase_db_url: str | None = Field(default=None)

    # ── SMTP (OTP email delivery) ────────────────────────────────
    smtp_host: str | None = Field(default=None)
    smtp_port: int = Field(default=587)
    smtp_user: str | None = Field(default=None)
    smtp_password: str | None = Field(default=None)
    smtp_from: str | None = Field(default=None)
    smtp_tls: bool = Field(default=True)
    smtp_ssl: bool = Field(default=False)

    gcp_project_id: str | None = Field(default=None)
    gcp_location: str = Field(default="US")

    cache_enabled: bool = Field(default=True)
    cache_ttl_seconds: int = Field(default=3600)
    cache_namespace: str = Field(default="snti-ai")
    top_query_tracking_enabled: bool = Field(default=True)
    redis_url: str | None = Field(default=None)
    redis_host: str | None = Field(default=None)
    redis_port: int = Field(default=6379)
    redis_db: int = Field(default=0)
    redis_password: str | None = Field(default=None)
    redis_ssl: bool = Field(default=False)

    telemetry_enabled: bool = Field(default=True)
    cloud_logging_enabled: bool = Field(default=True)
    bigquery_telemetry_enabled: bool = Field(default=False)
    telemetry_file_enabled: bool = Field(default=True)
    telemetry_file_path: str = Field(default="logs/chat_telemetry.jsonl")
    bigquery_telemetry_dataset: str = Field(default="analytics")
    bigquery_telemetry_table: str = Field(default="chat_telemetry")
    telemetry_batch_enabled: bool = Field(default=True)
    telemetry_batch_size: int = Field(default=10)
    telemetry_flush_interval_seconds: int = Field(default=30)
    log_level: str = Field(default="INFO")

    gcs_staging_bucket: str | None = Field(default=None)
    bigquery_raw_dataset: str = Field(default="raw")
    bigquery_context_dataset: str = Field(default="analytics")
    bigquery_context_table: str = Field(default="chat_context_docs")
    rag_use_bigquery: bool = Field(default=False)
    rag_use_embeddings: bool = Field(default=False)
    rag_embedding_model: str = Field(default="gemini-embedding-001")
    rag_vector_index_path: str = Field(default=".rag_index/context_vectors.json")
    data_access_control_enabled: bool = Field(default=True)
    data_access_rules: str | None = Field(default=None)
    data_access_default_sources: str | None = Field(default=None)
    max_input_tokens: int = Field(default=6000)
    max_context_tokens: int = Field(default=2500)
    max_output_tokens: int = Field(default=4096, ge=256, le=8192)
    model_auto_routing_enabled: bool = Field(default=True)
    cheap_model_choice: str = Field(default="Llama")
    premium_model_choice: str = Field(default="Gemini")
    low_risk_token_threshold: int = Field(default=500)
    language_detection_enabled: bool = Field(default=True)
    translation_enabled: bool = Field(default=False)
    translation_target_language: str = Field(default="English")

    secret_manager_enabled: bool = Field(default=False)
    groq_api_key_secret: str = Field(default="groq-api-key")
    gemini_api_key_secret: str = Field(default="gemini-api-key")
    pii_redaction_enabled: bool = Field(default=True)
    prompt_validation_enabled: bool = Field(default=True)
    forbidden_topic_patterns: str | None = Field(default=None)
    output_moderation_enabled: bool = Field(default=True)
    output_moderation_patterns: str | None = Field(default=None)
    reference_checking_enabled: bool = Field(default=True)
    audit_prompt_preview_enabled: bool = Field(default=False)

    @classmethod
    def from_env(cls) -> "AppSettings":
        return cls(
            groq_api_key=os.getenv("GROQ_API_KEY") or None,
            gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
            together_api_key=os.getenv("TOGETHER_API_KEY") or None,
            deepgram_api_key=os.getenv("DEEPGRAM_API_KEY") or None,
            aicredits_api_key=os.getenv("AICREDITS_API_KEY") or None,
            cerebras_api_key=os.getenv("CEREBRAS_API_KEY") or None,
            cerebras_model=os.getenv("CEREBRAS_MODEL", "gpt-oss-120b"),
            aicredits_base_url=os.getenv("AICREDITS_BASE_URL", "https://api.aicredits.in/v1"),
            aicredits_model=os.getenv("AICREDITS_MODEL", "google/gemma-4-26b-a4b-it"),
            cloudflare_account_id=os.getenv("CLOUDFLARE_ACCOUNT_ID") or None,
            cloudflare_auth_token=os.getenv("CLOUDFLARE_AUTH_TOKEN") or None,
            cloudflare_model=os.getenv("CLOUDFLARE_MODEL", "@cf/moonshotai/kimi-k2.6"),
            aicredits_inr_limit=float(os.getenv("AICREDITS_INR_LIMIT", "5.0")),
            aicredits_inr_per_1k_input_tokens=float(os.getenv("AICREDITS_INR_PER_1K_INPUT", "0.005")),
            aicredits_inr_per_1k_output_tokens=float(os.getenv("AICREDITS_INR_PER_1K_OUTPUT", "0.020")),
            llm_provider=os.getenv("LLM_PROVIDER", "vertex_gemini"),
            vertex_ai_project_id=(
                os.getenv("VERTEX_AI_PROJECT_ID")
                or os.getenv("GCP_PROJECT_ID")
                or os.getenv("GOOGLE_CLOUD_PROJECT")
                or None
            ),
            vertex_ai_location=os.getenv("VERTEX_AI_LOCATION", "us-central1"),
            vertex_ai_gemini_model=os.getenv("VERTEX_AI_GEMINI_MODEL", "gemini-2.5-flash"),
            gemini_api_model=os.getenv("GEMINI_API_MODEL", "gemini-2.5-flash"),
            groq_llama_model=os.getenv("GROQ_LLAMA_MODEL", "llama-3.1-8b-instant"),
            groq_think_model=os.getenv("GROQ_THINK_MODEL", "openai/gpt-oss-120b"),
            groq_compound_model=os.getenv("GROQ_COMPOUND_MODEL", "openai/gpt-oss-safeguard-20b"),
            together_model=os.getenv("TOGETHER_MODEL", "mistralai/Mistral-Small-24B-Instruct-2501"),
            auth_provider=os.getenv("AUTH_PROVIDER", "firebase"),
            firebase_web_api_key=os.getenv("FIREBASE_WEB_API_KEY") or None,
            firebase_project_id=os.getenv("FIREBASE_PROJECT_ID") or None,
            firebase_storage_bucket=os.getenv("FIREBASE_STORAGE_BUCKET") or None,
            app_storage_backend=os.getenv("APP_STORAGE_BACKEND", "firebase"),
            appwrite_endpoint=os.getenv("APPWRITE_ENDPOINT", "https://cloud.appwrite.io/v1"),
            appwrite_project_id=os.getenv("APPWRITE_PROJECT_ID") or None,
            appwrite_api_key=os.getenv("APPWRITE_API_KEY") or None,
            appwrite_storage_bucket_id=os.getenv("APPWRITE_STORAGE_BUCKET_ID") or None,
            appwrite_file_permissions=os.getenv("APPWRITE_FILE_PERMISSIONS") or None,
            oidc_provider_name=os.getenv("OIDC_PROVIDER_NAME", "Enterprise SSO"),
            oidc_discovery_url=os.getenv("OIDC_DISCOVERY_URL") or None,
            oidc_client_id=os.getenv("OIDC_CLIENT_ID") or None,
            oidc_client_secret=os.getenv("OIDC_CLIENT_SECRET") or None,
            oidc_redirect_uri=os.getenv("OIDC_REDIRECT_URI") or os.getenv("APP_BASE_URL") or None,
            oidc_scopes=os.getenv("OIDC_SCOPES", "openid profile email"),
            oidc_allowed_domains=os.getenv("OIDC_ALLOWED_DOMAINS") or None,
            oidc_allowed_emails=os.getenv("OIDC_ALLOWED_EMAILS") or None,
            supabase_db_url=os.getenv("SUPABASE_DB_URL") or None,
            smtp_host=os.getenv("SMTP_HOST") or None,
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_user=os.getenv("SMTP_USER") or None,
            smtp_password=os.getenv("SMTP_PASSWORD") or None,
            smtp_from=os.getenv("SMTP_FROM") or None,
            smtp_tls=_env_bool("SMTP_TLS", "true"),
            smtp_ssl=_env_bool("SMTP_SSL", "false"),
            gcp_project_id=os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or None,
            gcp_location=os.getenv("GCP_LOCATION", "US"),
            cache_enabled=_env_bool("CACHE_ENABLED", "true"),
            cache_ttl_seconds=_env_int("CACHE_TTL_SECONDS", 3600),
            cache_namespace=os.getenv("CACHE_NAMESPACE", "snti-ai"),
            top_query_tracking_enabled=_env_bool("TOP_QUERY_TRACKING_ENABLED", "true"),
            redis_url=os.getenv("REDIS_URL") or None,
            redis_host=os.getenv("REDIS_HOST") or None,
            redis_port=_env_int("REDIS_PORT", 6379),
            redis_db=_env_int("REDIS_DB", 0),
            redis_password=os.getenv("REDIS_PASSWORD") or None,
            redis_ssl=_env_bool("REDIS_SSL"),
            telemetry_enabled=_env_bool("TELEMETRY_ENABLED", "true"),
            cloud_logging_enabled=_env_bool("CLOUD_LOGGING_ENABLED", "true"),
            bigquery_telemetry_enabled=_env_bool("BIGQUERY_TELEMETRY_ENABLED"),
            telemetry_file_enabled=_env_bool("TELEMETRY_FILE_ENABLED", "true"),
            telemetry_file_path=os.getenv("TELEMETRY_FILE_PATH", "logs/chat_telemetry.jsonl"),
            bigquery_telemetry_dataset=os.getenv("BIGQUERY_TELEMETRY_DATASET", "analytics"),
            bigquery_telemetry_table=os.getenv("BIGQUERY_TELEMETRY_TABLE", "chat_telemetry"),
            telemetry_batch_enabled=_env_bool("TELEMETRY_BATCH_ENABLED", "true"),
            telemetry_batch_size=_env_int("TELEMETRY_BATCH_SIZE", 10),
            telemetry_flush_interval_seconds=_env_int("TELEMETRY_FLUSH_INTERVAL_SECONDS", 30),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            gcs_staging_bucket=os.getenv("GCS_STAGING_BUCKET") or None,
            bigquery_raw_dataset=os.getenv("BIGQUERY_RAW_DATASET", "raw"),
            bigquery_context_dataset=os.getenv("BIGQUERY_CONTEXT_DATASET", "analytics"),
            bigquery_context_table=os.getenv("BIGQUERY_CONTEXT_TABLE", "chat_context_docs"),
            rag_use_bigquery=_env_bool("RAG_USE_BIGQUERY"),
            rag_use_embeddings=_env_bool("RAG_USE_EMBEDDINGS"),
            rag_embedding_model=os.getenv("RAG_EMBEDDING_MODEL", "gemini-embedding-001"),
            rag_vector_index_path=os.getenv("RAG_VECTOR_INDEX_PATH", ".rag_index/context_vectors.json"),
            data_access_control_enabled=_env_bool("DATA_ACCESS_CONTROL_ENABLED", "true"),
            data_access_rules=os.getenv("DATA_ACCESS_RULES") or None,
            data_access_default_sources=os.getenv("DATA_ACCESS_DEFAULT_SOURCES") or None,
            max_input_tokens=_env_int("MAX_INPUT_TOKENS", 6000),
            max_context_tokens=_env_int("MAX_CONTEXT_TOKENS", 2500),
            max_output_tokens=_env_int("MAX_OUTPUT_TOKENS", 4096),
            model_auto_routing_enabled=_env_bool("MODEL_AUTO_ROUTING_ENABLED", "true"),
            cheap_model_choice=os.getenv("CHEAP_MODEL_CHOICE", "Llama"),
            premium_model_choice=os.getenv("PREMIUM_MODEL_CHOICE", "Gemini"),
            low_risk_token_threshold=_env_int("LOW_RISK_TOKEN_THRESHOLD", 500),
            language_detection_enabled=_env_bool("LANGUAGE_DETECTION_ENABLED", "true"),
            translation_enabled=_env_bool("TRANSLATION_ENABLED", "false"),
            translation_target_language=os.getenv("TRANSLATION_TARGET_LANGUAGE", "English"),
            secret_manager_enabled=_env_bool("SECRET_MANAGER_ENABLED"),
            groq_api_key_secret=os.getenv("GROQ_API_KEY_SECRET", "groq-api-key"),
            gemini_api_key_secret=os.getenv("GEMINI_API_KEY_SECRET", "gemini-api-key"),
            pii_redaction_enabled=_env_bool("PII_REDACTION_ENABLED", "true"),
            prompt_validation_enabled=_env_bool("PROMPT_VALIDATION_ENABLED", "true"),
            forbidden_topic_patterns=os.getenv("FORBIDDEN_TOPIC_PATTERNS") or None,
            output_moderation_enabled=_env_bool("OUTPUT_MODERATION_ENABLED", "true"),
            output_moderation_patterns=os.getenv("OUTPUT_MODERATION_PATTERNS") or None,
            reference_checking_enabled=_env_bool("REFERENCE_CHECKING_ENABLED", "true"),
            audit_prompt_preview_enabled=_env_bool("AUDIT_PROMPT_PREVIEW_ENABLED"),
        )

    def public_dict(self) -> dict[str, Any]:
        hidden = {
            "groq_api_key",
            "gemini_api_key",
            "together_api_key",
            "aicredits_api_key",
            "cerebras_api_key",
            "cloudflare_auth_token",
            "firebase_web_api_key",
            "appwrite_api_key",
            "oidc_client_secret",
            "redis_password",
            "smtp_password",
        }
        return {
            key: ("***" if key in hidden and value else value)
            for key, value in self.__dict__.items()
        }


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings.from_env()
