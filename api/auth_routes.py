"""
Framework-free auth endpoints for the React frontend.
Wraps Firebase Identity Toolkit REST API. No Streamlit dependency.
"""
from __future__ import annotations

import os
import time
import random
import logging
import base64
from io import BytesIO
from typing import Any

import requests
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials

from app.preferences import get_custom_instructions, set_custom_instructions
from app.db import is_user_verified, mark_user_verified
from app.rate_limits import RateLimit, check_deep_research_limit
from app.workspace import user_storage_usage, MAX_QUOTA_BYTES
from app.config import get_settings
from app import otp_store

logger = logging.getLogger(__name__)

# ── In-memory auth cache ─────────────────────────────────────────
# Firebase ID tokens are valid for 1h.  We cache the verified result
# for 5 min so repeated requests in the same session don't pay the
# ~10-15 s network round-trip to Google's JWKS / identity servers.
# Production should use Redis; this is dev-friendly.
_AUTH_CACHE: dict[str, tuple[dict[str, Any], float]] = {}
_AUTH_CACHE_TTL = 300  # seconds

# Initialize Firebase Admin SDK
if not firebase_admin._apps:
    project_id = os.getenv("FIREBASE_PROJECT_ID")
    try:
        if project_id:
            firebase_admin.initialize_app(options={"projectId": project_id})
        else:
            firebase_admin.initialize_app()
    except Exception as e:
        logger.warning(f"Failed to initialize firebase_admin: {e}")

FIREBASE_AUTH_BASE_URL = "https://identitytoolkit.googleapis.com/v1"
FIREBASE_SECURE_TOKEN_URL = "https://securetoken.googleapis.com/v1/token"
ID_TOKEN_TTL = 3600

router = APIRouter(prefix="/auth", tags=["auth"])

OTP_TTL_SECONDS = 300          # 5 minutes
MAX_OTP_ATTEMPTS = 3           # wrong-code tries before expiry
OTP_THROTTLE_LIMIT = 3         # max sends per 15 min
OTP_THROTTLE_WINDOW = 900      # 15 minutes


def _otp_throttle_key(email: str) -> str:
    return f"otp_throttle:{email}"


def _check_otp_throttle(email: str) -> bool:
    """Return True if the email has NOT exceeded the send throttle."""
    from app.rate_limits import check_rate_limit
    key = _otp_throttle_key(email)
    result = check_rate_limit(key, OTP_THROTTLE_LIMIT, OTP_THROTTLE_WINDOW)
    return result.allowed


_LOGO_BYTES: bytes | None = None


def _logo_bytes() -> bytes | None:
    """Resize logo.jpeg to 80x80 and return raw JPEG bytes."""
    global _LOGO_BYTES
    if _LOGO_BYTES is not None:
        return _LOGO_BYTES

    from pathlib import Path
    try:
        from PIL import Image
    except ImportError:
        return None

    logo_path = Path(__file__).resolve().parent.parent / "frontend" / "assets" / "images" / "logo.jpeg"
    if not logo_path.exists():
        return None

    img = Image.open(logo_path)
    img = img.convert("RGB")
    img = img.resize((80, 80), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85, optimize=True)
    _LOGO_BYTES = buf.getvalue()
    return _LOGO_BYTES


def _send_otp_email(to: str, otp_code: str) -> bool:
    """Send the OTP via SMTP if configured. Returns True on success."""
    settings = get_settings()
    host = settings.smtp_host
    if not host:
        return False

    import smtplib
    import uuid
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.image import MIMEImage

    sender = settings.smtp_from or settings.smtp_user or "noreply@snti.ai"
    msg_root = MIMEMultipart("related")
    msg_root["Subject"] = "Your SNTI verification code"
    msg_root["From"] = sender
    msg_root["To"] = to
    msg_root["Message-Id"] = f"<{uuid.uuid4()}@snti.ai>"
    msg_root["MIME-Version"] = "1.0"
    msg_root["X-Mailer"] = "SNTI-Mail/1.0"
    msg_root["Precedence"] = "bulk"
    msg_root["Auto-Submitted"] = "auto-generated"

    # Plain-text fallback
    plain = f"""Your SNTI verification code is: {otp_code}

This code will expire in 5 minutes.
If you did not request this code, you can safely ignore this email.

— SNTI AI
"""

    logo_bytes = _logo_bytes()
    has_logo = logo_bytes is not None
    logo_html = '<img src="cid:logo" width="48" height="48" alt="SNTI" style="display:block;margin:0 auto;border-radius:10px;" />' if has_logo else '<div style="display:inline-block;width:48px;height:48px;background:#38bdf8;border-radius:10px;line-height:48px;color:#0f172a;font-weight:800;font-size:22px;text-align:center;">s</div>'

    # Modern HTML email (inline CSS for max client compatibility)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SNTI Verification</title>
