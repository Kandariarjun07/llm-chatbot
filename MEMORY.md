# Memory: LLM Chatbot Progress & Architecture

## 1. Current Goal
Audit and optimize the full-stack LLM Chatbot application, covering chat retrieval performance (on-demand history loading), Sheets natural-language querying & export bug fixes, and stunning glassmorphic frontend UI enhancements.

## 2. Tech Decisions & Architecture
* **Dual Database Support**: Parallel DB logic for SQLite (development/fallback) and PostgreSQL/Supabase (production on Render). Unified `get_conversations` and `get_conversation` wrappers in `app/db.py` route dynamically using `_USE_PG`.
* **Metadata-Only Retrieval**: Optimized initial loading by retrieving only chat metadata (id, title, timestamps) on login, leaving the `messages` array empty (`[]`). This speeds up initial page load dramatically.
* **On-Demand Message Fetching**: The frontend now checks if a conversation's messages are empty on activation, and dynamically fetches details in the background using `GET /history/{id}` to hydrate the Zustand store on-demand.
* **Split-Workspace Layout for Sheets**: Refactored `Sheets.tsx` into a responsive split-workspace CSS layout (desktop: 35/65 split) where the database schema and sample rows stick to the left, and the AI composer and results occupy the right pane.

## 3. Pending Tasks
* **Verification**: Wait for the background `npm run build` process to finish. Verify if the syntax error in `Sheets.tsx` is completely resolved and the app compiles successfully.
* **Task Tracker & Walkthrough**: Mark off items in the `task.md` and create a `walkthrough.md` to document the completed visual and performance enhancements.

## 4. Known Bugs & Gotchas
* **JSX Comment Mismatches**: Trailing comments (e.g. `{/* end sheets-split-workspace */}`) outside of JSX tags but inside JavaScript block expressions cause TS1005 syntax errors because they are parsed in standard JavaScript context rather than JSX child context. Do not write JSX comments after closing tags in curly brace conditionals.
