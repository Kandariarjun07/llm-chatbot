import os

from groq import Groq, AsyncGroq
from google import genai
from cerebras.cloud.sdk import Cerebras
import json
import requests
from typing import Any

try:
    import vertexai
    from vertexai.generative_models import GenerativeModel as VertexGenerativeModel
except ImportError:
    vertexai = None
    VertexGenerativeModel = None

try:
    from tenacity import retry, stop_after_attempt, wait_exponential
except ImportError:
    def retry(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

    def stop_after_attempt(*args, **kwargs):
        return None

    def wait_exponential(*args, **kwargs):
        return None

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        return False

from app.secret_manager import get_secret_value
from app.config import get_settings
from app.token_budget import trim_to_token_budget
from llm.circuit_breaker import CircuitOpenError, call_with_breaker


load_dotenv()

# Hard ceilings to prevent any LLM call from hanging a worker indefinitely.
# Non-streaming calls should resolve in well under a minute; streaming calls
# may legitimately take longer when generating large outputs.
LLM_TIMEOUT_SECONDS = 60
LLM_STREAM_TIMEOUT_SECONDS = 300

GROQ_API_KEY = get_secret_value("GROQ_API_KEY", "GROQ_API_KEY_SECRET")
GEMINI_API_KEY = get_secret_value("GEMINI_API_KEY", "GEMINI_API_KEY_SECRET")
TOGETHER_API_KEY = get_secret_value("TOGETHER_API_KEY", "TOGETHER_API_KEY_SECRET")
AICREDITS_API_KEY = get_secret_value("AICREDITS_API_KEY", "AICREDITS_API_KEY_SECRET")
CEREBRAS_API_KEY = get_secret_value("CEREBRAS_API_KEY", "CEREBRAS_API_KEY_SECRET")
CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID") or None
CLOUDFLARE_AUTH_TOKEN = os.environ.get("CLOUDFLARE_AUTH_TOKEN") or None

# Tolerate missing keys at import time. Calls below will raise a clear error
# only when the LLM is actually invoked, allowing the auth API to boot
# without LLM credentials configured.
try:
    groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
except Exception:
    groq_client = None

# AsyncGroq is used exclusively for streaming endpoints. The sync Groq
# client is kept for the rest of the codebase (non-streaming completions,
# tool decisions, etc.) so this change is non-breaking.
#
# Why a separate async client: each token from the sync iterator requires
# `await asyncio.to_thread(...)` which adds a thread context switch (~10-
# 50ms) per token. For a 500-token response that's >5s of pure overhead.
# AsyncGroq uses httpx's async transport directly — no threadpool, no
# context switch — and runs concurrent requests as independent coroutines
# instead of competing for threadpool slots.
try:
    async_groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
except Exception:
    async_groq_client = None

try:
    cerebras_client = Cerebras(api_key=CEREBRAS_API_KEY) if CEREBRAS_API_KEY else None
except Exception:
    cerebras_client = None

try:
    if GEMINI_API_KEY:
        try:
            # google-genai expects timeout in MILLISECONDS via http_options.
            gemini_client = genai.Client(
                api_key=GEMINI_API_KEY,
                http_options=genai.types.HttpOptions(timeout=LLM_TIMEOUT_SECONDS * 1000),
            )
        except (TypeError, AttributeError):
            # Older SDK versions don't accept http_options at construction.
            gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    else:
        gemini_client = None
except Exception:
    gemini_client = None


def _call_groq(user_input: str, temperature: float = 0.2, max_output_tokens: int | None = None, model: str | None = None, system: str | None = None) -> str:
    settings = get_settings()
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_input})
    request = {
        "model": model or settings.groq_llama_model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_output_tokens:
        request["max_completion_tokens"] = max_output_tokens

    try:
        response = groq_client.chat.completions.create(timeout=LLM_TIMEOUT_SECONDS, **request)
    except TypeError:
        request.pop("max_completion_tokens", None)
        response = groq_client.chat.completions.create(timeout=LLM_TIMEOUT_SECONDS, **request)

    return response.choices[0].message.content


def _call_gemini(user_input: str, temperature: float = 0.2, max_output_tokens: int | None = None, system: str | None = None) -> str:
    settings = get_settings()
    if not gemini_client:
        raise RuntimeError("Gemini API key not configured")
        
    config_dict = {"temperature": temperature}
    if max_output_tokens:
        config_dict["max_output_tokens"] = max_output_tokens
    if system:
        config_dict["system_instruction"] = system
        
    response = gemini_client.models.generate_content(
        model=settings.gemini_api_model,
        contents=user_input,
        config=genai.types.GenerateContentConfig(**config_dict),
        # Gemini SDK expects timeout in milliseconds via http_options.
    )
    return response.text


def _call_vertex_gemini(
    user_input: str,
    temperature: float = 0.2,
    max_output_tokens: int | None = None,
    system: str | None = None,
) -> str:
    settings = get_settings()
    if vertexai is None or VertexGenerativeModel is None:
        raise RuntimeError("google-cloud-aiplatform is required for Vertex AI Gemini.")
    if not settings.vertex_ai_project_id:
        raise RuntimeError("VERTEX_AI_PROJECT_ID or GCP_PROJECT_ID is required for Vertex AI Gemini.")

    # Fail fast if GCP credentials are not available
    import os
    import platform
    adc_env = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    has_adc = False
    if adc_env and os.path.exists(adc_env):
        has_adc = True
    else:
        if platform.system() == "Windows":
            default_path = os.path.expandvars(r"%APPDATA%\gcloud\application_default_credentials.json")
        else:
            default_path = os.path.expanduser("~/.config/gcloud/application_default_credentials.json")
        if os.path.exists(default_path):
            has_adc = True
            
    if not has_adc:
        raise RuntimeError("Google Application Default Credentials (ADC) are not configured. Bypassing Vertex AI to prevent 45s metadata hang.")

    import google.auth
    from google.auth.exceptions import DefaultCredentialsError
    try:
        google.auth.default()
    except DefaultCredentialsError as e:
        raise RuntimeError(f"Google Application Default Credentials (ADC) are not configured. Cannot use Vertex AI: {e}")

    vertexai.init(project=settings.vertex_ai_project_id, location=settings.vertex_ai_location)
    model = VertexGenerativeModel(settings.vertex_ai_gemini_model, system_instruction=system)
    generation_config = {"temperature": temperature}
    if max_output_tokens:
        generation_config["max_output_tokens"] = max_output_tokens

    try:
        response = model.generate_content(
            user_input,
            generation_config=generation_config,
            request_options={"timeout": LLM_TIMEOUT_SECONDS},
        )
    except TypeError:
        # Older SDKs don't accept request_options.
        response = model.generate_content(user_input, generation_config=generation_config)
    return response.text


def _call_openai_compatible(api_key: str, base_url: str, model: str, user_input: str, temperature: float = 0.2, max_output_tokens: int | None = None) -> str:
    if not api_key:
        raise RuntimeError(f"API key for {base_url} is not configured.")
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": user_input}],
        "temperature": temperature,
    }
    if max_output_tokens:
        payload["max_tokens"] = max_output_tokens
    r = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=LLM_TIMEOUT_SECONDS,
    )
    r.raise_for_status()
    data = r.json()
    msg = data["choices"][0]["message"]
    content = msg.get("content") or ""
    return content or "(No response received from the model.)"


