"""Load a rep's existing tracker into the app.

Accepts:
* a spreadsheet (.xlsx) or .csv with one row per business. Column names are
  matched loosely ("Business", "Company", "Account Name"... all work);
* the ``data.json`` export from the earlier Fieldnote map app.

Re-importing the same file updates records instead of duplicating them.
Run from the Settings screen, or:

    python -m field_assistant.importer my_tracker.xlsx --owner me@x.com \
        --city "Fernandina Beach" --zip 32034
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from typing import Any

from . import field
from .store import get_store

ALIASES = {
    "name": [
        "business",
        "business name",
        "company",
        "account",
        "account name",
        "location",
        "prospect",
        "business / deal",
    ],
    "street": [
        "address",
        "street",
        "street address",
        "service address",
        "addresses",
    ],
    "unit": ["unit", "suite", "ste"],
    "city": ["city", "town"],
    "zip": ["zip", "zip code", "zipcode", "postal code"],
    "phone": ["phone", "phone number", "business phone", "main phone"],
    "email": ["email", "e-mail", "email address"],
    "website": ["website", "web", "url"],
    "contact": ["contact", "contact name", "decision maker", "dm", "name"],
    "title": ["title", "role", "position"],
    "status": [
        "status",
        "stage",
        "status / stage",
        "outcome",
        "result",
        "lead status",
    ],
    "notes": [
        "notes",
        "note",
        "comments",
        "description",
        "field notes",
        "next step",
    ],
    "followup": [
        "follow up",
        "follow-up",
        "follow-up date",
        "followup",
        "next follow up",
        "next follow-up",
        "next_follow_up",
    ],
    "last_visit": [
        "last visit",
        "last interaction",
        "date",
        "visit date",
        "last activity",
    ],
    "priority": ["priority"],
    "area": ["area", "zone", "territory", "route"],
    "restriction": [
        "restriction",
        "do not contact",
        "dnc",
        "contact restriction",
    ],
}


def _norm(h: str) -> str:
    return (
        re.sub(r"\s+", " ", re.sub(r"[_*:]", " ", str(h or ""))).strip().lower()
    )


def map_headers(headers: list[str]) -> dict[str, int]:
    norm = [_norm(h) for h in headers]
    found: dict[str, int] = {}
    for key, names in ALIASES.items():
        for name in names:
            if name in norm and norm.index(name) not in found.values():
                found[key] = norm.index(name)
                break
    # "Name" means the business only if no better business column exists.
    if (
        "name" not in found
        and "contact" in found
        and norm[found["contact"]] == "name"
    ):
        found["name"] = found.pop("contact")
    return found


def stage_from_status(text: str) -> str:
    t = (text or "").lower()
    rules = [
        ("existing customer", "Existing customer"),
        ("customer", "Existing customer"),
        ("installed", "Installed"),
        ("sold", "Signed"),
        ("signed", "Signed"),
        ("sale", "Signed"),
        ("closed won", "Signed"),
        ("roe", "ROE"),
        ("right of entry", "ROE"),
        ("survey", "Site Survey"),
        ("not interested", "Not interested"),
        ("declined", "Not interested"),
        ("closed lost", "Not interested"),
        ("follow", "Follow-up"),
        ("email pending", "Follow-up"),
        ("interested", "Follow-up"),
        ("callback", "Follow-up"),
        ("prospect", "Follow-up"),
        ("not home", "Contacted"),
        ("no answer", "Contacted"),
        ("visited", "Contacted"),
        ("attempt", "Contacted"),
        ("contacted", "Contacted"),
    ]
    for needle, stage in rules:
        if needle in t:
            return stage
    return "Prospect"


def _date(v: Any) -> str:
    if v is None or v == "":
        return ""
    if hasattr(v, "date"):
        return v.date().isoformat()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(v))
    if m:
        return m.group(0)
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", str(v))
    if m:
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y  # noqa: PLR2004 (two-digit year)
        return f"{y:04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return ""


def _stable_id(prefix: str, *parts: str) -> str:
    h = hashlib.sha1(
        "|".join(p.lower().strip() for p in parts).encode()
    ).hexdigest()
    return f"{prefix}_{h[:12]}"


def _split_contact(name: str) -> tuple[str, str]:
    name = re.split(r"[;(]", name or "")[0].strip()
    if not name:
        return "", ""
    parts = name.split()
    return parts[0], " ".join(parts[1:])


def _upsert(owner: str, rec: dict[str, Any], defaults: dict[str, str]) -> str:
    s = get_store()
    existing = s.get("businesses", rec["id"])
    if existing and existing.get("owner") != owner:
        rec["id"] = _stable_id("B", owner, rec["id"])
        existing = s.get("businesses", rec["id"])
    doc = existing or {
        "id": rec["id"],
        "owner": owner,
        "created_at": field.now().isoformat(),
        "state": "FL",
    }
    for k in [
        "name",
        "street",
        "unit",
        "phone",
        "email",
        "website",
        "notes",
        "priority",
        "area",
        "restriction",
        "last_visit",
    ]:
        if rec.get(k):
            doc[k] = str(rec[k]).strip()
    doc["city"] = rec.get("city") or doc.get("city") or defaults.get("city", "")
    doc["zip"] = str(
        rec.get("zip") or doc.get("zip") or defaults.get("zip", "")
    )
    # Don't move a stage backwards if the app already advanced it.
    doc["stage"] = field.advance_stage(
        doc.get("stage", ""), rec.get("stage") or "Prospect"
    )
    doc["source"] = rec.get("source", "Imported tracker")
    s.put("businesses", doc)

    if rec.get("followup"):
        tid = _stable_id("T", doc["id"], rec["followup"])
        if not s.get("tasks", tid):
            s.put(
                "tasks",
                {
                    "id": tid,
                    "owner": owner,
                    "business_id": doc["id"],
                    "business_name": doc["name"],
                    "due": rec["followup"],
                    "subject": "Follow up (imported)",
                    "status": "open",
                },
            )
            doc["next_followup"] = rec["followup"]
            s.put("businesses", doc)
    for c in rec.get("contacts", []):
        first, last = _split_contact(c.get("name", ""))
        if not (first or c.get("email") or c.get("phone")):
            continue
        cid = _stable_id("C", doc["id"], c.get("name", ""), c.get("email", ""))
        s.put(
            "contacts",
            {
                "id": cid,
                "owner": owner,
                "business_id": doc["id"],
                "first_name": first,
                "last_name": last,
                "title": c.get("title", ""),
                "phone": c.get("phone", ""),
                "mobile": "",
                "email": c.get("email", ""),
                "website": "",
                "source": "Imported tracker",
                "upload_id": "",
                "created_at": field.now().isoformat(),
            },
        )
    for v in rec.get("history", []):
        vid = _stable_id("V", doc["id"], v["date"], v.get("notes", ""))
        s.put(
            "visits",
            {
                "id": vid,
                "owner": owner,
                "business_id": doc["id"],
                "business_name": doc["name"],
                "date": v["date"],
                "time": "",
                "outcome": "history",
                "dm": v.get("dm", False),
                "card": False,
                "notes": v.get("notes", ""),
                "followup_date": "",
            },
        )
    return doc["id"]


def rows_to_records(rows: list[list[Any]]) -> list[dict[str, Any]]:
    """First row with a business-like column is the header."""
    header_at = next(
        (
            i
            for i, r in enumerate(rows[:15])
            if "name" in map_headers([str(c) for c in r])
        ),
        None,
    )
    if header_at is None:
        raise ValueError(
            "Couldn't find a business name column. Name one column "
            "'Business' and try again."
        )
    cols = map_headers([str(c) for c in rows[header_at]])
    out = []
    for r in rows[header_at + 1 :]:

        def get(key, r=r):
            i = cols.get(key)
            return (
                ""
                if i is None or i >= len(r) or r[i] is None
                else str(r[i]).strip()
            )

        name = get("name")
        if not name:
            continue
        status = get("status")
        out.append(
            {
                "id": _stable_id("B", name, get("street")),
                "name": name,
                "street": get("street"),
                "unit": get("unit"),
                "city": get("city"),
                "zip": get("zip"),
                "phone": get("phone"),
                "email": get("email"),
                "website": get("website"),
                "notes": " | ".join(
                    x
                    for x in [
                        get("notes"),
                        f"Tracker status: {status}" if status else "",
                    ]
                    if x
                ),
                "priority": get("priority"),
                "area": get("area"),
                "restriction": get("restriction"),
                "stage": stage_from_status(status),
                "followup": _date(r[cols["followup"]])
                if "followup" in cols and cols["followup"] < len(r)
                else "",
                "last_visit": _date(r[cols["last_visit"]])
                if "last_visit" in cols and cols["last_visit"] < len(r)
                else "",
                "contacts": [
                    {
                        "name": get("contact"),
                        "title": get("title"),
                        "email": get("email"),
                        "phone": get("phone"),
                    }
                ]
                if get("contact")
                else [],
            }
        )
    return out


def fieldnote_to_records(data: dict) -> list[dict[str, Any]]:
    """The earlier Fieldnote map app's data.json ("prospects" list)."""
    bucket_stage = {
        "customer": "Existing customer",
        "survey": "Site Survey",
        "sale": "Signed",
    }
    out = []
    for p in data.get("prospects", []):
        addrs = p.get("addresses") or []
        street = addrs[0] if addrs and isinstance(addrs[0], str) else ""
        notes = p.get("notes") or []
        notes = " | ".join(notes) if isinstance(notes, list) else str(notes)
        status = p.get("status") or ""
        stage = bucket_stage.get(p.get("bucket", "")) or stage_from_status(
            status
        )
        history = []
        for a in p.get("activities") or []:
            if "door" not in (a.get("type") or "").lower() or not _date(
                a.get("date")
            ):
                continue
            history.append(
                {
                    "date": _date(a["date"]),
                    "dm": (a.get("decision_maker") or "").lower() == "yes",
                    "notes": " | ".join(
                        x for x in [a.get("outcome"), a.get("notes")] if x
                    ),
                }
            )
        out.append(
            {
                "id": "B_" + re.sub(r"\W", "", p.get("id", ""))[-14:]
                if p.get("id")
                else _stable_id("B", p.get("business", ""), street),
                "name": p.get("business", ""),
                "street": street,
                "notes": " | ".join(
                    x
                    for x in [
                        notes,
                        f"Tracker status: {status}" if status else "",
                    ]
                    if x
                ),
                "priority": p.get("priority", ""),
                "area": p.get("area", ""),
                "restriction": p.get("restriction", ""),
                "stage": stage,
                "followup": _date(p.get("next_follow_up")),
                "last_visit": _date(p.get("last_interaction")),
                "contacts": p.get("contact_records") or [],
                "history": history,
                "source": "Fieldnote tracker",
            }
        )
    return [r for r in out if r["name"]]


