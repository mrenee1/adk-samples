"""Card scan, site survey and ROE: start (build the A2UI sheet) and finish
(handle the sheet's button). Used by both the app buttons and the agent."""

from __future__ import annotations

from typing import Any

from . import a2ui, card_scanner, emails, field, property_lookup
from .store import read_upload


def start_card_scan(owner: str, business_id: str, upload_id: str) -> dict:
    business = field.get_business(owner, business_id)
    upload = read_upload(upload_id)
    if upload is None:
        raise KeyError("Photo not found; take it again.")
    fields = card_scanner.scan_card(*upload)
    return a2ui.card_review(business, fields, upload_id)


def start_roe(owner: str, business_id: str) -> dict:
    business = field.get_business(owner, business_id)
    info = property_lookup.lookup_owner(
        " ".join(
            x for x in [business.get("street"), business.get("unit")] if x
        ),
        business.get("city", ""),
        business.get("zip", ""),
    )
    business = {**business, "address": field.full_address(business)}
    return a2ui.roe_review(business, info, field.get_settings(owner))


def start_survey(owner: str, business_id: str) -> dict:
    business = field.get_business(owner, business_id)
    contacts = field.contacts_for(owner, business_id)
    business = {**business, "address": field.full_address(business)}
    return a2ui.survey_review(
        business, contacts[-1] if contacts else None, field.get_settings(owner)
    )


def _str(ctx: dict, key: str) -> str:
    return str(ctx.get(key) or "").strip()


def save_contact(owner: str, ctx: dict[str, Any]) -> dict:
    values = {k: _str(ctx, k) for k in a2ui.CARD_KEYS}
    if not any(values.values()):
        raise ValueError(
            "The card is empty. Fill in at least a name or number."
        )
    contact = field.save_contact(
        owner,
        {
            **values,
            "business_id": _str(ctx, "business_id"),
            "upload_id": _str(ctx, "upload_id"),
            "source": "Business card",
        },
    )
    name = " ".join(
        x for x in [contact["first_name"], contact["last_name"]] if x
    )
    return {"message": f"Saved {name or 'contact'}.", "contact": contact}


def draft_roe_email(owner: str, ctx: dict[str, Any]) -> dict:
    business = field.get_business(owner, _str(ctx, "business_id"))
    business = {**business, "address": field.full_address(business)}
    info = {
        k: _str(ctx, k)
        for k in [
            "owner",
            "owner_mailing",
            "parcel_id",
            "county",
            "property_use",
            "appraiser_url",
            "sunbiz_url",
        ]
    }
    extra = {k: _str(ctx, k) for k in ["site_contact", "notes"]}
    settings = field.get_settings(owner)
    email = emails.roe_email(settings, business, info, extra)
    record = field.add_record(
        owner, business["id"], "roe", "Requested", {**info, **extra}
    )
    return {
        "message": f"ROE email ready for {settings.get('roe_to_name') or 'review'}.",
        "email": email,
        "record": record,
    }


def request_survey(owner: str, ctx: dict[str, Any]) -> dict:
    business = field.get_business(owner, _str(ctx, "business_id"))
    business = {**business, "address": field.full_address(business)}
    extra = {k: _str(ctx, k) for k in a2ui.SURVEY_KEYS}
    settings = field.get_settings(owner)
    record = field.add_record(
        owner, business["id"], "survey", "Requested", extra
    )
    out: dict[str, Any] = {"record": record, "message": "Site survey ordered."}
    mode = settings.get("survey_mode", "email")
    if mode == "form" and settings.get("survey_form_url"):
        out["url"] = emails.form_url(
            settings["survey_form_url"],
            {
                **settings,
                **extra,
                "business": business["name"],
                "address": business["address"],
            },
        )
        out["message"] = "Opening the survey form with the details filled in."
    elif mode == "email":
        out["email"] = emails.survey_email(settings, business, extra)
        out["message"] = "Survey request email ready."
    return out


ACTIONS = {
    "save_contact": save_contact,
    "draft_roe_email": draft_roe_email,
    "request_survey": request_survey,
}