def _call_aicredits(user_input: str, temperature: float = 0.2, max_output_tokens: int | None = None) -> str:
    """Call the AI Credits provider with a hard ₹-cap pre-flight check."""
    from app.aicredits_tracker import assert_within_limit, record_usage

    settings = get_settings()
    if not AICREDITS_API_KEY:
        raise RuntimeError("AICREDITS_API_KEY is not configured.")
    assert_within_limit()

    payload: dict[str, Any] = {
        "model": settings.aicredits_model,
        "messages": [{"role": "user", "content": user_input}],
        "temperature": temperature,
    }
    if max_output_tokens:
        payload["max_tokens"] = max_output_tokens

    r = requests.post(
        f"{settings.aicredits_base_url}/chat/completions",
        headers={"Authorization": f"Bearer {AICREDITS_API_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=LLM_TIMEOUT_SECONDS,
    )
    r.raise_for_status()
    data = r.json()
    record_usage(data.get("usage"))
    msg = data["choices"][0]["message"]
    content = msg.get("content") or ""
    return content or "(No response received from the model.)"


def _stream_aicredits(user_input: str, temperature: float = 0.2, max_output_tokens: int | None = None):
    """Stream from the AI Credits provider, recording usage at the end."""
    from app.aicredits_tracker import assert_within_limit, record_usage

    settings = get_settings()
    if not AICREDITS_API_KEY:
        raise RuntimeError("AICREDITS_API_KEY is not configured.")
    assert_within_limit()

    payload: dict[str, Any] = {
        "model": settings.aicredits_model,
        "messages": [{"role": "user", "content": user_input}],
        "temperature": temperature,
        "stream": True,
        # Ask the upstream to emit a final usage chunk (OpenAI-spec extension).
        "stream_options": {"include_usage": True},
    }
    if max_output_tokens:
        payload["max_tokens"] = max_output_tokens

    captured_usage: dict[str, Any] | None = None
    with requests.post(
        f"{settings.aicredits_base_url}/chat/completions",
        headers={"Authorization": f"Bearer {AICREDITS_API_KEY}", "Content-Type": "application/json"},
        json=payload,
        stream=True,
        timeout=LLM_STREAM_TIMEOUT_SECONDS,
    ) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            decoded = line.decode("utf-8")
            if not decoded.startswith("data: "):
                continue
            chunk = decoded[6:]
            if chunk.strip() == "[DONE]":
                break
            try:
                obj = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            # Final usage chunk has `choices: []` and a populated `usage`.
            if obj.get("usage"):
                captured_usage = obj["usage"]
            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            text = delta.get("content") or ""
            if text:
                yield text

    record_usage(captured_usage)


def _stream_openai_compatible(api_key: str, base_url: str, model: str, user_input: str, temperature: float = 0.2, max_output_tokens: int | None = None):
    if not api_key:
        raise RuntimeError(f"API key for {base_url} is not configured.")
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": user_input}],
        "temperature": temperature,
        "stream": True,
    }
    if max_output_tokens:
        payload["max_tokens"] = max_output_tokens
    with requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        stream=True,
        timeout=LLM_STREAM_TIMEOUT_SECONDS,
    ) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            decoded = line.decode("utf-8")
            if decoded.startswith("data: "):
                chunk = decoded[6:]
                if chunk.strip() == "[DONE]":
                    break
                try:
                    obj = json.loads(chunk)
                    delta = obj["choices"][0]["delta"]
                    text = delta.get("content") or ""
                    if text:
                        yield text
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue


