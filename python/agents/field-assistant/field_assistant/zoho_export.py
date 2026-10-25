"""Export everything as Zoho CRM import files (one CSV per module + a guide).

Column headers use Zoho's standard field labels, so the import wizard maps
most of them automatically. Every row carries a "Field App ID" so a second
import can update instead of duplicating (add it as a custom field once).
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, timedelta

from . import field
from .store import get_store

OUTCOME_LABELS = {o["key"]: o["label"] for o in field.OUTCOMES}
OUTCOME_LABELS["history"] = "Earlier visit (imported)"

# Field app stage -> Zoho Lead Status (Path A) and Deal Stage (Path B).
LEAD_STATUS = {
    "Prospect": "Not Contacted",
    "Contacted": "Attempted to Contact",
    "Follow-up": "Contact in Future",
    "Site Survey": "Pre-Qualified",
    "ROE": "Pre-Qualified",
    "Signed": "Pre-Qualified",
    "Installed": "Pre-Qualified",
    "Not interested": "Not Qualified",
    "Existing customer": "Not Qualified",
}
DEAL_STAGES = {"Site Survey", "ROE", "Signed", "Installed"}

GUIDE = """\
HOW TO IMPORT INTO ZOHO CRM
===========================

One-time setup (5 minutes)
--------------------------
1. Setup > Customization > Modules and Fields > Leads, Accounts, Contacts,
   Deals: add a single-line text field named "Field App ID" to each.
   This lets later imports update records instead of duplicating them.
2. Deals > Stage: make sure these stages exist (add any that are missing):
   Site Survey, ROE, Signed, Installed.

Pick ONE path
-------------
Path A: simple (everything is a Lead, convert later in Zoho)
  1. Leads > Import > From file > Leads.csv
  2. Duplicate check: "Field App ID". Mode: "Add as new and update existing".
  3. Map columns (most match automatically). Finish.

Path B: full (Accounts, Contacts, Deals, Tasks, Visits)
  Import in THIS ORDER so the links resolve:
  1. Accounts.csv   (duplicate check: Field App ID)
  2. Contacts.csv   (map "Account Name" to the Accounts lookup)
  3. Deals.csv      (map "Account Name" to the Accounts lookup)
  4. Tasks.csv      (Activities > Tasks; map "Related To" to Accounts)
  5. Visits.csv     (import into Notes, Calls, or a custom "Field Visits"
                     module; "Account Name" links each visit)

