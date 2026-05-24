import json
import logging
import os
import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Literal

# Load project root .env BEFORE importing anything that reads env vars.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configure root logging so our `logger.error / .warning / .info` calls
# actually show up in Render / Cloud Run logs. LOG_LEVEL env var lets ops
# bump verbosity to DEBUG on demand without a redeploy.
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api.auth_routes import get_current_user, router as auth_router
from api.chat_routes import router as chat_router
from api.images_routes import router as images_router
from api.upload_routes import router as upload_router
from api.multimodal_routes import router as multimodal_router
from api.sheets_routes import router as sheets_router
from api.transcribe_routes import router as transcribe_router
from api.diagram_routes import router as diagram_router
from app.cache import answer_cache
from app.config import get_settings
from app.db import init_tables
from app.mode_routing import mode_to_model_choice
from app.orchestrator import answer_query, build_chat_messages
from app.rate_limits import check_deep_research_limit, RateLimit
from llm.client import achat_completion_stream
from prompts.compose import list_prompt_templates

logger = logging.getLogger(__name__)


class ChatHistoryItem(BaseModel):
    """Minimal shape of a prior chat turn sent from the client.

    Only role + content are accepted; client-side metadata (ids, timestamps)
    is intentionally dropped at the API boundary.
    """

    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1)
    # `mode` is the new product-facing field (Fast / Think). When set, it
    # overrides `model_choice` server-side. `model_choice` is kept for
    # backward compatibility with older clients and internal callers.
    mode: Literal["Fast", "Think"] | None = None
    model_choice: Literal["Auto", "Llama", "Gemini", "AICredits", "Cerebras", "Cloudflare"] = "Llama"
    temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    include_trace: bool = False
    web_search: bool = False
    research: bool = False
    # Conversation history for multi-turn context. Newest turn LAST. The
    # *current* query is `query` above and should NOT also appear in this
    # list. The orchestrator will trim by token budget before injection.
    history: list[ChatHistoryItem] = Field(default_factory=list)


class ChatResponse(BaseModel):
    answer: str
    model_choice: str
    used_context_count: int = 0
    trace: dict[str, Any] | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """App-startup hook: initialize DB schema before serving any traffic.

    Without this the very first request after a fresh Postgres deploy
    would fail with `relation "conversations" does not exist`. SQLite
    init is lazy and remains a no-op here.
    """
    try:
        await init_tables()
        logger.info("Database tables initialized.")
    except Exception as exc:
        # Don't crash the whole app if DB init fails — surface a clear log
        # so operators can spot it, but keep auth/chat working in degraded
        # mode (the relevant routes will still raise their own errors).
        logger.error("Database initialization failed: %s", exc)
    yield


app = FastAPI(title="SNTI AI Assistant API", version="1.0.0", lifespan=lifespan)

# ── Global body-size guard (M3) ──────────────────────────────────
# Reject uploads / JSON bodies before FastAPI buffers them in memory.
MAX_BODY_BYTES = 25 * 1024 * 1024  # 25 MB — generous, since upload routes
# use FormData with 20 MB per-file limits anyway.


@app.middleware("http")
async def _size_guard(request: Request, call_next):
    t0 = time.perf_counter()
    # Defense-in-depth: rewrite any stray /api/* paths to their root
    # equivalents so older browser-cached frontends keep working until
    # the user picks up the new build. Production routes don't use /api,
    # but the dev Vite proxy does — this makes both behaviors transparent.
    raw_path = request.url.path
    if raw_path.startswith("/api/"):
        new_path = raw_path[4:] or "/"
        request.scope["path"] = new_path
        request.scope["raw_path"] = new_path.encode("utf-8")
    path = request.url.path
    cl = request.headers.get("content-length")
    if cl is not None:
        try:
            if int(cl) > MAX_BODY_BYTES:
                print(f"[timing] {path} rejected body-size after {(time.perf_counter()-t0)*1000:.0f}ms", flush=True)
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body too large (max {MAX_BODY_BYTES // (1024*1024)} MB)."},
                )
        except ValueError:
            pass
    response = await call_next(request)
    print(f"[timing] {path} total_server={(time.perf_counter()-t0)*1000:.0f}ms", flush=True)
    return response

# ── CORS ─────────────────────────────────────────────────────────
_default_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
    "http://localhost:4173",
]
_extra = os.getenv("CORS_ALLOW_ORIGINS", "")
_origins = _default_origins + [o.strip() for o in _extra.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global exception handler ─────────────────────────────────────
# Without this, any unhandled exception inside a route handler returns
# Starlette's bare 500 with no body, which makes debugging in production
# painful. We log the full traceback to stderr (visible in Render logs)
# and surface a stable JSON shape the frontend can render.
@app.exception_handler(Exception)
async def _unhandled_exception(request: Request, exc: Exception):
    import traceback
    tb = traceback.format_exc()
    logger.error("Unhandled error on %s %s: %s\n%s",
                 request.method, request.url.path, exc, tb)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error. Please try again; if it persists, contact support.",
            "path": request.url.path,
        },
    )


