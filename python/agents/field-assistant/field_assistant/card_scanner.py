"""Business card photo -> contact fields, using Gemini vision."""

from __future__ import annotations

import json

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from . import config


class CardFields(BaseModel):
    first_name: str = ""
    last_name: str = ""
    title: str = ""
    company: str = ""
    phone: str = Field("", description="Office/main phone, digits as printed")
    mobile: str = Field("", description="Cell phone if labeled as such")
    email: str = ""
    website: str = ""
    street: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    confidence: str = Field(
        "", description="'high', 'medium' or 'low' for the whole card"
    )


PROMPT = (
    "Read this business card photo and return the contact details. Copy "
    "values exactly as printed; leave a field empty if it is not on the "
    "card. Do not guess emails or phone numbers. If the photo is not a "
    "business card, return empty fields with confidence 'low'."
)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    # Uses GOOGLE_API_KEY locally, or Vertex AI on Cloud Run when
    # GOOGLE_GENAI_USE_VERTEXAI=TRUE is set.
    global _client  # noqa: PLW0603
    if _client is None:
        _client = genai.Client()
    return _client


def scan_card(image: bytes, mime: str) -> dict:
    response = _get_client().models.generate_content(
        model=config.MODEL,
        contents=[types.Part.from_bytes(data=image, mime_type=mime), PROMPT],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=CardFields,
            temperature=0,
        ),
    )
    parsed = response.parsed
    if isinstance(parsed, CardFields):
        return parsed.model_dump()
    return CardFields(**json.loads(response.text or "{}")).model_dump()
