# SNTI AI Assistant

A full-stack conversational AI platform I built that delivers real-time streaming responses, live web search, deep research, multimodal file analysis, and enterprise-grade safety guardrails. It supports multiple LLM providers, Firebase authentication, and a polished React interface that feels like ChatGPT but with research superpowers.

---

## What I Built

I wanted a single AI assistant that could do everything — fast casual chat, deep research with live web search, PDF/document analysis, spreadsheet analytics, and image generation — all in one clean interface. So I built this.

### Key Features

- **Real-time streaming** — Native async SSE streaming from Groq/Gemini with sub-second first-token latency and no proxy buffering
- **Dual chat modes** — **Fast** (Llama 3.1 instant) for quick answers, **Think** (GPT-OSS 120B) for reasoning-heavy tasks
- **Live web search** — Query expansion + multi-provider search (Serper, Bing, Brave, DDGS, Tavily) with intelligent reranking
- **Deep research** — Multi-step research pipeline that breaks queries into sub-questions, searches across engines, and synthesizes comprehensive answers
- **Multimodal support** — Upload PDFs, images, CSVs, Excel files; the AI reads, analyzes, and answers questions about them
- **Safety guardrails** — PII redaction, prompt validation, output moderation, and reference checking built into every request
- **Firebase auth** — Secure email/password auth with OTP verification, refresh tokens, and role-based data access
- **Image generation** — Server-side proxy to image generation APIs (keys never exposed to browser)
- **Multilingual** — Automatic language detection with per-user preference persistence
- **Conversation persistence** — SQLite-backed chat history with debounced sync to prevent backend flooding
- **Rate limiting** — Per-user per-minute and per-day quotas with Redis or in-memory fallback

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.11, FastAPI, Uvicorn (async) |
| **Frontend** | React 18, TypeScript, Vite, Tailwind CSS, Zustand |
| **LLMs** | Groq (Llama 3.1, GPT-OSS 120B), Gemini API, Vertex AI |
| **Search** | Serper, DuckDuckGo (`ddgs`), Bing, Brave, Tavily, Reddit, HN, StackExchange, Wikipedia |
| **Auth** | Firebase Authentication (Admin SDK + REST fallback) |
| **Database** | SQLite (conversations), JSON file (preferences), optional Redis |
| **RAG** | Sentence-Transformers embeddings, TF-IDF + cosine similarity, optional BigQuery |
| **File Processing** | PyPDF2, pdf2image, Pillow, pandas, openpyxl, pyarrow |
| **Telemetry** | JSONL file logging, optional Google Cloud Logging + BigQuery |
| **Deployment** | Docker, Uvicorn single-worker (dev) / multi-worker (prod) |

---

## Prerequisites