def chat_completion(
    messages,
    model_choice="Llama",
    temperature: float = 0.2,
    max_output_tokens: int | None = None,
    max_input_tokens: int | None = None,
    system: str | None = None,
    model: str | None = None,
):
    settings = get_settings()
    max_input_tokens = max_input_tokens or settings.max_input_tokens
    max_output_tokens = max_output_tokens or settings.max_output_tokens
    user_input = trim_to_token_budget(messages[-1]["content"], max_input_tokens).text

    try:
        if model_choice == "Gemini":
            if GEMINI_API_KEY:
                try:
                    return call_with_breaker(
                        "gemini",
                        _call_gemini,
                        user_input,
                        temperature=temperature,
                        max_output_tokens=max_output_tokens,
                        system=system,
                    )
                except (Exception, CircuitOpenError):
                    pass

            if settings.llm_provider.lower() in {"vertex_gemini", "vertex", "vertex_ai", "vertex-ai"}:
                try:
                    return call_with_breaker(
                        "vertex_gemini",
                        _call_vertex_gemini,
                        user_input,
                        temperature=temperature,
                        max_output_tokens=max_output_tokens,
                        system=system,
                    )
                except (Exception, CircuitOpenError):
                    pass

            # If GEMINI_API_KEY wasn't tried yet (e.g. not set but default provider is vertex which failed):
            if not GEMINI_API_KEY:
                try:
                    return call_with_breaker(
                        "gemini",
                        _call_gemini,
                        user_input,
                        temperature=temperature,
                        max_output_tokens=max_output_tokens,
                        system=system,
                    )
                except (Exception, CircuitOpenError):
                    pass

            # Groq fallback
            return call_with_breaker(
                "groq",
                _call_groq,
                user_input,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                system=system,
            )

        if model_choice == "Llama":
            # Fallback chain: Groq → AICredits → Cerebras → Cloudflare
            try:
                return call_with_breaker(
                    "groq",
                    _call_groq,
                    user_input,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    system=system,
                    model=model,
                )
            except (Exception, CircuitOpenError):
                pass

            try:
                return call_with_breaker(
                    "aicredits",
                    _call_aicredits,
                    user_input,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                )
            except (Exception, CircuitOpenError):
                pass

            try:
                return call_with_breaker(
                    "cerebras",
                    _call_cerebras,
                    user_input,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    system=system,
                )
            except (Exception, CircuitOpenError):
                pass

            try:
                return call_with_breaker(
                    "cloudflare",
                    _call_cloudflare,
                    user_input,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    system=system,
                )
            except (Exception, CircuitOpenError):
                pass

            return "Error: All LLM providers are currently unavailable. Please try again later."

        if model_choice == "Think":
            # Fallback chain: Groq (think model) → AICredits → Cerebras → Cloudflare
            try:
                return call_with_breaker(
                    "groq",
                    _call_groq,
                    user_input,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    system=system,
                    model=settings.groq_think_model,
                )
            except (Exception, CircuitOpenError):
                pass

            try:
                return call_with_breaker(
                    "aicredits",
                    _call_aicredits,
                    user_input,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                )
            except (Exception, CircuitOpenError):
                pass

            try:
                return call_with_breaker(
                    "cerebras",
                    _call_cerebras,
                    user_input,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    system=system,
                )
            except (Exception, CircuitOpenError):
                pass

            try:
                return call_with_breaker(
                    "cloudflare",
                    _call_cloudflare,
                    user_input,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    system=system,
                )
            except (Exception, CircuitOpenError):
                pass

            return "Error: All LLM providers are currently unavailable. Please try again later."

        if model_choice == "AICredits":
            return call_with_breaker(
                "aicredits",
                _call_aicredits,
                user_input,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )

        if model_choice == "Cerebras":
            return call_with_breaker(
                "cerebras",
                _call_cerebras,
                user_input,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                system=system,
            )

        if model_choice == "Cloudflare":
            return call_with_breaker(
                "cloudflare",
                _call_cloudflare,
                user_input,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                system=system,
            )

        return "This is a fallback response."

    except CircuitOpenError as e:
        # All providers we tried are tripped — give the caller a clear
        # short-circuit message instead of a generic 500.
        return f"Error: {str(e)} — provider temporarily unavailable, please retry shortly."
    except Exception as e:
        return f"Error: {str(e)}"


