# Memory: LLM Chatbot Progress & Architecture

## 1. Current Goal
Audit and optimize the full-stack LLM Chatbot application, covering chat retrieval performance (on-demand history loading), Sheets natural-language querying & export bug fixes, and stunning glassmorphic frontend UI enhancements.

## 2. Tech Decisions & Architecture
* **Dual Database Support**: Parallel DB logic for SQLite (development/fallback) and PostgreSQL/Supabase (production on Render). Unified `get_conversations` and `get_conversation` wrappers in `app/db.py` route dynamically using `_USE_PG`.
* **Metadata-Only Retrieval**: Optimized initial loading by retrieving only chat metadata (id, title, timestamps) on login, leaving the `messages` array empty (`[]`). This speeds up initial page load dramatically.
* **On-Demand Message Fetching**: The frontend now checks if a conversation's messages are empty on activation, and dynamically fetches details in the background using `GET /history/{id}` to hydrate the Zustand store on-demand.
* **Split-Workspace Layout for Sheets**: Refactored `Sheets.tsx` into a responsive split-workspace CSS layout (desktop: 35/65 split) where the database schema and sample rows stick to the left, and the AI composer and results occupy the right pane.
* **Fast Startups & Token Verification**: Deferring Firebase Admin SDK initialization to runtime completely eliminates the 10-second blocking Google credentials metadata query on startup. Converting the auth dependency to `async def` and implementing in-flight request deduplication collapses parallel login/navigation requests down to a single network call.
* **SMTP over SSL (Port 465) for Render**: Added a robust secure email transport (`_IPv4SMTP_SSL`) that forces IPv4 resolution to prevent timeouts and handles port 465 SSL handshakes natively.
* **Resend HTTP API Integration**: Since cloud hosts like Render frequently block all standard SMTP outbound ports (25, 465, 587) by default on free tier accounts, we implemented a robust HTTP API fallback using Resend (`https://api.resend.com/emails`) on port 443. This is never blocked and delivers directly to Gmail reliably.

## 3. Pending Tasks
* **Verification on Render**: Update environment variables in Render to set either `RESEND_API_KEY` (highly recommended for ports blocked by Render) or configure standard SMTP (using port 465 and `SMTP_TLS=false`).

## 4. Known Bugs & Gotchas
* **JSX Comment Mismatches**: Trailing comments (e.g. `{/* end sheets-split-workspace */}`) outside of JSX tags but inside JavaScript block expressions cause TS1005 syntax errors because they are parsed in standard JavaScript context rather than JSX child context. Do not write JSX comments after closing tags in curly brace conditionals.
* **Port 587 Restrictions**: Outbound ports 25 and 587 are blocked on Render. Always use port 465 with SSL for Render deployments.