- **Python 3.11+** — [Download](https://www.python.org/downloads/)
- **Node.js 18+** — [Download](https://nodejs.org/)
- **Git** — for cloning
- **API Keys** (free tiers available):
  - [Groq](https://console.groq.com/) — for Llama and GPT-OSS models
  - [Gemini](https://aistudio.google.com/app/apikey) — for Gemini fallback
  - [Firebase](https://console.firebase.google.com/) — for authentication
  - Optional: [Serper](https://serper.dev/), [Brave](https://brave.com/search/api/), [Tavily](https://tavily.com/) — for premium search

---

## Setup Instructions

### 1. Clone the repo

```bash
git clone https://github.com/kandariarjun07/llm-chatbot.git
cd llm-chatbot
```

### 2. Set up the backend

```bash
# Create virtual environment
python -m venv .venv

# Windows
.\.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt
```

### 3. Set up the frontend

```bash
cd frontend
npm install
cd ..
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your API keys. The **minimum required** keys are:

```env
# LLM Providers (need at least one)
GROQ_API_KEY=your_groq_api_key
GEMINI_API_KEY=your_gemini_api_key

# Firebase Authentication
FIREBASE_WEB_API_KEY=your_firebase_web_api_key
FIREBASE_PROJECT_ID=your_firebase_project_id

# App Settings
AUTH_PROVIDER=firebase
```

Optional — for premium search and features:

```env
# Search APIs (all optional — falls back to DuckDuckGo)
SERPER_API_KEY=your_serper_key
BING_API_KEY=your_bing_key
BRAVE_API_KEY=your_brave_key
TAVILY_API_KEY=your_tavily_key

# Redis (optional — uses in-memory fallback if not set)
REDIS_HOST=localhost
REDIS_PORT=6379

# BigQuery (optional — for production telemetry)
GCP_PROJECT_ID=your_gcp_project
```

See `.env.example` for the full list of configuration options.

### 5. Run the application

The easiest way is using the provided batch script:

```bash
# Windows — opens two separate terminal windows
.\run.bat
```

Or manually in two terminals:

```bash
# Terminal 1 — Backend API (http://127.0.0.1:8000)
uvicorn api.main:app --reload --port 8000
```

```bash
# Terminal 2 — Frontend (http://localhost:5173)
cd frontend
npm run dev
```

Open your browser to **http://localhost:5173** and sign up / log in.

---

## Architecture

```
┌─────────────────┐      SSE / REST / WS      ┌─────────────────────┐
│   React 18      │ ◄──────────────────────► │     FastAPI         │
│   TypeScript      │                         │   (Async/Uvicorn)    │
│   Vite + Tailwind │                         │                     │
│   Zustand State   │                         │  • Auth (Firebase)   │
└─────────────────┘                         │  • Orchestrator      │
                                            │  • Rate Limits       │
                                            │  • Streaming SSE   │
                                            └─────────────────────┘
                                                        │
                    ┌─────────────┬─────────────┬──────┴──────┬──────────────┐
                    ▼             ▼             ▼             ▼              ▼
              ┌─────────┐   ┌──────────┐   ┌─────────┐   ┌─────────┐   ┌──────────┐
              │ Groq    │   │ Search   │   │  RAG    │   │ Guard-  │   │ Telemetry│
              │ Llama   │   │ Providers│   │ (SQLite │   │ rails   │   │ (JSONL/  │
              │ GPT-OSS │   │ Serper   │   │ + Embeds│   │ PII/    │   │ BigQuery)│
              │ Gemini  │   │ DDGS/etc │   │ + BQ)   │   │ Validate│   │          │
              └─────────┘   └──────────┘   └─────────┘   └─────────┘   └──────────┘
```

### How a request flows

1. **Authentication** — Every request carries a Firebase ID token. The backend verifies it locally (cached for 5 min) or falls back to Firebase REST.
2. **PII Redaction** — Emails, phone numbers, and API keys are stripped from the query before any LLM sees it.
3. **Intent Analysis** — The system decides if the query needs web search, deep research, file analysis, or a simple chat answer.
4. **Context Building** — Relevant documents are retrieved via RAG (embeddings or TF-IDF), and web search results are injected into the prompt.
5. **Model Selection** — The orchestrator routes "Fast" mode to Llama (cheap, fast) and "Think" mode to GPT-OSS 120B (reasoning-heavy).
6. **Streaming** — Tokens are streamed via native async generators (AsyncGroq) directly to the frontend with no thread blocking.
7. **Guardrails** — The response is checked for hallucinations, missing references, and unsafe content before delivery.

---

## Project Structure

```
llm-chatbot/
├── api/                          # FastAPI route modules
│   ├── main.py                   # App entrypoint, middleware, streaming endpoint
│   ├── auth_routes.py            # Login, signup, OTP, token refresh, me
│   ├── chat_routes.py            # Conversation CRUD (SQLite)
│   ├── multimodal_routes.py      # PDF RAG, image vision, spreadsheet analytics
│   ├── upload_routes.py          # File upload with background processing
│   ├── sheets_routes.py          # Spreadsheet SQL query + export
│   ├── images_routes.py          # Image generation proxy
│   └── transcribe_routes.py      # Audio transcription
│
├── app/                          # Core business logic
│   ├── orchestrator.py           # Main pipeline: guardrails → routing → streaming
│   ├── model_routing.py          # Auto / explicit model selection logic
│   ├── mode_routing.py           # Fast / Think mode mapping
│   ├── guardrails.py             # PII redaction, prompt validation, moderation
│   ├── rate_limits.py            # Per-user rate limiting (Redis + memory)
│   ├── search_providers/         # Pluggable search backends
│   ├── deep_research.py          # Multi-step research pipeline
│   ├── tools_web_search.py       # Web search with query expansion
│   ├── chunker.py                # Text chunking for embeddings
│   ├── embedding_manager.py      # Vector store for PDF RAG
│   ├── pdf_processor.py          # PDF text + image extraction
│   ├── excel_processor.py        # Spreadsheet parsing + SQL analytics
│   ├── vision_pipeline.py        # Gemini Vision for images/PDFs
│   ├── workspace.py              # File storage paths + quota management
│   ├── db.py                     # SQLite conversation persistence
│   ├── preferences.py            # User custom instructions
│   ├── config.py                 # Pydantic settings with env var loading
│   └── telemetry.py              # Chat event logging
│
├── data/                         # RAG documents + SQLite DB
│   ├── rag.py                    # TF-IDF context retrieval
│   ├── embedding_rag.py          # Vector-based context retrieval
│   ├── docs.json                 # Default knowledge base
│   ├── sample.json               # Sample documents
│   └── chat_history.db           # SQLite DB (auto-created, gitignored)
│
├── frontend/                     # React SPA
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Chat.tsx          # Main chat UI with streaming
│   │   │   ├── Login.tsx         # Auth (login/signup/OTP)
│   │   │   ├── Sheets.tsx        # Spreadsheet analytics UI
│   │   │   ├── Images.tsx        # Image generation UI
│   │   │   ├── Usage.tsx         # Quota + storage dashboard
│   │   │   └── Settings.tsx      # User preferences
│   │   ├── components/
│   │   │   ├── Layout.tsx        # Sidebar + navigation + conversation list
│   │   │   ├── ThemeToggle.tsx   # Dark/light mode switch
│   │   │   └── ErrorBoundary.tsx # React error boundaries
│   │   ├── store/
│   │   │   ├── chatStore.ts      # Zustand: conversations, streaming state
│   │   │   ├── authStore.ts      # Zustand: user, tokens, logout
│   │   │   └── themeStore.ts     # Zustand: dark/light mode
│   │   ├── lib/
│   │   │   └── api.ts            # Axios + fetch API client (streaming)
│   │   ├── index.css             # Tailwind + CSS variables
│   │   └── main.tsx              # React entrypoint
│   └── vite.config.ts            # Vite proxy config for /api
│
├── llm/                          # LLM provider clients
│   ├── client.py                 # Unified sync + async streaming clients
│   └── circuit_breaker.py        # Circuit breaker for LLM failures
│
├── prompts/                      # Prompt templates
│   ├── compose.py                # Prompt builder functions
│   ├── manager.py                # Template registry
│   ├── formatters.py             # Context snippet formatters
│   ├── system.py                 # System role prompts
│   └── tools.py                  # Tool selection prompts
│
├── .env.example                  # Full configuration reference
├── requirements.txt              # Python dependencies
├── run.bat                       # Windows launcher (backend + frontend)
└── Dockerfile                    # Container build
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/auth/signup` | POST | Register with email + password |
| `/api/auth/signin` | POST | Login (returns ID + refresh token) |
| `/api/auth/verify-otp` | POST | Verify email OTP |
| `/api/auth/refresh` | POST | Refresh expired ID token |
| `/api/auth/me` | GET | Current user profile |
| `/api/chat` | POST | Standard (non-streaming) chat |
| `/api/chat/stream` | POST | **Streaming chat (SSE)** |
| `/api/chat/history` | GET/POST/DELETE | Conversation CRUD |
| `/api/chat/multimodal` | POST | File-based chat (PDF, image, spreadsheet) |
| `/api/limits` | GET | Rate limit quota status |
| `/api/upload` | POST | Upload files to a chat |
| `/api/upload/files/{chat_id}` | GET | List uploaded files |
| `/api/sheets/query` | POST | Natural language → SQL |
| `/api/sheets/export` | POST | Export query results to Excel |
| `/api/images/generate` | POST | Generate images |
| `/health` | GET | Health check |

---

## Development

### Backend structure

Every request goes through the orchestrator pipeline in `app/orchestrator.py`:

1. **Guardrails** (`guardrails.py`) — PII redaction + prompt validation
2. **Tool decision** (`tools.py`) — Calculator, file analyzer, or chat
3. **Search intent** (`tools_web_search.py`) — Should we search the web?
4. **Context retrieval** (`data/rag.py` or `embedding_rag.py`) — Find relevant docs
5. **Model routing** (`model_routing.py`) — Pick the right model for cost/speed
6. **LLM call** (`llm/client.py`) — Stream tokens back via async generators
7. **Post-processing** — Reference checking, output moderation, telemetry logging

### Adding a new search provider

1. Create `app/search_providers/<name>_provider.py`
2. Inherit from `SearchProvider` and implement `search()` and `is_available()`
3. Register in `app/search_providers/_registry.py`
4. Add `<NAME>_API_KEY` to `.env`

### Running checks

```bash
# Syntax check
python -m py_compile api/main.py app/orchestrator.py

# Test streaming endpoint directly
curl -N -X POST http://127.0.0.1:8000/chat/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your_token>" \
  -d '{"query": "Hello", "mode": "Fast"}'
```

---

## Performance Optimizations I Implemented

- **Auth caching** — Firebase token verification results cached in-memory for 5 minutes (eliminated ~12s delay per request)
- **Async streaming** — Native `AsyncGroq` client with no per-token thread context switches
- **Proxy bypass** — Streaming fetches connect directly to the backend, bypassing Vite proxy buffering
- **Debounced sync** — Conversation saves debounced at 800ms to prevent flooding SQLite during streaming
- **Plain text during streaming** — ReactMarkdown is skipped while streaming; raw text renders instantly
- **Memoized MessageBubble** — `React.memo` prevents unnecessary re-renders on every token
- **Anti-buffering headers** — `X-Accel-Buffering: no` + `Cache-Control: no-cache` on all SSE responses

---

## Security

- **No API keys in frontend** — All LLM and search API calls happen server-side
- **Firebase token validation** — Every request verified via Firebase Admin SDK with REST fallback
- **PII redaction** — Emails, phone numbers, API keys stripped before LLM processing
- **Prompt validation** — Blocked topic patterns prevent misuse
- **Rate limiting** — Per-user per-minute and per-day limits with descriptive 429 responses
- **Secure file uploads** — Type validation, size limits, quota enforcement

---

## License

MIT — feel free to fork, modify, and build on top of this.