# ── Streaming variants ─────────────────────────────────────────────

def _stream_groq(user_input: str, temperature: float = 0.2, max_output_tokens: int | None = None, model: str | None = None):
    """Yield text chunks from Groq streaming."""
    if groq_client is None:
        raise RuntimeError("Groq client not initialized.")
    settings = get_settings()
    request = {
        "model": model or settings.groq_llama_model,
        "messages": [{"role": "user", "content": user_input}],
        "temperature": temperature,
        "stream": True,
    }
    if max_output_tokens:
        request["max_completion_tokens"] = max_output_tokens

    try:
        stream = groq_client.chat.completions.create(timeout=LLM_STREAM_TIMEOUT_SECONDS, **request)
    except TypeError:
        request.pop("max_completion_tokens", None)
        stream = groq_client.chat.completions.create(timeout=LLM_STREAM_TIMEOUT_SECONDS, **request)

    for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta


def _stream_gemini(user_input: str, temperature: float = 0.2, max_output_tokens: int | None = None, system: str | None = None):
    """Yield text chunks from Gemini API streaming."""
    settings = get_settings()
    if not gemini_client:
        raise RuntimeError("Gemini API key not configured")
        
    config_dict = {"temperature": temperature}
    if max_output_tokens:
        config_dict["max_output_tokens"] = max_output_tokens
    if system:
        config_dict["system_instruction"] = system

    stream = gemini_client.models.generate_content_stream(
        model=settings.gemini_api_model,
        contents=user_input,
        config=genai.types.GenerateContentConfig(**config_dict),
    )
    for chunk in stream:
        if chunk.text:
            yield chunk.text


