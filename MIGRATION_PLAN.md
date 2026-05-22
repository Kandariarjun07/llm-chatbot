# SQLite → Supabase Migration Plan

## 1. Current Local Storage Audit

| Component | File(s) | Storage Type | Needs Migration |
|-----------|---------|--------------|-----------------|
| Chat conversations | `app/db.py` → `conversations` table | SQLite | ✅ Yes |
| User OTP verification | `app/db.py` → `user_verifications` table | SQLite | ✅ Yes |
| Architecture diagrams | `app/db.py` → `diagrams` table | SQLite | ✅ Yes |
| User custom instructions | `app/preferences.py` → `data/user_preferences.json` | Local JSON | ✅ Yes |
| AI Credits spend tracker | `app/aicredits_tracker.py` → `workspace/aicredits_spend.json` | Local JSON | ✅ Yes |
| Workspace files (uploads, chunks, vectors, parquet) | `app/workspace.py` → `workspace/` | Local filesystem | ✅ Yes |
| RAG vector index | `data/embedding_rag.py` → `.rag_index/context_vectors.json` | Local JSON | ⚠️ Regeneratable |
| Telemetry logs | `app/config.py` → `logs/chat_telemetry.jsonl` | Local file | ❌ Disable / stdout |
| Static RAG docs | `data/rag.py` → `data/docs.json`, `data/sample.json` | Static config | ❌ No |

---

## 2. Target Architecture (Supabase)

```
┌─────────────────────────────────────────────────────────────┐
│                     Hosting (Render / Fly.io)               │
│  ┌─────────────────┐    ┌─────────────────────────────────┐ │
│  │  React Frontend │    │      FastAPI Backend            │ │
│  │   (static)      │    │  ┌──────────────────────────┐   │ │
│  └─────────────────┘    │  │  PostgreSQL via asyncpg  │   │ │
│                         │  │  ───────────────────────  │   │ │
│                         │  │  • conversations          │   │ │
│                         │  │  • diagrams               │   │ │
│                         │  │  • user_verifications     │   │ │
│                         │  │  • user_preferences       │   │ │
│                         │  │  • aicredits_spend        │   │ │
│                         │  └──────────────────────────┘   │ │
│                         │                                 │ │
│                         │  ┌──────────────────────────┐   │ │
│                         │  │  Firebase Storage        │   │ │
│                         │  │  (already configured)    │   │ │
│                         │  │  ───────────────────────  │   │ │
│                         │  │  • upload raw files      │   │ │
│                         │  │  • PDF chunks             │   │ │
│                         │  │  • FAISS vectors          │   │ │
│                         │  │  • Excel parquet          │   │ │
│                         │  └──────────────────────────┘   │ │
│                         └─────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │    Supabase         │
                    │  ┌───────────────┐  │
                    │  │  PostgreSQL   │  │
                    │  │  (Structured) │  │
                    │  └───────────────┘  │
                    │                     │
                    │  ┌───────────────┐  │
                    │  │    Storage    │  │  ← Optional backup
                    │  │  (Object)     │  │
                    │  └───────────────┘  │
                    └─────────────────────┘
```

---

## 3. PostgreSQL Schema Design

### 3.1 `conversations`
```sql
CREATE TABLE conversations (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    title           TEXT NOT NULL DEFAULT 'New conversation',
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL,
    messages        JSONB NOT NULL DEFAULT '[]'
);

CREATE INDEX idx_conversations_user ON conversations(user_id);
CREATE INDEX idx_conversations_updated ON conversations(updated_at DESC);
```

### 3.2 `diagrams`
```sql
CREATE TABLE diagrams (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    title           TEXT NOT NULL DEFAULT 'Untitled Diagram',
    diagram_type    TEXT NOT NULL DEFAULT 'flowchart',
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL,
    nodes           JSONB NOT NULL DEFAULT '[]',
    edges           JSONB NOT NULL DEFAULT '[]',
    mermaid_code    TEXT NOT NULL DEFAULT '',
    metadata        JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_diagrams_user ON diagrams(user_id);
CREATE INDEX idx_diagrams_updated ON diagrams(updated_at DESC);
```

