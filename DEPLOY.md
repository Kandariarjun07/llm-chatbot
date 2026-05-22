# Deployment Guide — SNTI AI Chatbot

This project now supports **two database backends** automatically:
- **SQLite** (local file, default) — works out of the box
- **PostgreSQL via Supabase** — set `SUPABASE_DB_URL` env var

The code detects which mode to use at startup. No code changes needed — just set (or unset) the env var.

---

## Option A: Cloudflare Tunnel (Fastest — 2 minutes, no signup)

Best for: **Immediate sharing with friends**. Your machine stays on, they access via a public URL.

### Prerequisites
- Backend already runs locally (`python -m uvicorn api.main:app --port 8000`)
- `cloudflared` installed

### Step 1: Install cloudflared (one-time)
```powershell
winget install --id Cloudflare.cloudflared
```

### Step 2: Start your backend
```powershell
cd c:\Users\arjun\OneDrive\Desktop\llm-chatbot
python -m uvicorn api.main:app --port 8000
```

### Step 3: Start the tunnel (new terminal)
```powershell
cd c:\Users\arjun\OneDrive\Desktop\llm-chatbot
deploy_tunnel.bat
```

Or manually:
```powershell
cloudflared tunnel --url http://localhost:8000
```

### Step 4: Share the URL
You'll see something like:
```
https://snti-chatbot-abc123.trycloudflare.com
```

Send this to your friends. They can:
- Sign up / log in
- Chat, create diagrams, upload files
- All data stays on **your machine** (SQLite + workspace files)

### Important Notes
- **Your machine must stay ON** — URL dies when you shut down
- URL changes every time you restart cloudflared (random subdomain)
- For a fixed URL, create a free Cloudflare account + named tunnel

---

## Option B: Supabase + Render / Fly.io (Persistent, scalable)

Best for: **Permanent deployment** — data lives in the cloud, accessible 24/7.

### Phase 1 — Supabase Setup (5 min)

