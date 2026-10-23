"""A2UI v0.9 surfaces for the three time-wasters.

Each builder returns the standard ``a2ui_operations`` envelope (createSurface
-> updateComponents -> updateDataModel). The same envelope is returned by
the agent's tools (streamed over AG-UI) and by the phone app's buttons (plain
REST), and the app renders both with one small renderer in web/a2ui.js.

Buttons emit A2UI action events; the app handles them in web/app.js
(``save_contact``, ``draft_roe_email``, ``request_survey``, ``open_url``,
``dismiss``) by calling /api/actions/<name>.
"""

from __future__ import annotations

from typing import Any

from ag_ui_a2ui_toolkit import (
    A2UI_OPERATIONS_KEY,
    create_surface,
    update_components,
    update_data_model,
)

CATALOG_ID = "https://field-assistant.local/catalogs/v1.json"


def _envelope(surface_id: str, components: list[dict], data: dict) -> dict:
    return {
        A2UI_OPERATIONS_KEY: [
            create_surface(surface_id, CATALOG_ID),
            update_components(surface_id, components),
            update_data_model(surface_id, data),
        ]
    }


def _text(cid: str, text: Any, variant: str = "body") -> dict:
    return {"id": cid, "component": "Text", "text": text, "variant": variant}


def _field(cid: str, label: str, path: str, kind: str = "text") -> dict:
    return {
        "id": cid,
        "component": "TextField",
        "label": label,
        "value": {"path": path},
        "inputType": kind,
    }


def _button(cid: str, label: str, event: str, context: dict, variant="primary"):
    return [
        {
            "id": cid,
            "component": "Button",
            "child": f"{cid}-label",
            "variant": variant,
            "action": {"event": {"name": event, "context": context}},
        },
        _text(f"{cid}-label", label),
    ]


def _paths(prefix: str, keys: list[str]) -> dict:
    return {k: {"path": f"{prefix}/{k}"} for k in keys}


CARD_KEYS = [
    "first_name",
    "last_name",
    "title",
    "phone",
    "mobile",
    "email",
    "website",
]


def card_review(business: dict, fields: dict, upload_id: str) -> dict:
    """'Check the card' sheet: editable fields + Save."""
    sid = f"card-{upload_id}"
    labels = {
        "first_name": "First name",
        "last_name": "Last name",
        "title": "Title",
        "phone": "Phone",
        "mobile": "Cell",
        "email": "Email",
        "website": "Website",
    }
    kinds = {
        "phone": "tel",
        "mobile": "tel",
        "email": "email",
        "website": "url",
    }
    comps: list[dict] = [
        {"id": "root", "component": "Card", "child": "body"},
        {
            "id": "body",
            "component": "Column",
            "children": [
                "title",
                "sub",
                *(f"f-{k}" for k in CARD_KEYS),
                "warn",
                "actions",
            ],
        },
        _text("title", "Check the card", "h2"),
        _text("sub", {"path": "/business/name"}, "caption"),
        *(
            _field(f"f-{k}", labels[k], f"/form/{k}", kinds.get(k, "text"))
            for k in CARD_KEYS
        ),
        {"id": "warn", "component": "Notice", "text": {"path": "/warning"}},
        {
            "id": "actions",
            "component": "Row",
            "justify": "end",
            "children": ["discard", "save"],
        },
        *_button(
            "discard", "Discard", "dismiss", {"surfaceId": sid}, "borderless"
        ),
        *_button(
            "save",
            "Save contact",
            "save_contact",
            {
                "surfaceId": sid,
                "business_id": business["id"],
                "upload_id": upload_id,
                **_paths("/form", CARD_KEYS),
            },
        ),
    ]
    low = fields.get("confidence") == "low"
    data = {
        "business": {"name": business.get("name", "")},
        "form": {k: fields.get(k, "") for k in CARD_KEYS},
        "warning": "Hard to read. Please double-check every field."
        if low
        else "",
    }
    return _envelope(sid, comps, data)


ROE_KEYS = ["owner", "owner_mailing", "parcel_id", "site_contact", "notes"]