### 3.3 `user_verifications`
```sql
CREATE TABLE user_verifications (
    user_id         TEXT PRIMARY KEY,
    otp_verified    BOOLEAN NOT NULL DEFAULT FALSE
);
```

### 3.4 `user_preferences`
```sql
CREATE TABLE user_preferences (
    user_id         TEXT PRIMARY KEY,
    instructions    TEXT NOT NULL DEFAULT ''
);
```

### 3.5 `aicredits_spend` (single-row global counter)
```sql
CREATE TABLE aicredits_spend (
    id              SERIAL PRIMARY KEY,  -- always 1
    total_inr       NUMERIC(12, 6) NOT NULL DEFAULT 0.0,
    prompt_tokens   INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    calls           INTEGER NOT NULL DEFAULT 0,
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Seed with initial row
INSERT INTO aicredits_spend (id, total_inr) VALUES (1, 0.0);
```

---

## 4. File-by-File Code Changes

### 4.1 `requirements.txt`
**Add:**
```
# Database
asyncpg>=0.29.0
sqlalchemy[asyncio]>=2.0.0

# Supabase (optional — only if using Storage/Auth APIs)
supabase>=2.0.0
```

### 4.2 `app/config.py`
**Add new env vars:**
```python
# Supabase PostgreSQL direct connection
supabase_db_url: str | None = Field(default=None)
# Or individual components
supabase_host: str | None = Field(default=None)
supabase_port: int = Field(default=5432)
supabase_db_name: str | None = Field(default=None)
supabase_db_user: str | None = Field(default=None)
supabase_db_password: str | None = Field(default=None)
```

### 4.3 `app/db.py` — COMPLETE REWRITE

**Current:** sqlite3 + local file
**Target:** SQLAlchemy async ORM with PostgreSQL

```python
# New structure:
# - Database engine + async session factory
# - Same function signatures (get_conversations, upsert_conversation, etc.)
# - Internally uses asyncpg via SQLAlchemy
# - Falls back to SQLite if SUPABASE_DB_URL not set (dev mode)
```

**Functions to port (same signatures, async internals):**
- `get_conversations(user_id)` → async SQL query
- `upsert_conversation(user_id, conv)` → INSERT ... ON CONFLICT
- `delete_conversation(user_id, conv_id)` → DELETE + RETURNING
- `clear_conversations(user_id)` → DELETE
- `is_user_verified(user_id)` → SELECT
- `mark_user_verified(user_id)` → INSERT ... ON CONFLICT
- `get_diagrams(user_id)` → SELECT
- `get_diagram(user_id, diag_id)` → SELECT
- `upsert_diagram(user_id, diag)` → INSERT ... ON CONFLICT
- `delete_diagram(user_id, diag_id)` → DELETE

### 4.4 `api/chat_routes.py`
**Changes:**
- `list_history` already calls `await asyncio.to_thread(get_conversations, uid)` — keep the wrapper but `get_conversations` becomes async native
- All sync DB calls need `await`

### 4.5 `api/diagram_routes.py`
**Changes:**
- Same as chat_routes — wrap sync calls with async

### 4.6 `api/auth_routes.py`
**Changes:**
- `is_user_verified()` and `mark_user_verified()` become async
- Add `await` where called

### 4.7 `app/preferences.py` — REWRITE
**Current:** JSON file + optional Redis
**Target:** PostgreSQL table `user_preferences`

```python
# New structure:
# - get_custom_instructions(user_id) → SELECT instructions FROM user_preferences
# - set_custom_instructions(user_id, instructions) → INSERT ... ON CONFLICT UPDATE
# - Redis optional caching layer stays
```

### 4.8 `app/aicredits_tracker.py` — REWRITE
**Current:** JSON file with thread lock
**Target:** PostgreSQL row with atomic UPDATE

```python
# New structure:
# - get_spend() → SELECT FROM aicredits_spend WHERE id=1
# - record_usage() → UPDATE aicredits_spend SET ... WHERE id=1
# - reset() → UPDATE aicredits_spend SET total_inr=0...
# - Thread-safe because PostgreSQL row-level locking handles concurrency
```