# ── Routers ──────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(images_router)
app.include_router(upload_router)
app.include_router(multimodal_router)
app.include_router(sheets_router)
app.include_router(transcribe_router)
app.include_router(diagram_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/config")
def config():
    return get_settings().public_dict()


@app.get("/prompts")
def prompts():
    return {"templates": list_prompt_templates()}


@app.get("/cache/top", dependencies=[Depends(get_current_user), Depends(RateLimit("cache.read", per_minute=60))])
def top_cached_queries(user: dict[str, Any] = Depends(get_current_user), limit: int = 10):
    return {"queries": answer_cache.top_queries(limit)}


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(RateLimit("chat.standard", per_minute=30, per_day=500))])
async def chat(request: ChatRequest, user: dict[str, Any] = Depends(get_current_user)):
    effective_model = mode_to_model_choice(request.mode, fallback=request.model_choice)
    history = [item.model_dump() for item in request.history]
    result = await answer_query(
        request.query,
        effective_model,
        include_trace=request.include_trace,
        temperature=request.temperature,
        user_id=user["user_id"],
        user_context={
            "user_id": user["user_id"],
            "email": user.get("email", ""),
            "roles": [],
            "groups": [],
        },
        web_search=request.web_search,
        research=request.research,
        history=history,
    )

    if isinstance(result, dict):
        return ChatResponse(
            answer=result["answer"],
            model_choice=effective_model,
            used_context_count=result["used_context_count"],
            trace=result["trace"],
        )

    return ChatResponse(answer=result, model_choice=effective_model)


@app.post("/chat/stream", dependencies=[Depends(RateLimit("chat.stream", per_minute=30, per_day=500))])
async def chat_stream(request: ChatRequest, user: dict[str, Any] = Depends(get_current_user)):
    """Stream the assistant response as Server-Sent Events.
    Runs the full orchestrator pipeline (guardrails, routing, context,
    web-search injection, prompt selection) then streams the LLM output.
    """

    MAX_STREAM_BYTES = 3 * 1024 * 1024  # 3 MB — hard cap on a single stream answer

    requested_model = mode_to_model_choice(request.mode, fallback=request.model_choice)

    # Per-request timer for diagnostic logs. Helps spot where latency
    # lives if the user reports a slow request: pre-build, build, or
    # streaming. Logs go to stdout so they're visible in the uvicorn
    # console alongside the standard request logs.
    import time as _t
    t_req = _t.perf_counter()

    def _ms() -> str:
        return f"{(_t.perf_counter() - t_req) * 1000:.0f}ms"

    print(f"[stream] request received  uid={user['user_id']!s} mode={request.mode} q={request.query[:40]!r}", flush=True)

    async def event_generator():
        print(f"[stream] generator:start  {_ms()}", flush=True)
        yield f"data: {json.dumps({'event': 'start', 'model': requested_model, 'mode': request.mode})}\n\n"

        # Pre-build phase signal — best guess from the user's toggles. This
        # gives the client something concrete to render *while* the heavy
        # work (search, decompose, gap analysis) is actually happening.
        if request.research:
            yield f"data: {json.dumps({'event': 'phase', 'phase': 'researching'})}\n\n"
        elif request.web_search:
            yield f"data: {json.dumps({'event': 'phase', 'phase': 'searching'})}\n\n"
        else:
            yield f"data: {json.dumps({'event': 'phase', 'phase': 'thinking'})}\n\n"

        try:
            history = [item.model_dump() for item in request.history]
            messages, effective_model, max_tokens, trace = await build_chat_messages(
                request.query,
                model_choice=requested_model,
                temperature=request.temperature,
                user_id=user["user_id"],
                user_context={
                    "user_id": user["user_id"],
                    "email": user.get("email", ""),
                    "roles": [],
                    "groups": [],
                },
                web_search=request.web_search,
                research=request.research,
                history=history,
            )
            print(f"[stream] build_done       {_ms()}  tool={trace.get('tool')}  model={effective_model}", flush=True)
        except Exception as e:
            print(f"[stream] build_error      {_ms()}  err={e!r}", flush=True)
            yield f"data: {json.dumps({'event': 'error', 'message': f'Pipeline error: {e}'})}\n\n"
            return

        # Post-build phase signal — based on actual trace data so the UI
        # reflects what really happened (auto-routed search counts, deep
        # research sub-question count, etc.).
        dr_trace = trace.get("deep_research_pipeline")
        if dr_trace:
            yield (
                "data: "
                + json.dumps(
                    {
                        "event": "phase",
                        "phase": "research_sources",
                        "count": dr_trace.get("final_count", 0),
                        "subs": len(dr_trace.get("sub_questions", []) or []),
                    }
                )
                + "\n\n"
            )
        elif trace.get("web_search") or trace.get("auto_routed_to_search"):
            yield (
                "data: "
                + json.dumps(
                    {
                        "event": "phase",
                        "phase": "sources",
                        "count": int(trace.get("used_context_count", 0) or 0),
                    }
                )
                + "\n\n"
            )

        # Guardrail or tool short-circuit (calculator / file / blocked)
        if len(messages) == 1 and messages[0].get("role") == "system":
            blocked_text = messages[0].get("content", "")
            yield f"data: {json.dumps({'event': 'delta', 'delta': blocked_text})}\n\n"
            done_payload = {'event': 'done', 'answer': blocked_text}
            if request.include_trace:
                done_payload["trace"] = trace
            yield f"data: {json.dumps(done_payload)}\n\n"
            return

        # Writing phase — last status before tokens start flowing.
        yield f"data: {json.dumps({'event': 'phase', 'phase': 'writing'})}\n\n"

        buffer = ""
        first_token_logged = False
        try:
            # Native async streaming — no per-token thread context switch.
            # AsyncGroq uses httpx async transport so each delta arrives
            # without leaving the event loop. For Llama/Fast mode this
            # cuts ~5-15s of overhead off a typical response.
            async for delta in achat_completion_stream(
                messages,
                model_choice=effective_model,
                temperature=request.temperature,
                max_output_tokens=max_tokens,
            ):
                if not first_token_logged:
                    first_token_logged = True
                    print(f"[stream] first_token       {_ms()}", flush=True)
                buffer += delta
                if len(buffer.encode("utf-8")) > MAX_STREAM_BYTES:
                    yield f"data: {json.dumps({'event': 'error', 'message': 'Response exceeded maximum stream size.'})}\n\n"
                    return
                yield f"data: {json.dumps({'event': 'delta', 'delta': delta})}\n\n"
            print(f"[stream] stream_complete   {_ms()}  chars={len(buffer)}", flush=True)
        except Exception as e:
            print(f"[stream] stream_error      {_ms()}  err={e!r}", flush=True)
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"

        done_payload = {'event': 'done', 'answer': buffer}
        if request.include_trace:
            done_payload["trace"] = trace
        yield f"data: {json.dumps(done_payload)}\n\n"

    print(f"[stream] returning_sr      {_ms()}", flush=True)
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",          # disable nginx buffering
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/limits")
def get_limits(user: dict[str, Any] = Depends(get_current_user)):
    """Return the user's remaining premium-feature quotas."""
    _, remaining = check_deep_research_limit(user["user_id"])
    return {"deep_research_remaining": remaining}


