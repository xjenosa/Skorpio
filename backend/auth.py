"""
Skorpio authentication.

Two paths into a session:
  1. Google OAuth 2.0
       /api/auth/google/login    → 302 to Google
       /api/auth/google/callback ← Google → 302 to frontend with #token=…
  2. Email magic-code (6-digit) via Resend
       POST /api/auth/email/request-code  {email}            → 202
       POST /api/auth/email/verify-code   {email, code}      → {token, user}

Sessions are stateless JWTs signed with SKORPIO_AUTH_SECRET. Logout is
client-side (drop the token); a server-side revocation list is overkill for
this scope but easy to add later.
"""
import hashlib
import hmac
import secrets
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional

import httpx
import jwt
import resend
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db import crud
from backend.db.models import User
from backend.db.session import get_db
from backend.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Constants ─────────────────────────────────────────────────────────── #

JWT_ALG = "HS256"
CODE_TTL_MINUTES = 10
MAX_CODE_ATTEMPTS = 5


# ── Email allowlist ───────────────────────────────────────────────────── #

def _allowed_emails() -> set[str]:
    """Parse SKORPIO_ALLOWED_EMAILS into a normalised set. Empty = no
    restriction (allow any email)."""
    raw = (settings.skorpio_allowed_emails or "").strip()
    if not raw:
        return set()
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def is_email_allowed(email: str) -> bool:
    """Allowlist check. Returns True when no allowlist is configured (open
    dev mode) OR when the email is in the configured allowlist (case- and
    whitespace-insensitive)."""
    allow = _allowed_emails()
    if not allow:
        return True
    return (email or "").strip().lower() in allow


# ── JWT helpers ───────────────────────────────────────────────────────── #

def issue_token(user_id: str, email: str) -> str:
    now = datetime.utcnow()
    payload = {
        "sub": user_id,
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.skorpio_auth_token_ttl_hours)).timestamp()),
    }
    return jwt.encode(payload, settings.skorpio_auth_secret, algorithm=JWT_ALG)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.skorpio_auth_secret, algorithms=[JWT_ALG])


# ── Bearer dependency ─────────────────────────────────────────────────── #

bearer_scheme = HTTPBearer(auto_error=False)