### 4.9 `app/workspace.py` — STRATEGY DECISION NEEDED

**Option A: Firebase Storage (Recommended)**
- Already configured in `app/firebase_storage.py`
- Change workspace functions to upload/download from Firebase instead of local disk
- Chunks and vectors stored as objects

**Option B: Supabase Storage**
- New integration needed
- Similar to Firebase

**Option C: Keep local + mount volume (not true cloud)**
- Render/Fly persistent disk
- Not truly "online" data

**Recommendation: Option A** — expand Firebase Storage usage.

### 4.10 `data/embedding_rag.py` — NO CHANGE NEEDED
- `.rag_index/context_vectors.json` can be regenerated on deploy
- Set `RAG_USE_EMBEDDINGS=true` + `GEMINI_API_KEY` → auto-builds on first request

### 4.11 Telemetry (`app/config.py`, telemetry module)
- Set `TELEMETRY_FILE_ENABLED=false`
- Keep `CLOUD_LOGGING_ENABLED=true` (stdout)
- Optionally create `telemetry` table in Supabase for structured events

---

## 5. SQLite ↔ PostgreSQL Type Mapping

| SQLite | PostgreSQL | Notes |
|--------|-----------|-------|
| `TEXT PRIMARY KEY` | `TEXT PRIMARY KEY` | Same |
| `TEXT` | `TEXT` | Same |
| `REAL` (timestamp) | `TIMESTAMP WITH TIME ZONE` | Use `datetime.utcnow()` → `timezone.utc` aware |
| `TEXT` (JSON) | `JSONB` | PostgreSQL native JSON indexing |
| `INTEGER` (0/1 bool) | `BOOLEAN` | Use `True`/`False` in Python |
| `INSERT ... ON CONFLICT` | `INSERT ... ON CONFLICT` | Same syntax! |

---

## 6. Data Migration Strategy

### Step 1: Export existing SQLite data
```python
# One-time script: scripts/export_sqlite.py
import sqlite3, json

conn = sqlite3.connect("path/to/chat_history.db")
conn.row_factory = sqlite3.Row

# Export conversations
cursor = conn.execute("SELECT * FROM conversations")
conversations = [dict(row) for row in cursor.fetchall()]
with open("migrate_conversations.json", "w") as f:
    json.dump(conversations, f)

# Export diagrams
cursor = conn.execute("SELECT * FROM diagrams")
diagrams = [dict(row) for row in cursor.fetchall()]
with open("migrate_diagrams.json", "w") as f:
    json.dump(diagrams, f)

# Export user_verifications
cursor = conn.execute("SELECT * FROM user_verifications")
verifications = [dict(row) for row in cursor.fetchall()]
with open("migrate_verifications.json", "w") as f:
    json.dump(verifications, f)
```

### Step 2: Import into Supabase
```python
# scripts/import_to_supabase.py
import asyncio, json
from app.db_postgres import async_session

async def import_conversations():
    with open("migrate_conversations.json") as f:
        data = json.load(f)
    async with async_session() as session:
        for row in data:
            # INSERT into PostgreSQL
            pass
```

### Step 3: Firebase Storage migration for workspace files
- Upload existing `workspace/` contents to Firebase Storage bucket
- Update file paths in any DB records

---

## 7. Supabase Setup Steps

1. Go to https://supabase.com
2. Create project (free tier: 500MB DB + 1GB file storage)
3. In Settings → Database → copy **Connection string** (URI format)
4. Set env var: `SUPABASE_DB_URL=postgresql://...`
5. Open SQL Editor → run schema DDL (tables above)
6. (Optional) Enable RLS policies on tables if using Supabase Auth

---

## 8. Environment Variables (New)