</head>
<body style="margin:0;padding:0;background:#0f172a;font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#0f172a;">
    <tr>
      <td align="center" style="padding:48px 16px;">
        <table width="480" cellpadding="0" cellspacing="0" border="0" style="max-width:480px;width:100%;background:#1e293b;border-radius:16px;overflow:hidden;border:1px solid #334155;">
          <!-- Brand -->
          <tr>
            <td style="padding:40px 32px 24px 32px;text-align:center;">
              {logo_html}
              <div style="margin-top:12px;color:#f8fafc;font-size:18px;font-weight:700;letter-spacing:-0.5px;">snti<span style="color:#38bdf8;">.</span></div>
            </td>
          </tr>
          <!-- Heading -->
          <tr>
            <td style="padding:0 32px 8px 32px;text-align:center;">
              <h1 style="margin:0;color:#f8fafc;font-size:22px;font-weight:700;letter-spacing:-0.3px;">Verify your email</h1>
            </td>
          </tr>
          <tr>
            <td style="padding:0 32px 28px 32px;text-align:center;">
              <p style="margin:0;color:#94a3b8;font-size:14px;line-height:1.6;">Enter the code below to finish signing in. It expires in <strong style="color:#f8fafc;">5 minutes</strong>.</p>
            </td>
          </tr>
          <!-- OTP code -->
          <tr>
            <td style="padding:0 32px 20px 32px;text-align:center;">
              <p style="margin:0 0 12px 0;color:#64748b;font-size:11px;text-transform:uppercase;letter-spacing:2px;font-weight:600;">Your verification code</p>
              <div style="background:#0f172a;border:1px solid #334155;border-radius:12px;padding:22px 16px;text-align:center;">
                <div style="font-family:'SF Mono','Menlo','Consolas',monospace;font-size:36px;font-weight:700;letter-spacing:10px;color:#38bdf8;-webkit-user-select:all;-moz-user-select:all;-ms-user-select:all;user-select:all;cursor:copy;line-height:1;">{otp_code}</div>
              </div>
            </td>
          </tr>
          <!-- Copy hint button -->
          <tr>
            <td style="padding:0 32px 28px 32px;text-align:center;">
              <div style="display:inline-block;background:#38bdf8;color:#0f172a;padding:10px 22px;border-radius:8px;font-weight:700;font-size:12px;letter-spacing:1px;text-transform:uppercase;font-family:'Inter',-apple-system,sans-serif;">📋 Tap the code above to copy</div>
            </td>
          </tr>
          <!-- Didn't request? -->
          <tr>
            <td style="padding:0 32px 32px 32px;text-align:center;">
              <p style="margin:0;color:#64748b;font-size:12px;line-height:1.6;">Didn&apos;t request this? You can safely ignore it.</p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="padding:24px 32px;background:#0f172a;border-top:1px solid #334155;text-align:center;">
              <p style="margin:0;color:#475569;font-size:11px;line-height:1.5;">SNTI AI Assistant<br>Private &middot; Fast &middot; Yours</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    msg_alt = MIMEMultipart("alternative")
    msg_alt.attach(MIMEText(plain, "plain", "utf-8"))
    msg_alt.attach(MIMEText(html, "html", "utf-8"))
    msg_root.attach(msg_alt)

    if has_logo:
        img_part = MIMEImage(logo_bytes, _subtype="jpeg")
        img_part.add_header("Content-ID", "<logo>")
        img_part.add_header("Content-Disposition", "inline", filename="logo.jpeg")
        msg_root.attach(img_part)

    try:
        if settings.smtp_tls:
            server = smtplib.SMTP(host, settings.smtp_port, timeout=10)
            server.starttls()
        else:
            server = smtplib.SMTP(host, settings.smtp_port, timeout=10)
        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(sender, [to], msg_root.as_string())
        server.quit()
        return True
    except Exception as e:
        logger.warning("SMTP OTP delivery failed for %s: %s", to, e)
        return False