@app.get("/stream-test")
async def stream_test():
    """Minimal SSE endpoint to verify streaming isn't buffered end-to-end."""
    async def _gen():
        for i in range(5):
            yield f"data: {{\"chunk\":{i}}}\n\n"
            await asyncio.sleep(0.05)
    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Static frontend (production) ─────────────────────────────────
# Serve the built React app from frontend/dist.  API routes above take
# precedence.  All unmatched paths fall back to index.html so React Router
# client-side routes work after a hard refresh.
_frontend_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.isdir(_frontend_dist):
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from starlette.responses import FileResponse

    @app.exception_handler(StarletteHTTPException)
    async def _spa_fallback(_request: Request, _exc: StarletteHTTPException):
        # SPA fallback strategy: serve index.html for browser navigations,
        # JSON for API calls. We detect "browser navigation" as
        #   GET method  +  Accept includes text/html  +  not under /api/.
        # This correctly handles deep links like /chat/<id>, /login, etc.
        # which collide with backend route prefixes (chat_router, etc.) —
        # the backend has no GET handler for /chat/<id>, so it 404s, and
        # we transparently rewrite that to index.html so React Router can
        # take over client-side. Real API failures (POST, JSON Accept,
        # /api/* paths) still return structured JSON for the client to
        # surface to the user.
        if _exc.status_code == 404:
            accept = _request.headers.get("accept", "")
            looks_like_browser_nav = (
                _request.method == "GET"
                and "text/html" in accept.lower()
                and not _request.url.path.startswith("/api/")
            )
            if looks_like_browser_nav:
                index_path = os.path.join(_frontend_dist, "index.html")
                if os.path.isfile(index_path):
                    return FileResponse(index_path)

        # Default: return the original HTTP error as JSON instead of
        # re-raising (which Starlette converts to 500).
        return JSONResponse(
            status_code=_exc.status_code,
            content={"detail": _exc.detail},
        )

    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="static")
