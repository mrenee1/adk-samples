"""Deployment settings (environment) and rep-editable app settings (stored)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
WEB_DIR = Path(os.getenv("WEB_DIR", PROJECT_DIR / "web"))

# --- Deployment settings (set as env vars locally or on Cloud Run) ---------

# "local" keeps everything in JSON files under DATA_DIR; "firestore" uses the
# Google Cloud project the service runs in.
DATA_BACKEND = os.getenv("DATA_BACKEND", "local")
DATA_DIR = Path(os.getenv("DATA_DIR", PROJECT_DIR / "data"))

# "none" for local testing; "firebase" requires a Firebase Google sign-in and
# an email on ALLOWED_EMAILS.
AUTH_MODE = os.getenv("AUTH_MODE", "none")
ALLOWED_EMAILS = {
    e.strip().lower()
    for e in os.getenv("ALLOWED_EMAILS", "").split(",")
    if e.strip()
}
LOCAL_USER = os.getenv("LOCAL_USER", "me@example.com")

# Firebase web config (the JSON snippet from Firebase console > Project
# settings > Your apps). Only needed when AUTH_MODE=firebase.
FIREBASE_WEB_CONFIG = json.loads(os.getenv("FIREBASE_WEB_CONFIG", "{}") or "{}")

MODEL = os.getenv("FIELD_MODEL", "gemini-2.5-flash")
TIMEZONE = ZoneInfo(os.getenv("FIELD_TIMEZONE", "America/New_York"))

# --- App settings (each rep edits these on the Settings screen) -----------

DEFAULT_APP_SETTINGS: dict = {
    "rep_name": "",
    "rep_title": "Business Account Executive",
    "rep_phone": "",
    "rep_email": "",
    "company": "IQ Fiber",
    "daily_goal": 40,
    "manager_email": "",
    # ROE requests go to this person (e.g. David).
    "roe_to_name": "David",
    "roe_to_email": "",
    "roe_cc": "",
    "roe_subject": "ROE request: {business} ({address})",
    "roe_body": (
        "Hi {roe_to_name},\n\n"
        "Please start a Right of Entry for this property.\n\n"
        "Business: {business}\n"
        "Service address: {address}\n"
        "On-site contact: {site_contact}\n\n"
        "Property owner of record: {owner}\n"
        "Owner mailing address: {owner_mailing}\n"
        "Parcel: {parcel_id} ({county} County)\n"
        "Property use: {property_use}\n"
        "Appraiser record: {appraiser_url}\n"
        "Sunbiz search: {sunbiz_url}\n\n"
        "Notes: {notes}\n\n"
        "Thanks,\n{rep_name}\n{rep_phone}"
    ),
    # "email" sends a pre-filled request, "form" opens survey_form_url with
    # the details filled in, "log" only records it.
    "survey_mode": "email",
    "survey_to_email": "",
    "survey_form_url": "",
    "survey_subject": "Site survey request: {business} ({address})",
    "survey_body": (
        "Hi,\n\n"
        "Please schedule a site survey.\n\n"
        "Business: {business}\n"
        "Address: {address}\n"
        "Contact: {contact_name} {contact_phone} {contact_email}\n"
        "Best time: {best_time}\n"
        "Notes: {notes}\n\n"
        "Thanks,\n{rep_name}\n{rep_phone}"
    ),
    "followup_subject": "Following up after my visit to {business}",
    "followup_body": (
        "Hi {contact_first},\n\n"
        "I stopped by {business} on my recent visit. I'm your local "
        "{company} {rep_title} and wanted to share my contact information. "
        "Who would be the best person to connect with about your business "
        "internet?\n\n"
        "{rep_name}\n{rep_title} | {company}\n{rep_phone}\n{rep_email}"
    ),
}