def _call_cerebras(user_input: str, temperature: float = 0.2, max_output_tokens: int | None = None, system: str | None = None) -> str:
    """Non-streaming call to Cerebras SDK."""
    settings = get_settings()
    if not cerebras_client:
        raise RuntimeError("Cerebras API key not configured")
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_input})
    request = {
        "model": settings.cerebras_model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_output_tokens:
        request["max_completion_tokens"] = max_output_tokens
    response = cerebras_client.chat.completions.create(**request)
    return response.choices[0].message.content or "(No response received from the model.)"


def _stream_cerebras(user_input: str, temperature: float = 0.2, max_output_tokens: int | None = None, system: str | None = None):
    """Yield text chunks from Cerebras streaming."""
    if not cerebras_client:
        raise RuntimeError("Cerebras client not initialized.")
    settings = get_settings()
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_input})
    request = {
        "model": settings.cerebras_model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    if max_output_tokens:
        request["max_completion_tokens"] = max_output_tokens
    stream = cerebras_client.chat.completions.create(**request)
    for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta


def _call_cloudflare(user_input: str, temperature: float = 0.2, max_output_tokens: int | None = None, system: str | None = None) -> str:
    """Non-streaming call to Cloudflare Workers AI."""
    settings = get_settings()
    if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_AUTH_TOKEN:
        raise RuntimeError("Cloudflare account ID or auth token not configured")
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_input})
    payload: dict[str, Any] = {
        "messages": messages,
    }
    if max_output_tokens:
        payload["max_tokens"] = max_output_tokens
    r = requests.post(
        f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/{settings.cloudflare_model}",
        headers={"Authorization": f"Bearer {CLOUDFLARE_AUTH_TOKEN}", "Content-Type": "application/json"},
        json=payload,
        timeout=LLM_TIMEOUT_SECONDS,
    )
    r.raise_for_status()
    data = r.json()

    # Cloudflare Workers AI response formats vary by model.
    # Try the common {result: {response: ...}} shape first.
    result = data.get("result", {})
    if isinstance(result, dict):
        text = result.get("response") or ""
        if text:
            return text
        msg = result.get("message", {})
        if isinstance(msg, dict):
            text = msg.get("content") or ""
            if text:
                return text

    # Some models return an OpenAI-compatible {choices: [...]} shape.
    choices = data.get("choices")
    if choices and isinstance(choices, list) and len(choices) > 0:
        msg = choices[0].get("message", {})
        if isinstance(msg, dict):
            text = msg.get("content") or ""
            if text:
                return text

    return "(No response received from the model.)"