Re-importing later
------------------
Export again from the app and repeat the same steps with "update existing".
Nothing in the app changes when you import, so you can retry safely.
"""


def _csv(rows: list[dict], headers: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=headers, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def _split_name(c: dict) -> tuple[str, str]:
    return c.get("first_name", ""), c.get("last_name", "") or "(unknown)"


def build(owner: str) -> dict[str, str]:
    """Return {filename: csv text} for everything the rep owns."""
    s = get_store()
    biz = [b for b in s.list("businesses") if b.get("owner") == owner]
    contacts = [c for c in s.list("contacts") if c.get("owner") == owner]
    visits = [v for v in s.list("visits") if v.get("owner") == owner]
    tasks = [t for t in s.list("tasks") if t.get("owner") == owner]
    by_id = {b["id"]: b for b in biz}
    first_contact = {}
    for c in contacts:
        first_contact.setdefault(c["business_id"], c)

    leads, accounts, deals = [], [], []
    for b in biz:
        c = first_contact.get(b["id"], {})
        first, last = _split_name(c) if c else ("", "(unknown)")
        desc = "; ".join(
            x for x in [b.get("notes", ""), f"Stage: {b.get('stage', '')}"] if x
        )
        leads.append(
            {
                "Field App ID": b["id"],
                "Company": b.get("name", ""),
                "First Name": first,
                "Last Name": last,
                "Title": c.get("title", ""),
                "Email": c.get("email") or b.get("email", ""),
                "Phone": c.get("phone") or b.get("phone", ""),
                "Mobile": c.get("mobile", ""),
                "Website": c.get("website") or b.get("website", ""),
                "Street": " ".join(
                    x for x in [b.get("street"), b.get("unit")] if x
                ),
                "City": b.get("city", ""),
                "State": b.get("state", ""),
                "Zip Code": b.get("zip", ""),
                "Lead Source": "Door knock",
                "Lead Status": LEAD_STATUS.get(
                    b.get("stage", ""), "Not Contacted"
                ),
                "Description": desc,
            }
        )
        accounts.append(
            {
                "Field App ID": b["id"],
                "Account Name": b.get("name", ""),
                "Phone": b.get("phone", ""),
                "Website": b.get("website", ""),
                "Billing Street": " ".join(
                    x for x in [b.get("street"), b.get("unit")] if x
                ),
                "Billing City": b.get("city", ""),
                "Billing State": b.get("state", ""),
                "Billing Code": b.get("zip", ""),
                "Description": desc,
            }
        )
        if b.get("stage") in DEAL_STAGES:
            deals.append(
                {
                    "Field App ID": f"{b['id']}-deal",
                    "Deal Name": f"{b.get('name', '')} - Fiber",
                    "Account Name": b.get("name", ""),
                    "Contact Name": " ".join(_split_name(c)).strip()
                    if c
                    else "",
                    "Stage": b["stage"],
                    "Closing Date": (
                        date.today() + timedelta(days=30)
                    ).isoformat(),
                    "Lead Source": "Door knock",
                }
            )

    contact_rows = []
    for c in contacts:
        first, last = _split_name(c)
        contact_rows.append(
            {
                "Field App ID": c["id"],
                "First Name": first,
                "Last Name": last,
                "Account Name": by_id.get(c["business_id"], {}).get("name", ""),
                "Title": c.get("title", ""),
                "Email": c.get("email", ""),
                "Phone": c.get("phone", ""),
                "Mobile": c.get("mobile", ""),
                "Lead Source": c.get("source") or "Door knock",
            }
        )

    task_rows = [
        {
            "Subject": f"{t['subject']}: {t['business_name']}",
            "Due Date": t["due"],
            "Status": "Not Started" if t["status"] == "open" else "Completed",
            "Priority": "High",
            "Related To": t["business_name"],
        }
        for t in tasks
        if t["status"] in ("open", "done")
    ]

    visit_rows = [
        {
            "Date": v["date"],
            "Time": v["time"],
            "Account Name": v["business_name"],
            "Outcome": OUTCOME_LABELS.get(v["outcome"], v["outcome"]),
            "Decision Maker": "Yes" if v["dm"] else "No",
            "Card Captured": "Yes" if v["card"] else "No",
            "Follow-up Date": v["followup_date"],
            "Notes": v["notes"],
        }
        for v in sorted(visits, key=lambda v: (v["date"], v["time"]))
    ]

    return {
        "Leads.csv": _csv(leads, list(leads[0]) if leads else ["Field App ID"]),
        "Accounts.csv": _csv(
            accounts, list(accounts[0]) if accounts else ["Field App ID"]
        ),
        "Contacts.csv": _csv(
            contact_rows,
            [
                "Field App ID",
                "First Name",
                "Last Name",
                "Account Name",
                "Title",
                "Email",
                "Phone",
                "Mobile",
                "Lead Source",
            ],
        ),
        "Deals.csv": _csv(
            deals,
            [
                "Field App ID",
                "Deal Name",
                "Account Name",
                "Contact Name",
                "Stage",
                "Closing Date",
                "Lead Source",
            ],
        ),
        "Tasks.csv": _csv(
            task_rows,
            [
                "Subject",
                "Due Date",
                "Status",
                "Priority",
                "Related To",
            ],
        ),
        "Visits.csv": _csv(
            visit_rows,
            [
                "Date",
                "Time",
                "Account Name",
                "Outcome",
                "Decision Maker",
                "Card Captured",
                "Follow-up Date",
                "Notes",
            ],
        ),
        "HOW_TO_IMPORT.txt": GUIDE,
    }


def build_zip(owner: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in build(owner).items():
            # BOM so Excel opens the CSVs with the right characters.
            z.writestr(name, ("﻿" + text) if name.endswith(".csv") else text)
    return buf.getvalue()