def send_otp(email: str) -> str:
    """Generate an OTP, store it with TTL, email it (if SMTP configured), and return it.

    Falls back to structured logging when SMTP is not available so
    dev environments still work.
    """
    # Throttle guard
    if not _check_otp_throttle(email):
        logger.warning("OTP throttle exceeded for %s", email)
        raise HTTPException(
            status_code=429,
            detail="Too many OTP requests. Please wait 15 minutes before trying again.",
            headers={"Retry-After": str(OTP_THROTTLE_WINDOW // OTP_THROTTLE_LIMIT)},
        )

    otp = str(random.randint(100000, 999999))
    # Persist via Redis (with memory fallback). TTL is enforced by the store,
    # so we no longer need a manual sweep of expired entries.
    otp_store.set_otp(email, otp, OTP_TTL_SECONDS)

    mailed = _send_otp_email(email, otp)
    if mailed:
        logger.info("OTP emailed", extra={"email": email, "ttl": OTP_TTL_SECONDS})
    else:
        # Dev fallback: print the OTP to the console ONLY when explicit debug
        # logging is enabled. Aggregated production logs must never carry the
        # raw code — anyone with log-read access could replay it.
        if get_settings().log_level.upper() == "DEBUG":
            logger.debug("OTP generated (no SMTP configured)", extra={"email": email, "otp": otp, "ttl": OTP_TTL_SECONDS})
        else:
            logger.warning(
                "OTP generated but SMTP delivery failed. Configure SMTP_* env vars; set LOG_LEVEL=DEBUG to print codes locally.",
                extra={"email": email, "ttl": OTP_TTL_SECONDS},
            )
    return otp



# ───────────────────── helpers ─────────────────────

def _firebase_api_key() -> str:
    key = os.getenv("FIREBASE_WEB_API_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="Firebase is not configured.")
    return key


def _friendly(code: str) -> str:
    msgs = {
        "EMAIL_EXISTS": "An account already exists for this email.",
        "EMAIL_NOT_FOUND": "No account was found for this email.",
        "INVALID_LOGIN_CREDENTIALS": "The email or password is incorrect.",
        "INVALID_PASSWORD": "The email or password is incorrect.",
        "MISSING_PASSWORD": "Please enter a password.",
        "WEAK_PASSWORD : Password should be at least 6 characters":
            "Password should be at least 6 characters.",
        "USER_DISABLED": "This account has been disabled.",
        "TOO_MANY_ATTEMPTS_TRY_LATER": "Too many attempts. Try again later.",
        "INVALID_EMAIL": "Please enter a valid email address.",
        "OPERATION_NOT_ALLOWED": "Email/password sign-in is not enabled.",
        "CONFIGURATION_NOT_FOUND": "Firebase Authentication is not initialized.",
        "API_KEY_INVALID": "The Firebase Web API key is invalid.",
        "INVALID_API_KEY": "The Firebase Web API key is invalid.",
    }
    if code.startswith("WEAK_PASSWORD"):
        return "Password should be at least 6 characters."
    return msgs.get(code, f"Authentication error: {code or 'unknown'}")


def _firebase_request(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    api_key = _firebase_api_key()
    r = requests.post(
        f"{FIREBASE_AUTH_BASE_URL}/{endpoint}?key={api_key}",
        json=payload,
        timeout=20,
    )
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.ok:
        return data
    code = (data.get("error") or {}).get("message", "")
    raise HTTPException(status_code=400, detail=_friendly(code))


def _user_from_firebase(d: dict[str, Any]) -> dict[str, Any]:
    email = d.get("email", "")
    return {
        "user_id": d.get("localId", "") or email,
        "email": email,
        "name": d.get("displayName") or (email.split("@")[0] if email else "User"),
        "id_token": d.get("idToken", ""),
        "refresh_token": d.get("refreshToken", ""),
        "expires_at": time.time() + ID_TOKEN_TTL,
        "email_verified": d.get("emailVerified", False),
    }


# ───────────────────── schemas ─────────────────────

class SignInBody(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class SignUpBody(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)
    name: str | None = None


class ResetBody(BaseModel):
    email: EmailStr


class RefreshBody(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class AuthResponse(BaseModel):
    user_id: str
    email: str
    name: str
    id_token: str
    refresh_token: str
    expires_at: float
    email_verified: bool = False


class MeResponse(BaseModel):
    user_id: str
    email: str
    name: str


# ───────────────────── routes ─────────────────────

@router.post("/signin", response_model=AuthResponse, dependencies=[Depends(RateLimit("auth.signin", per_minute=5, per_ip=True))])
def signin(body: SignInBody) -> AuthResponse:
    data = _firebase_request(
        "accounts:signInWithPassword",
        {"email": body.email, "password": body.password, "returnSecureToken": True},
    )
    
    user_id = data.get("localId")
    if not user_id or not is_user_verified(user_id):
        # Auto-send OTP for users who haven't completed OTP verification
        send_otp(body.email)
        raise HTTPException(
            status_code=403,
            detail="Email not verified. OTP sent.",
        )
        
    data["emailVerified"] = True
    return AuthResponse(**_user_from_firebase(data))


@router.post("/signup", response_model=AuthResponse, dependencies=[Depends(RateLimit("auth.signup", per_minute=5, per_ip=True))])
def signup(body: SignUpBody) -> AuthResponse:
    data = _firebase_request(
        "accounts:signUp",
        {"email": body.email, "password": body.password, "returnSecureToken": True},
    )
    # Preserve the idToken from signUp; accounts:update may return a new one,
    id_token = data.get("idToken", "")
    if body.name:
        update_resp = _firebase_request(
            "accounts:update",
            {"idToken": id_token, "displayName": body.name, "returnSecureToken": True},
        )
        # Merge: keep the idToken (prefer fresh one from update if present)
        id_token = update_resp.get("idToken") or id_token
        data.update(update_resp)
        data["idToken"] = id_token
        
    # Send custom OTP
    send_otp(body.email)
    
    result = _user_from_firebase(data)
    result["email_verified"] = False
    resp = AuthResponse(**result)
    return resp


@router.post("/reset", dependencies=[Depends(RateLimit("auth.reset", per_minute=3, per_ip=True))])
def send_reset(body: ResetBody) -> dict[str, str]:
    _firebase_request(
        "accounts:sendOobCode",
        {"requestType": "PASSWORD_RESET", "email": body.email},
    )
    return {"status": "sent"}


class ResendVerifyBody(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)

@router.post("/resend-verification", dependencies=[Depends(RateLimit("auth.resend", per_minute=3, per_ip=True))])
def resend_verification(body: ResendVerifyBody) -> dict[str, str]:
    # Validate user credentials first
    _firebase_request(
        "accounts:signInWithPassword",
        {"email": body.email, "password": body.password, "returnSecureToken": True},
    )
    # Re-send OTP
    send_otp(body.email)
    return {"status": "sent"}

class VerifyOtpBody(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)
    otp: str = Field(..., min_length=6, max_length=6)

@router.post("/verify-otp", response_model=AuthResponse)
def verify_otp(body: VerifyOtpBody) -> AuthResponse:
    # TTL is enforced by the store — a missing entry means expired OR
    # never-issued; we present the same message either way so we don't
    # leak which one it is.
    stored = otp_store.get_otp(body.email)
    if not stored:
        raise HTTPException(status_code=400, detail="OTP expired or not found. Please request a new one.")

    # Attempt cap. Burn the code on the *current* attempt so a future
    # correct guess can't bypass this after the limit is hit.
    if stored["attempts"] >= MAX_OTP_ATTEMPTS:
        otp_store.delete_otp(body.email)
        raise HTTPException(status_code=400, detail="Too many failed attempts. Please request a new OTP.")

    if stored["otp"] != body.otp:
        new_attempts = otp_store.increment_attempts(body.email)
        remaining = max(0, MAX_OTP_ATTEMPTS - new_attempts)
        if remaining <= 0:
            # Hit the cap on this attempt — burn the code so the next
            # request (even with the right OTP) has to start fresh.
            otp_store.delete_otp(body.email)
        raise HTTPException(
            status_code=400,
            detail=f"Invalid OTP. {remaining} attempt(s) remaining before this code is invalidated."
        )

    # Sign in to get tokens for the frontend
    data = _firebase_request(
        "accounts:signInWithPassword",
        {"email": body.email, "password": body.password, "returnSecureToken": True},
    )

    user_id = data.get("localId")
    if user_id:
        mark_user_verified(user_id)

    # Remove used OTP
    otp_store.delete_otp(body.email)

    data["emailVerified"] = True
    return AuthResponse(**_user_from_firebase(data))


class VerifyResetBody(BaseModel):
    oob_code: str = Field(..., min_length=1)


class ConfirmResetBody(BaseModel):
    oob_code: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6)


@router.post("/verify-reset")
def verify_reset(body: VerifyResetBody) -> dict[str, str]:
    data = _firebase_request(
        "accounts:resetPassword",
        {"oobCode": body.oob_code},
    )
    return {"email": data.get("email", "")}


@router.post("/confirm-reset")
def confirm_reset(body: ConfirmResetBody) -> dict[str, str]:
    _firebase_request(
        "accounts:resetPassword",
        {"oobCode": body.oob_code, "newPassword": body.new_password},
    )
    return {"status": "reset"}


@router.post("/refresh", response_model=AuthResponse)
def refresh(body: RefreshBody) -> AuthResponse:
    api_key = _firebase_api_key()
    r = requests.post(
        f"{FIREBASE_SECURE_TOKEN_URL}?key={api_key}",
        data={"grant_type": "refresh_token", "refresh_token": body.refresh_token},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=20,
    )
    if not r.ok:
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
    j = r.json()
    # Look up user details to fill name/email
    lookup = _firebase_request("accounts:lookup", {"idToken": j["id_token"]})
    user = (lookup.get("users") or [{}])[0]
    return AuthResponse(
        user_id=user.get("localId", ""),
        email=user.get("email", ""),
        name=user.get("displayName") or (user.get("email", "").split("@")[0] if user.get("email") else "User"),
        id_token=j["id_token"],
        refresh_token=j["refresh_token"],
        expires_at=time.time() + int(j.get("expires_in", ID_TOKEN_TTL)),
    )


# ─── Auth dependency: parse Bearer token, return user info ───

def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")
    token = authorization.split(" ", 1)[1].strip()

    # ── 0. In-memory cache (dev optimisation) ──
    now = time.time()
    cached = _AUTH_CACHE.get(token)
    if cached and now - cached[1] < _AUTH_CACHE_TTL:
        request.state.user = cached[0]
        return cached[0]

    # ── 1. Try firebase_admin SDK verification (fast, local JWKS) ──
    try:
        decoded = firebase_auth.verify_id_token(token)
        email = decoded.get("email", "")
        result = {
            "user_id": decoded.get("uid", ""),
            "email": email,
            "name": decoded.get("name") or (email.split("@")[0] if email else "User"),
        }
        request.state.user = result
        _AUTH_CACHE[token] = (result, now)
        return result
    except Exception:
        pass

    # ── 2. REST API fallback (works without service account credentials) ──
    try:
        lookup = _firebase_request("accounts:lookup", {"idToken": token})
        user = (lookup.get("users") or [{}])[0]
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user.")
        email = user.get("email", "")
        result = {
            "user_id": user.get("localId", "") or email,
            "email": email,
            "name": user.get("displayName") or (email.split("@")[0] if email else "User"),
        }
        request.state.user = result
        _AUTH_CACHE[token] = (result, now)
        return result
    except HTTPException:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")


@router.get("/me", response_model=MeResponse)
def me(user: dict[str, Any] = Depends(get_current_user)) -> MeResponse:
    return MeResponse(**user)


@router.get("/me/usage", dependencies=[Depends(RateLimit("usage.read", per_minute=30))])
def me_usage(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Return the user's current storage and rate-limit status."""
    uid = user["user_id"]
    used = user_storage_usage(uid)
    _, remaining_research = check_deep_research_limit(uid)
    return {
        "storage": {
            "used_bytes": used,
            "quota_bytes": MAX_QUOTA_BYTES,
            "used_mb": round(used / (1024 * 1024), 2),
            "quota_mb": round(MAX_QUOTA_BYTES / (1024 * 1024), 2),
        },
        "limits": {
            "deep_research_remaining": remaining_research,
        },
    }


class UpdateProfileBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


@router.post("/update-profile", response_model=MeResponse)
def update_profile(
    body: UpdateProfileBody,
    authorization: str | None = Header(default=None),
) -> MeResponse:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")
    token = authorization.split(" ", 1)[1].strip()
    data = _firebase_request(
        "accounts:update",
        {"idToken": token, "displayName": body.name.strip(), "returnSecureToken": False},
    )
    email = data.get("email", "")
    return MeResponse(
        user_id=data.get("localId", "") or email,
        email=email,
        name=data.get("displayName") or body.name.strip(),
    )


class PreferencesBody(BaseModel):
    instructions: str = Field(..., max_length=1500)


@router.get("/preferences")
def get_preferences(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, str]:
    instructions = get_custom_instructions(user["user_id"])
    return {"instructions": instructions}


@router.post("/preferences")
def update_preferences(
    body: PreferencesBody,
    user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, str]:
    set_custom_instructions(user["user_id"], body.instructions)
    return {"status": "success"}
