"""Entry point for hosts that look for ``app.py`` (Vercel's FastAPI preset)."""

from field_assistant.server import app

__all__ = ["app"]
