"""Who is calling? Firebase Google sign-in in the cloud, a fixed user locally."""

from __future__ import annotations

import os

from fastapi import HTTPException, Request

from . import config

_firebase_ready = False


def _init_firebase() -> None:
    global _firebase_ready  # noqa: PLW0603
    if _firebase_ready:
        return
    import firebase_admin  # noqa: PLC0415

    project = os.getenv(
        "GOOGLE_CLOUD_PROJECT"
    ) or config.FIREBASE_WEB_CONFIG.get("projectId")
    if not firebase_admin._apps:
        firebase_admin.initialize_app(
            options={"projectId": project} if project else None
        )
    _firebase_ready = True


def verify(request: Request) -> str:
    """Return the caller's email, or raise 401/403."""
    if config.AUTH_MODE == "none":
        return config.LOCAL_USER
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in first.")
    _init_firebase()
    from firebase_admin import auth  # noqa: PLC0415

    try:
        claims = auth.verify_id_token(header.split(" ", 1)[1])
    except Exception as e:
        raise HTTPException(401, "Sign-in expired. Sign in again.") from e
    email = (claims.get("email") or "").lower()
    if not email or not claims.get("email_verified", False):
        raise HTTPException(403, "This Google account has no verified email.")
    if config.ALLOWED_EMAILS and email not in config.ALLOWED_EMAILS:
        raise HTTPException(403, f"{email} is not on this app's list.")
    return email
