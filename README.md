# LLM Chatbot

A production-grade conversational AI interface with real-time web search, multi-engine deep research, streaming responses, and enterprise-ready guardrails. Built with FastAPI and React.

---

## Features

- **Streaming responses** — Real-time SSE with typewriter-style delivery
- **Web search** — DuckDuckGo-powered live search with query expansion via LLM intent rewriting
- **Deep research** — Multi-engine aggregation (Bing, Brave, Tavily, DDGS) with deduplication and quality ranking
- **Model routing** — Automatic model selection (Groq Llama, Gemini API, Vertex AI) with fallback chains
- **Rate-limited premium features** — Weekly quota system for deep research with Redis/memorystore backend
- **Safety guardrails** — PII redaction, prompt validation, output moderation, and reference checking
- **RAG support** — TF-IDF + cosine similarity retrieval from JSON documents with optional BigQuery vector search
- **Firebase auth** — Email/password authentication with role-based data access control
- **Multilingual** — Auto language detection with translation support
- **Image generation** — Server-side proxy to Pollinations AI (key never exposed to browser)

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.10+, FastAPI, Uvicorn |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Zustand |
| LLMs | Groq (Llama), Gemini API, Vertex AI Gemini |
| Search | DuckDuckGo (`ddgs`), Bing API, Brave API, Tavily API |
| Cache | Redis or in-memory fallback |
| Auth | Firebase Authentication |
| Telemetry | Google Cloud Logging, optional BigQuery |
| Deployment | Docker, Cloud Build, GCR |

---

## Quick Start

### 1. Clone and setup

```bash
git clone <repo-url>
cd llm-chatbot

# Create virtual environment
python -m venv .venv
. .venv/bin/activate  # Windows: .\.venv\Scripts\activate

# Install backend dependencies
pip install -r requirements.txt

# Install frontend dependencies
cd frontend && npm install && cd ..
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your keys (Groq, Gemini, Firebase, etc.)
```

**Minimum required variables:**

```env
GROQ_API_KEY=your_groq_key
GEMINI_API_KEY=your_gemini_key

AUTH_PROVIDER=firebase
FIREBASE_WEB_API_KEY=your_firebase_key
FIREBASE_PROJECT_ID=your_project
```

Optional — for premium search engines:

```env
BING_API_KEY=your_bing_key
BRAVE_API_KEY=your_brave_key
TAVILY_API_KEY=your_tavily_key
```

### 3. Run locally

```bash
# Terminal 1 — Backend
uvicorn api.main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend && npm run dev
```

The frontend proxies `/api` to `localhost:8000` via Vite config.

---

## Architecture

```
┌─────────────┐      SSE / REST       ┌─────────────────┐
│   React     │ ◄───────────────────► │    FastAPI      │
│  (Vite)     │                     │   Orchestrator  │
└─────────────┘                     └─────────────────┘
                                           │
              ┌────────────┬───────────────┼────────────┐
              ▼            ▼               ▼            ▼
         ┌────────┐   ┌─────────┐    ┌──────────┐  ┌─────────┐
         │  LLM   │   │ Search  │    │   RAG    │  │  Auth   │
         │ Router │   │Providers│    │  (JSON/  │  │Firebase │
         │ Groq/  │   │DDGS/Bing│    │ BigQuery)│  │ / OIDC  │
         │Gemini  │   │Brave/etc│    └──────────┘  └─────────┘
         └────────┘   └─────────┘
```

### Request Flow

1. **Auth** — Firebase token validated via `get_current_user`
2. **PII Redaction** — Sensitive patterns stripped before processing
3. **Tool Decision** — LLM decides if calculator, file analyzer, or chat is needed
4. **Query Expansion** — Vague queries rewritten into precise search terms via LLM
5. **Context Retrieval** — RAG + optional web search results injected into prompt
6. **Model Routing** — Auto-selects cheapest capable model based on token count/risk
7. **Streaming** — SSE chunks delivered to frontend as they're generated
8. **Guardrails** — Output moderated, references checked before final delivery

### Search Modes

| Mode | Engine | Rate Limit | Use Case |
|------|--------|-----------|----------|
| Web Search | DDGS only | Unlimited | Quick current info |
| Deep Research | All configured engines | 5/week/user | Comprehensive multi-source analysis |

---

## Project Structure

```
llm-chatbot/
├── api/                    # FastAPI routes (auth, chat, images, limits)
├── app/                    # Core business logic
│   ├── search_providers/   # Pluggable search backends
│   ├── rate_limits.py      # Weekly quota management
│   ├── orchestrator.py     # Main request pipeline
│   └── guardrails.py       # Safety filters
├── data/                   # RAG retrieval, BigQuery connectors
├── frontend/               # React SPA
│   ├── src/pages/Chat.tsx  # Main chat interface
│   └── src/lib/api.ts      # API client
├── llm/                    # LLM provider clients (Groq, Gemini)
├── prompts/                # Prompt templates and composition
├── .env.example            # Full configuration reference
└── requirements.txt        # Python dependencies
```

---

## Key Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chat` | POST | Synchronous chat |
| `/api/chat/stream` | POST | Streaming chat (SSE) |
| `/api/limits` | GET | Deep research quota status |
| `/api/images/generate` | POST | Image generation (proxied) |
| `/api/auth/me` | GET | Current user profile |

---

## Development

### Adding a new search provider

1. Create `app/search_providers/<name>_provider.py`
2. Inherit from `SearchProvider` and implement `search()` and `is_available()`
3. Import in `app/search_providers/_registry.py`
4. Set `<NAME>_API_KEY` in `.env`

### Running tests

```bash
# Backend syntax check
python -m py_compile app/orchestrator.py api/main.py

# Quick search test
python -c "from app.search_providers import search_all; print(search_all('latest tech news'))"
```

---

## License

MIT