def roe_review(business: dict, info: dict, settings: dict) -> dict:
    """'ROE ready' sheet: owner of record + links + draft-email button."""
    sid = f"roe-{business['id']}"
    to_name = settings.get("roe_to_name") or "ROE desk"
    comps: list[dict] = [
        {"id": "root", "component": "Card", "child": "body"},
        {
            "id": "body",
            "component": "Column",
            "children": [
                "title",
                "sub",
                "status",
                "f-owner",
                "f-owner_mailing",
                "f-parcel_id",
                "use",
                "links",
                "f-site_contact",
                "f-notes",
                "actions",
            ],
        },
        _text("title", f"ROE for {business.get('name', '')}", "h2"),
        _text("sub", {"path": "/info/searched"}, "caption"),
        {
            "id": "status",
            "component": "Notice",
            "text": {"path": "/info/status"},
        },
        _field("f-owner", "Property owner", "/form/owner"),
        _field(
            "f-owner_mailing", "Owner mailing address", "/form/owner_mailing"
        ),
        _field("f-parcel_id", "Parcel", "/form/parcel_id"),
        _text("use", {"path": "/info/use_line"}, "caption"),
        {
            "id": "links",
            "component": "Row",
            "children": ["appraiser", "sunbiz"],
        },
        *_button(
            "appraiser",
            "Appraiser record ↗",
            "open_url",
            {"url": {"path": "/info/appraiser_url"}},
            "borderless",
        ),
        *_button(
            "sunbiz",
            "Who owns the LLC? ↗",
            "open_url",
            {"url": {"path": "/info/sunbiz_url"}},
            "borderless",
        ),
        _field(
            "f-site_contact",
            "On-site contact (name, phone)",
            "/form/site_contact",
        ),
        _field("f-notes", "Notes for " + to_name, "/form/notes"),
        {
            "id": "actions",
            "component": "Row",
            "justify": "end",
            "children": ["discard", "draft"],
        },
        *_button(
            "discard", "Not now", "dismiss", {"surfaceId": sid}, "borderless"
        ),
        *_button(
            "draft",
            f"Email {to_name}",
            "draft_roe_email",
            {
                "surfaceId": sid,
                "business_id": business["id"],
                "county": {"path": "/info/county"},
                "property_use": {"path": "/info/property_use"},
                "appraiser_url": {"path": "/info/appraiser_url"},
                "sunbiz_url": {"path": "/info/sunbiz_url"},
                **_paths("/form", ROE_KEYS),
            },
        ),
    ]
    found = info.get("found")
    status = (
        f"Found in {info.get('county')} County records. Check it matches the building."
        if found
        else f"{info.get('reason', 'Not found.')} Fill in the owner from the appraiser site."
    )
    data = {
        "info": {
            "searched": info.get("searched", ""),
            "status": status,
            "county": info.get("county", ""),
            "property_use": info.get("property_use", ""),
            "use_line": " · ".join(
                x
                for x in [
                    info.get("property_use", ""),
                    f"Parcel address: {info['parcel_address']}"
                    if info.get("parcel_address")
                    else "",
                ]
                if x
            ),
            "appraiser_url": info.get("appraiser_url", ""),
            "sunbiz_url": info.get("sunbiz_url", ""),
        },
        "form": {
            "owner": info.get("owner", ""),
            "owner_mailing": info.get("owner_mailing", ""),
            "parcel_id": info.get("parcel_id", ""),
            "site_contact": business.get("site_contact", ""),
            "notes": "",
        },
    }
    return _envelope(sid, comps, data)


def email_card(email: dict, surface_id: str) -> dict:
    """A ready-to-send email the rep can open as a draft with one tap."""
    comps: list[dict] = [
        {"id": "root", "component": "Card", "child": "body"},
        {
            "id": "body",
            "component": "Column",
            "children": ["title", "to", "subject", "f-body", "actions"],
        },
        _text("title", "Email ready", "h2"),
        _text("to", {"path": "/email/to_line"}, "caption"),
        _field("subject", "Subject", "/email/subject"),
        {**_field("f-body", "Message", "/email/body"), "multiline": True},
        {
            "id": "actions",
            "component": "Row",
            "justify": "end",
            "children": ["discard", "open"],
        },
        *_button(
            "discard",
            "Not now",
            "dismiss",
            {"surfaceId": surface_id},
            "borderless",
        ),
        *_button(
            "open",
            "Create draft",
            "open_email",
            {
                "surfaceId": surface_id,
                "to": {"path": "/email/to"},
                "cc": {"path": "/email/cc"},
                "subject": {"path": "/email/subject"},
                "body": {"path": "/email/body"},
            },
        ),
    ]
    data = {
        "email": {
            **email,
            "to_line": "To: "
            + (email.get("to") or "(add a recipient in Settings)"),
        }
    }
    return _envelope(surface_id, comps, data)


SURVEY_KEYS = [
    "contact_name",
    "contact_phone",
    "contact_email",
    "best_time",
    "notes",
]


def survey_review(business: dict, contact: dict | None, settings: dict) -> dict:
    sid = f"survey-{business['id']}"
    mode = settings.get("survey_mode", "email")
    label = {"form": "Open survey form", "log": "Mark survey ordered"}.get(
        mode, "Send survey request"
    )
    comps: list[dict] = [
        {"id": "root", "component": "Card", "child": "body"},
        {
            "id": "body",
            "component": "Column",
            "children": [
                "title",
                "sub",
                *(f"f-{k}" for k in SURVEY_KEYS),
                "actions",
            ],
        },
        _text("title", "Order a site survey", "h2"),
        _text(
            "sub",
            f"{business.get('name', '')} · {business.get('address', '')}",
            "caption",
        ),
        _field("f-contact_name", "Contact", "/form/contact_name"),
        _field(
            "f-contact_phone", "Contact phone", "/form/contact_phone", "tel"
        ),
        _field(
            "f-contact_email", "Contact email", "/form/contact_email", "email"
        ),
        _field("f-best_time", "Best day/time", "/form/best_time"),
        _field("f-notes", "Notes", "/form/notes"),
        {
            "id": "actions",
            "component": "Row",
            "justify": "end",
            "children": ["discard", "send"],
        },
        *_button(
            "discard", "Not now", "dismiss", {"surfaceId": sid}, "borderless"
        ),
        *_button(
            "send",
            label,
            "request_survey",
            {
                "surfaceId": sid,
                "business_id": business["id"],
                **_paths("/form", SURVEY_KEYS),
            },
        ),
    ]
    c = contact or {}
    data = {
        "form": {
            "contact_name": " ".join(
                x for x in [c.get("first_name"), c.get("last_name")] if x
            ),
            "contact_phone": c.get("mobile")
            or c.get("phone")
            or business.get("phone", ""),
            "contact_email": c.get("email") or business.get("email", ""),
            "best_time": "",
            "notes": "",
        }
    }
    return _envelope(sid, comps, data)
