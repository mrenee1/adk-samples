"""Fill the rep's email templates (Settings screen) with record details."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote


class _Blank(dict):
    def __missing__(self, key: str) -> str:
        return ""


_PLACEHOLDER = re.compile(r"{(\w+)}")


def fill(template: str, values: dict[str, Any]) -> str:
    """Format ``template``; drop "Label: {x}" lines when every {x} is empty."""
    data = _Blank({k: "" if v is None else str(v) for k, v in values.items()})
    out = []
    for line in template.splitlines():
        keys = _PLACEHOLDER.findall(line)
        rendered = line.format_map(data).rstrip()
        empty = keys and not any(data[k].strip() for k in keys)
        if empty and (":" in line or not rendered.strip()):
            continue
        out.append(rendered)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out))
    return text.strip() + "\n"


def roe_email(
    settings: dict, business: dict, owner_info: dict, extra: dict
) -> dict:
    values = {
        **settings,
        "business": business.get("name", ""),
        "address": business.get("address", ""),
        "site_contact": extra.get("site_contact", ""),
        "notes": extra.get("notes", ""),
        "owner": owner_info.get("owner", ""),
        "owner_mailing": owner_info.get("owner_mailing", ""),
        "parcel_id": owner_info.get("parcel_id", ""),
        "county": owner_info.get("county", ""),
        "property_use": owner_info.get("property_use", ""),
        "appraiser_url": owner_info.get("appraiser_url", ""),
        "sunbiz_url": owner_info.get("sunbiz_url", ""),
    }
    return {
        "to": settings.get("roe_to_email", ""),
        "cc": settings.get("roe_cc", ""),
        "subject": fill(settings["roe_subject"], values).strip(),
        "body": fill(settings["roe_body"], values),
    }


def survey_email(settings: dict, business: dict, extra: dict) -> dict:
    values = {
        **settings,
        "business": business.get("name", ""),
        "address": business.get("address", ""),
        "contact_name": extra.get("contact_name", ""),
        "contact_phone": extra.get("contact_phone", ""),
        "contact_email": extra.get("contact_email", ""),
        "best_time": extra.get("best_time", ""),
        "notes": extra.get("notes", ""),
    }
    return {
        "to": settings.get("survey_to_email", ""),
        "cc": "",
        "subject": fill(settings["survey_subject"], values).strip(),
        "body": fill(settings["survey_body"], values),
    }


def followup_email(
    settings: dict, business: dict, contact: dict | None
) -> dict:
    contact = contact or {}
    values = {
        **settings,
        "business": business.get("name", ""),
        "contact_first": contact.get("first_name") or "there",
    }
    return {
        "to": contact.get("email") or business.get("email", ""),
        "cc": "",
        "subject": fill(settings["followup_subject"], values).strip(),
        "body": fill(settings["followup_body"], values),
    }


def form_url(template: str, values: dict[str, Any]) -> str:
    """Survey form links can carry {business}, {address}... placeholders."""
    return template.format_map(
        _Blank({k: quote(str(v or "")) for k, v in values.items()})
    )