1. Go to [https://supabase.com](https://supabase.com)
2. Create a project (free tier: 500 MB DB + 1 GB storage)
3. Open **Settings → Database → Connection string**
4. Copy the **URI** format string:
   ```
   postgresql://postgres.xxxxx:password@aws-0-ap-south-1.pooler.supabase.com:5432/postgres
   ```

### Phase 2 — Export existing local data (if you have chats/diagrams)

```powershell
cd c:\Users\arjun\OneDrive\Desktop\llm-chatbot
python scripts/export_sqlite.py
```

This creates:
```
scripts/migrations/conversations.json
scripts/migrations/diagrams.json
scripts/migrations/verifications.json
```

### Phase 3 — Import into Supabase

```powershell
# Windows PowerShell
$env:SUPABASE_DB_URL="postgresql://postgres.xxxxx:password@...:5432/postgres"
python scripts/import_to_supabase.py
```

This creates tables and imports your existing data.

### Phase 4 — Deploy Backend

#### Option B1: Render (Recommended, free tier)

1. Go to [https://render.com](https://render.com)
2. Sign up with GitHub (no credit card for free tier)
3. Create **New Web Service**
4. Connect your GitHub repo
5. Settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn api.main:app --host 0.0.0.0 --port $PORT`
   - **Plan:** Free
6. Add **Environment Variables**:
   ```
   SUPABASE_DB_URL=postgresql://...
   GROQ_API_KEY=your-key
   GEMINI_API_KEY=your-key
   FIREBASE_PROJECT_ID=your-project
   FIREBASE_WEB_API_KEY=your-key
   FIREBASE_STORAGE_BUCKET=your-bucket
   # ... add all other API keys from your .env
   ```
7. Click **Create Web Service**

**Important:** Render free tier sleeps after 15 min inactivity. To prevent cold starts, add a free UptimeRobot ping to `/health` every 5 minutes.

#### Option B2: Fly.io (Also free tier)

```powershell
# Install flyctl
iwr https://fly.io/install.ps1 -useb | iex

# Login
fly auth login

# Launch (uses existing fly.toml)
cd c:\Users\arjun\OneDrive\Desktop\llm-chatbot
fly deploy --app snti-chatbot

# Set secrets
fly secrets set SUPABASE_DB_URL="postgresql://..." GROQ_API_KEY="..."
```

**Note:** Fly.io requires a credit card for signup (even though free tier has no charges). If you don't want to provide a credit card, use **Render** or **Cloudflare Tunnel** instead.

### Phase 5 — Deploy Frontend

The backend already serves the built React app at `/` when `frontend/dist` exists. So no separate frontend deployment needed!

If you want the frontend on Vercel/Netlify (for faster global CDN):
1. Build: `cd frontend && npm run build`
2. Deploy `frontend/dist` folder to Vercel/Netlify
3. Set `VITE_API_URL=https://your-render-app.onrender.com` in Vercel env vars
4. Update Render's `CORS_ALLOW_ORIGINS` to include your Vercel domain

---

## Database Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  When SUPABASE_DB_URL is set → PostgreSQL (online, shared)   │
│  When NOT set → SQLite (local file)                        │
└─────────────────────────────────────────────────────────────┘

PostgreSQL Tables (auto-created):
  - conversations      (id, user_id, title, created_at, updated_at, messages JSONB)
  - diagrams           (id, user_id, title, diagram_type, created_at, updated_at, nodes, edges, mermaid_code, metadata JSONB)
  - user_verifications (user_id, otp_verified BOOLEAN)
  - user_preferences   (user_id, instructions TEXT)
  - aicredits_spend    (id, total_inr, prompt_tokens, completion_tokens, calls)

SQLite Tables (same schema, local file):
  - Same tables, stored at %LOCALAPPDATA%/SNTI/chat_history.db
```

---

## What Was Changed in the Code

| File | Change |
|------|--------|
| `requirements.txt` | Added `asyncpg`, `sqlalchemy[asyncio]` |
| `app/config.py` | Added `supabase_db_url` env var |
| `app/db_postgres.py` | **NEW** — SQLAlchemy async models + engine + all CRUD helpers |
| `app/db.py` | **REWRITTEN** — Unified async API, dispatches to PG or SQLite |
| `api/chat_routes.py` | All DB calls now `await` |
| `api/diagram_routes.py` | All DB calls now `await` |
| `api/auth_routes.py` | `signin` and `verify_otp` made async |
| `scripts/export_sqlite.py` | **NEW** — Export local SQLite to JSON |
| `scripts/import_to_supabase.py` | **NEW** — Import JSON into PostgreSQL |
| `deploy_tunnel.bat` | **NEW** — One-click Cloudflare Tunnel launcher |

---

## Migration from SQLite → Supabase (Summary)

```powershell
# 1. Export existing data
python scripts/export_sqlite.py

# 2. Set your Supabase connection string
$env:SUPABASE_DB_URL="postgresql://postgres.xxxxx:password@...:5432/postgres"

# 3. Import into Supabase
python scripts/import_to_supabase.py

# 4. Deploy backend with SUPABASE_DB_URL env var set
#    (Render dashboard → Environment Variables)
```

Your existing chats, diagrams, and user verification status will be preserved.

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'sqlalchemy'"
```powershell
pip install -r requirements.txt
```

### "SUPABASE_DB_URL is not configured" but I set it
Make sure it's set **before** importing `app.db`. In PowerShell:
```powershell
$env:SUPABASE_DB_URL="..."
```

### Cloudflare Tunnel URL not accessible
- Make sure backend is running on `http://localhost:8000`
- Check firewall isn't blocking outbound connections
- Try `cloudflared tunnel --url http://127.0.0.1:8000` instead

### Render deploy fails with "No module named 'xxx'"
- Ensure `requirements.txt` is committed to git
- Render auto-detects Python, but you can set:
  - **Runtime:** Python 3
  - **Build Command:** `pip install -r requirements.txt`

---

## Next Steps (Optional Future Improvements)

1. **Workspace files to Firebase Storage** — Currently workspace/ (uploads, chunks, vectors) stays on local disk. For true multi-instance deployment, migrate these to Firebase Storage.
2. **Preferences + AI Credits to PostgreSQL** — Currently still local JSON files. Low priority since they're tiny.
3. **Redis for OTP + rate limits** — For multi-worker deployments, set `REDIS_URL`.

---

Ready to deploy? Pick **Option A** for instant sharing, or **Option B** for permanent cloud hosting.
