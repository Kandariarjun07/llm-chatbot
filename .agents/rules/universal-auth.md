---
trigger: always_on
---

# Universal Auth Sentinel (Firebase Stack)

## Context
- Frontend: React (Vite/CRA)
- Backend: Python (FastAPI/Flask/Django)
- Identity: Firebase Authentication

## Audit Logic
1. Scan `.py` files for `firebase_admin.auth.verify_id_token`. If missing, flag as "Critical Vulnerability".
2. Check `firebase.js` in React for proper environment variable usage.
3. Check `firestore.rules` for `request.auth != null`.

## Build Logic
1. Scaffold Firebase Client in React using `firebase/auth`.
2. Generate Python Middleware to extract UID from Bearer tokens.
3. Link Python UID to Firebase UID for user-specific chat data.