def parse_file(filename: str, data: bytes) -> list[dict[str, Any]]:
    name = filename.lower()
    if name.endswith(".json"):
        return fieldnote_to_records(json.loads(data))
    if name.endswith(".csv"):
        text = data.decode("utf-8-sig", errors="replace")
        return rows_to_records(list(csv.reader(io.StringIO(text))))
    if name.endswith((".xlsx", ".xlsm")):
        import openpyxl  # noqa: PLC0415

        wb = openpyxl.load_workbook(
            io.BytesIO(data), read_only=True, data_only=True
        )
        best: list[dict[str, Any]] = []
        for ws in wb.worksheets:  # the sheet with the most businesses wins
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            try:
                recs = rows_to_records(rows)
            except ValueError:
                continue
            if len(recs) > len(best):
                best = recs
        if not best:
            raise ValueError("No sheet with a 'Business' column was found.")
        return best
    raise ValueError("Upload a .xlsx, .csv or Fieldnote data.json file.")


def import_file(
    owner: str, filename: str, data: bytes, city: str = "", zip_code: str = ""
) -> dict[str, Any]:
    records = parse_file(filename, data)
    defaults = {"city": city, "zip": zip_code}
    ids = {_upsert(owner, r, defaults) for r in records}
    return {"imported": len(ids), "rows": len(records)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file")
    ap.add_argument("--owner", required=True, help="rep's sign-in email")
    ap.add_argument("--city", default="")
    ap.add_argument("--zip", default="")
    a = ap.parse_args()
    with open(a.file, "rb") as f:
        print(import_file(a.owner, a.file, f.read(), a.city, a.zip))


if __name__ == "__main__":
    main()