def _stream_cloudflare(user_input: str, temperature: float = 0.2, max_output_tokens: int | None = None, system: str | None = None):
    """Yield text chunks from Cloudflare Workers AI streaming."""
    settings = get_settings()
    if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_AUTH_TOKEN:
        raise RuntimeError("Cloudflare account ID or auth token not configured")
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_input})
    payload: dict[str, Any] = {
        "messages": messages,
        "stream": True,
    }
    if max_output_tokens:
        payload["max_tokens"] = max_output_tokens
    with requests.post(
        f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/{settings.cloudflare_model}?stream=true",
        headers={"Authorization": f"Bearer {CLOUDFLARE_AUTH_TOKEN}", "Content-Type": "application/json"},
        json=payload,
        stream=True,
        timeout=LLM_STREAM_TIMEOUT_SECONDS,
    ) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            decoded = line.decode("utf-8")
            if decoded.startswith("data: "):
                decoded = decoded[6:]
            if decoded.strip() == "[DONE]":
                break
            try:
                obj = json.loads(decoded)
            except json.JSONDecodeError:
                continue

            # Try multiple Cloudflare streaming response formats.
            text = obj.get("response") or ""
            if not text and "result" in obj:
                result = obj["result"]
                if isinstance(result, dict):
                    text = result.get("response") or ""
                    if not text:
                        msg = result.get("message", {})
                        if isinstance(msg, dict):
                            text = msg.get("content") or ""

            if not text and "choices" in obj:
                choices = obj.get("choices", [])
                if choices and isinstance(choices, list) and len(choices) > 0:
                    delta = choices[0].get("delta", {})
                    if isinstance(delta, dict):
                        text = delta.get("content") or ""

            if text:
                yield text