```bash
# Required
SUPABASE_DB_URL=postgresql://postgres.xxxxx:password@aws-0-ap-south-1.pooler.supabase.com:5432/postgres

# Or individual (if direct connection preferred)
SUPABASE_HOST=aws-0-ap-south-1.pooler.supabase.com
SUPABASE_DB_NAME=postgres
SUPABASE_DB_USER=postgres.xxxxx
SUPABASE_DB_PASSWORD=your-db-password

# Existing vars (keep as-is)
FIREBASE_PROJECT_ID=...
FIREBASE_WEB_API_KEY=...
FIREBASE_STORAGE_BUCKET=...
GROQ_API_KEY=...
GEMINI_API_KEY=...

# Optional tweaks
TELEMETRY_FILE_ENABLED=false
DATA_DIR=  # clear out, not needed with Supabase
```

---

## 9. Implementation Phases

### Phase 1: Foundation (1–2 hours)
- [ ] Add `asyncpg` + `sqlalchemy[asyncio]` to `requirements.txt`
- [ ] Create `app/db_postgres.py` with engine + session factory
- [ ] Create `app/models.py` with SQLAlchemy table definitions
- [ ] Add env vars to `app/config.py`

### Phase 2: Structured Data Migration (2–3 hours)
- [ ] Rewrite `app/db.py` to use PostgreSQL (keep same function signatures)
- [ ] Update `api/chat_routes.py` to await DB calls
- [ ] Update `api/diagram_routes.py` to await DB calls
- [ ] Update `api/auth_routes.py` to await verification calls
- [ ] Test locally with local PostgreSQL (or Supabase)

### Phase 3: JSON Files → PostgreSQL (1–2 hours)
- [ ] Rewrite `app/preferences.py` → `user_preferences` table
- [ ] Rewrite `app/aicredits_tracker.py` → `aicredits_spend` table
- [ ] Test preference read/write

### Phase 4: Workspace → Firebase Storage (3–4 hours)
- [ ] Audit `app/workspace.py` — which functions read/write files
- [ ] Create Firebase Storage upload/download helpers
- [ ] Port chunk storage, vector storage, parquet storage
- [ ] Test file upload → process → chat flow end-to-end

### Phase 5: Data Migration + Deploy (1–2 hours)
- [ ] Export SQLite data
- [ ] Import into Supabase
- [ ] Upload existing workspace files to Firebase Storage
- [ ] Deploy to Render / Fly.io
- [ ] Verify with friends

---

## 10. Risk Mitigation

| Risk | Mitigation |
|------|------------|
| PostgreSQL syntax different from SQLite | Test each query; `ON CONFLICT` syntax is same |
| Async/await mismatch | Keep `asyncio.to_thread()` wrapper initially, then refactor |
| Workspace file sizes (FAISS indexes) | Firebase Storage has 5GB free per project — plenty |
| Data loss during migration | Keep SQLite backup; migration is idempotent |
| Supabase free tier limits (500MB) | 2-3 users ka data easily fits; ~50MB/chat for text |
| Connection pool exhaustion | SQLAlchemy `AsyncSession` handles pooling automatically |

---

## 11. Effort Estimate

| Phase | Time |
|-------|------|
| Phase 1 (Foundation) | 1–2 hrs |
| Phase 2 (DB Layer) | 2–3 hrs |
| Phase 3 (Preferences/Credits) | 1–2 hrs |
| Phase 4 (Workspace Files) | 3–4 hrs |
| Phase 5 (Migrate + Deploy) | 1–2 hrs |
| **Total** | **~10–13 hours** |

This is a significant refactor. The biggest chunk is **Phase 4** (workspace files to Firebase) because file I/O paths are deeply embedded in the multimodal/chat pipeline.

---

## 12. Simpler Alternative (Partial Migration)

If 10+ hours sounds like too much, consider this **80/20 approach**:

1. **Keep SQLite** but mount it as a persistent volume on Fly.io / Render
2. **Keep workspace/** on persistent volume
3. **Only move** `user_preferences` + `aicredits` to Supabase (tiny tables, <1 hr work)
4. **Result:** Data survives across deploys and instances, but still tied to one backend instance

**Trade-off:** Not truly "online" in the sense that multiple backend replicas can't share data, but for a single-instance deployment with friends, it's perfectly fine.

---

**Ready to proceed?** Let me know which approach you prefer — full Supabase migration, or the simpler persistent-volume route.