async def current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not creds:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_token(creds.credentials)
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
    user = await crud.get_user_by_id(db, payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user


# ── Email-code helpers ────────────────────────────────────────────────── #

def generate_code() -> str:
    """6-digit code, leading zeros preserved (so '000123' stays 6 chars)."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_code(code: str, salt: str) -> str:
    """HMAC of (salt, code) keyed by the JWT secret. The salt is per-row
    so two pending codes with the same digits never collide."""
    return hmac.new(
        settings.skorpio_auth_secret.encode("utf-8"),
        f"{salt}:{code}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def send_code_email(email: str, code: str) -> None:
    """Fire the magic-code email through Resend.

    Configure RESEND_API_KEY + RESEND_FROM_EMAIL in .env. The default sender
    `onboarding@resend.dev` works without verifying a domain; use your own
    once you've verified one in the Resend dashboard.
    """
    resend.api_key = settings.resend_api_key
    html = f"""
    <div style="background: #0a0a09; padding: 56px 24px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;">
      <div style="max-width: 480px; margin: 0 auto; text-align: center;">
        <div style="margin: 0 0 44px; font-size: 22px; font-weight: 500; letter-spacing: 0.06em; color: #faf9f5;">
          SK<span style="color: #F38764;">O</span>RPIO
        </div>
        <h1 style="font-family: Georgia, 'Times New Roman', serif; font-weight: 400; font-size: 34px; line-height: 1.15; letter-spacing: -0.01em; color: #faf9f5; margin: 0 0 14px;">Let's get you signed in</h1>
        <p style="font-size: 15px; line-height: 1.55; color: #b3b1a8; margin: 0 0 36px;">Sign in with the code below</p>
        <div style="font-family: ui-monospace, Menlo, Consolas, 'Courier New', monospace; font-size: 36px; font-weight: 500; letter-spacing: 0.4em; padding: 22px 24px 22px 32px; background: #161614; border: 1px solid #2a2824; border-radius: 10px; color: #f38764; margin: 0 0 28px;">{code}</div>
        <p style="font-size: 13px; line-height: 1.6; color: #6f6c63; margin: 0 0 6px;">It expires in {CODE_TTL_MINUTES} minutes.</p>
        <p style="font-size: 13px; line-height: 1.6; color: #6f6c63; margin: 0;">If you didn't request this, you can safely ignore the email.</p>
      </div>
    </div>
    """
    resend.Emails.send({
        "from": f"Skorpio <{settings.resend_from_email}>",
        "to": [email],
        "subject": f"{code} is your Skorpio sign-in code",
        "html": html,
        "text": f"Your Skorpio sign-in code is: {code}\n\nIt expires in {CODE_TTL_MINUTES} minutes.",
    })


# ── Email auth endpoints ──────────────────────────────────────────────── #

class RequestCodeBody(BaseModel):
    email: EmailStr


class VerifyCodeBody(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


@router.post("/email/request-code", status_code=202)
async def request_email_code(
    body: RequestCodeBody,
    db: AsyncSession = Depends(get_db),
):
    if not settings.resend_api_key:
        raise HTTPException(status_code=503, detail="Email login not configured (missing RESEND_API_KEY)")
    if not is_email_allowed(body.email):
        # Rejected before sending the email — avoids both the Resend bill
        # AND the info leak of "code sent but never accepted".
        logger.info(f"Blocked email-code request for non-allowlisted address {body.email}")
        raise HTTPException(
            status_code=403,
            detail="This email is not authorized to access Skorpio.",
        )
    code = generate_code()
    salt = secrets.token_urlsafe(16)
    await crud.create_email_code(
        db,
        email=body.email,
        salt=salt,
        code_hash=hash_code(code, salt),
        expires_at=datetime.utcnow() + timedelta(minutes=CODE_TTL_MINUTES),
    )
    try:
        send_code_email(body.email, code)
    except Exception as exc:
        logger.error(f"Resend send failed for {body.email}: {exc}")
        raise HTTPException(status_code=502, detail="Could not send code email")
    logger.info(f"Issued email code for {body.email}")
    return {"status": "sent", "expires_in_minutes": CODE_TTL_MINUTES}


@router.post("/email/verify-code")
async def verify_email_code(
    body: VerifyCodeBody,
    db: AsyncSession = Depends(get_db),
):
    rec = await crud.get_active_email_code(db, body.email)
    if not rec:
        raise HTTPException(status_code=400, detail="No pending code. Request a new one.")
    if rec.attempts >= MAX_CODE_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many attempts. Request a new code.")
    expected = hash_code(body.code, rec.salt)
    if not hmac.compare_digest(expected, rec.code_hash):
        await crud.bump_email_code_attempts(db, rec.id)
        raise HTTPException(status_code=400, detail="Wrong code")

    await crud.consume_email_code(db, rec.id)
    user = await crud.upsert_user_by_email(db, email=body.email)
    token = issue_token(user.id, user.email)
    logger.info(f"Email login OK for {user.email}")
    return {"token": token, "user": _user_dict(user)}


# ── Google OAuth ──────────────────────────────────────────────────────── #

@router.get("/google/login")
async def google_login(redirect_to: str = "/"):
    """302 to Google's consent screen.

    `redirect_to` rides along inside a signed `state` JWT so the callback
    knows where to send the user back to in the frontend.
    """
    if not settings.google_oauth_client_id:
        raise HTTPException(status_code=503, detail="Google login not configured")

    state = jwt.encode(
        {
            "redirect_to": redirect_to,
            "nonce": secrets.token_urlsafe(8),
            "exp": int((datetime.utcnow() + timedelta(minutes=10)).timestamp()),
        },
        settings.skorpio_auth_secret,
        algorithm=JWT_ALG,
    )
    qs = urllib.parse.urlencode({
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "include_granted_scopes": "true",
        "prompt": "select_account",
        "state": state,
    })
    return RedirectResponse(url=f"https://accounts.google.com/o/oauth2/v2/auth?{qs}")


@router.get("/google/callback")
async def google_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
):
    """Handle Google's redirect: exchange code → tokens → user info → JWT.

    Sends the user back to the frontend with the token in the URL fragment
    (`#token=…`), which is invisible to servers and easy to read from JS.
    """
    try:
        state_payload = jwt.decode(state, settings.skorpio_auth_secret, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    async with httpx.AsyncClient(timeout=20) as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "redirect_uri": settings.google_oauth_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if token_resp.status_code != 200:
        logger.error(f"Google token exchange failed: {token_resp.status_code} {token_resp.text}")
        raise HTTPException(status_code=400, detail="Google token exchange failed")

    tokens = token_resp.json()
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="Missing id_token from Google")

    # We trust the id_token because it came over TLS straight from Google's
    # token endpoint we just authenticated to with our client_secret. Full
    # signature verification (RS256 via Google's JWKS) is the right move
    # for production; skipping here keeps the dep surface small.
    try:
        claims = jwt.decode(id_token, options={"verify_signature": False})
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=400, detail=f"Bad id_token: {e}")

    email = claims.get("email")
    google_sub = claims.get("sub")
    name = claims.get("name") or claims.get("given_name") or email
    if not email or not google_sub:
        raise HTTPException(status_code=400, detail="Google id_token missing email/sub")

    if not is_email_allowed(email):
        # Bounce back to /login with a friendly error fragment instead of
        # showing a raw JSON HTTPException. LoginPage's hash-parse effect
        # reads ?error= and renders it.
        logger.info(f"Blocked Google sign-in for non-allowlisted address {email}")
        return RedirectResponse(
            url=f"{settings.frontend_url}/login#error=not_authorized"
        )

    user = await crud.upsert_user_by_google(
        db, email=email, name=name, google_sub=google_sub,
    )
    token = issue_token(user.id, user.email)
    logger.info(f"Google login OK for {user.email}")

    # Always land on /login so its #token=… handler can catch the JWT,
    # store it, and then forward to the user's intended destination. The
    # original redirect_to from the OAuth start ride along so LoginPage
    # knows where to send them after a successful /me.
    redirect_to = state_payload.get("redirect_to", "/")
    if not redirect_to.startswith("/"):
        redirect_to = "/"
    safe_dest = urllib.parse.quote(redirect_to, safe="/")
    return RedirectResponse(
        url=f"{settings.frontend_url}/login#token={token}&dest={safe_dest}"
    )


# ── Session introspection ─────────────────────────────────────────────── #

@router.get("/me")
async def get_me(user: User = Depends(current_user)):
    return _user_dict(user)


@router.post("/logout", status_code=204)
async def logout():
    """Stateless: the client discards its token. Returned for symmetry."""
    return None


def _user_dict(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "google_sub": user.google_sub,
        "created_at": user.created_at,
    }