def chat_completion_stream(
    messages,
    model_choice="Llama",
    temperature: float = 0.2,
    max_output_tokens: int | None = None,
    max_input_tokens: int | None = None,
    system: str | None = None,
):
    """Generator that yields text deltas from the active LLM."""
    settings = get_settings()
    max_input_tokens = max_input_tokens or settings.max_input_tokens
    max_output_tokens = max_output_tokens or settings.max_output_tokens
    user_input = trim_to_token_budget(messages[-1]["content"], max_input_tokens).text

    try:
        if model_choice == "Gemini":
            # Prefer Gemini API streaming; fall back to Groq if unavailable
            try:
                yield from _stream_gemini(user_input, temperature=temperature, max_output_tokens=max_output_tokens, system=system)
                return
            except Exception:
                pass
            yield from _stream_groq(user_input, temperature=temperature, max_output_tokens=max_output_tokens, system=system)
            return

        if model_choice == "Llama":
            # Fallback chain: Groq → AICredits → Cerebras → Cloudflare
            try:
                yield from _stream_groq(user_input, temperature=temperature, max_output_tokens=max_output_tokens)
                return
            except Exception:
                pass

            try:
                yield from _stream_aicredits(user_input, temperature=temperature, max_output_tokens=max_output_tokens)
                return
            except Exception:
                pass

            try:
                yield from _stream_cerebras(user_input, temperature=temperature, max_output_tokens=max_output_tokens)
                return
            except Exception:
                pass

            try:
                yield from _stream_cloudflare(user_input, temperature=temperature, max_output_tokens=max_output_tokens)
                return
            except Exception:
                pass

            yield "Error: All LLM providers are currently unavailable. Please try again later."
            return

        if model_choice == "Think":
            # Fallback chain: Groq (think model) → AICredits → Cerebras → Cloudflare
            try:
                yield from _stream_groq(
                    user_input,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    model=settings.groq_think_model,
                )
                return
            except Exception:
                pass

            try:
                yield from _stream_aicredits(user_input, temperature=temperature, max_output_tokens=max_output_tokens)
                return
            except Exception:
                pass

            try:
                yield from _stream_cerebras(user_input, temperature=temperature, max_output_tokens=max_output_tokens)
                return
            except Exception:
                pass

            try:
                yield from _stream_cloudflare(user_input, temperature=temperature, max_output_tokens=max_output_tokens)
                return
            except Exception:
                pass

            yield "Error: All LLM providers are currently unavailable. Please try again later."
            return

        if model_choice == "AICredits":
            yield from _stream_aicredits(
                user_input,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
            return

        if model_choice == "Cerebras":
            yield from _stream_cerebras(
                user_input,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
            return

        if model_choice == "Cloudflare":
            yield from _stream_cloudflare(
                user_input,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
            return

        yield "This is a fallback response."

    except Exception as e:
        yield f"Error: {str(e)}"


# ── Async streaming variants ───────────────────────────────────────
#
# These mirror the sync versions above but use native async I/O so the
# FastAPI event loop never blocks on a thread. Used by the streaming
# endpoint (`/chat/stream`) for true concurrency: each request is an
# independent coroutine instead of competing for threadpool slots.

async def _astream_groq(
    user_input: str,
    temperature: float = 0.2,
    max_output_tokens: int | None = None,
    model: str | None = None,
    system: str | None = None,
):
    """Async generator yielding text chunks from Groq."""
    if async_groq_client is None:
        raise RuntimeError("Async Groq client not initialized.")
    settings = get_settings()
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_input})
    request: dict[str, Any] = {
        "model": model or settings.groq_llama_model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    if max_output_tokens:
        request["max_completion_tokens"] = max_output_tokens

    try:
        stream = await async_groq_client.chat.completions.create(
            timeout=LLM_STREAM_TIMEOUT_SECONDS, **request
        )
    except TypeError:
        request.pop("max_completion_tokens", None)
        stream = await async_groq_client.chat.completions.create(
            timeout=LLM_STREAM_TIMEOUT_SECONDS, **request
        )

    async for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta


async def achat_completion_stream(
    messages,
    model_choice: str = "Llama",
    temperature: float = 0.2,
    max_output_tokens: int | None = None,
    max_input_tokens: int | None = None,
    system: str | None = None,
):
    """Async generator that yields text deltas from the active LLM.

    Currently uses native async I/O for Groq (Llama / Gemini-fallback).
    Other providers fall back to the sync generator wrapped in
    `asyncio.to_thread` since they don't expose an async client.
    """
    settings = get_settings()
    max_input_tokens = max_input_tokens or settings.max_input_tokens
    max_output_tokens = max_output_tokens or settings.max_output_tokens
    user_input = trim_to_token_budget(messages[-1]["content"], max_input_tokens).text

    try:
        if model_choice == "Llama" and async_groq_client is not None:
            # Fallback chain: async Groq → sync AICredits → sync Cerebras → sync Cloudflare
            try:
                async for delta in _astream_groq(
                    user_input,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    system=system,
                ):
                    yield delta
                return
            except Exception:
                pass

            # Fall through to sync generator bridge which has the full fallback chain

        if model_choice == "Think" and async_groq_client is not None:
            # Fallback chain: async Groq (think model) → sync AICredits → sync Cerebras → sync Cloudflare
            try:
                async for delta in _astream_groq(
                    user_input,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    model=settings.groq_think_model,
                    system=system,
                ):
                    yield delta
                return
            except Exception:
                pass

            # Fall through to sync generator bridge which has the full fallback chain

        if model_choice == "Gemini" and async_groq_client is not None:
            # Gemini SDK is sync. Try Gemini first via thread-bridge, fall
            # back to async Groq (which is faster anyway) on failure.
            try:
                import asyncio as _asyncio

                def _gen():
                    return list(
                        _stream_gemini(
                            user_input,
                            temperature=temperature,
                            max_output_tokens=max_output_tokens,
                            system=system,
                        )
                    )

                chunks = await _asyncio.to_thread(_gen)
                for delta in chunks:
                    yield delta
                return
            except Exception:
                async for delta in _astream_groq(
                    user_input,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    system=system,
                ):
                    yield delta
                return

        # Fallback: bridge the sync generator via asyncio.to_thread per
        # token. Slower but works for providers without async SDKs.
        import asyncio as _asyncio

        def _next(it):
            try:
                return True, next(it)
            except StopIteration:
                return False, ""

        sync_iter = chat_completion_stream(
            messages,
            model_choice=model_choice,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            max_input_tokens=max_input_tokens,
            system=system,
        )
        while True:
            has_delta, delta = await _asyncio.to_thread(_next, sync_iter)
            if not has_delta:
                break
            if delta:
                yield delta

    except Exception as e:
        yield f"Error: {str(e)}"
