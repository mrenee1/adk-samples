"""Day-to-day logic shared by the phone app (REST) and the agent (tools).

Every record carries an ``owner`` (the signed-in rep's email), and every
read is filtered by it, so two reps can share one deployment.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from . import config
from .store import get_store, new_id

# The buttons a rep taps after each knock. ``followup_days`` pre-fills the
# follow-up date; ``dm`` pre-checks "talked to decision maker".
OUTCOMES: list[dict[str, Any]] = [
    {"key": "no_answer", "label": "No answer", "followup_days": 2, "dm": False},
    {
        "key": "gatekeeper",
        "label": "Gatekeeper",
        "followup_days": 3,
        "dm": False,
    },
    {
        "key": "talked_dm",
        "label": "Talked to DM",
        "followup_days": 3,
        "dm": True,
    },
    {
        "key": "interested",
        "label": "Interested",
        "followup_days": 2,
        "dm": True,
    },
    {"key": "callback", "label": "Call back", "followup_days": 2, "dm": False},
    {
        "key": "not_interested",
        "label": "Not interested",
        "followup_days": None,
        "dm": False,
    },
    {"key": "sold", "label": "Sold", "followup_days": None, "dm": True},
]
OUTCOME_KEYS = {o["key"]: o for o in OUTCOMES}

STAGES = [
    "Prospect",
    "Contacted",
    "Follow-up",
    "Site Survey",
    "ROE",
    "Signed",
    "Installed",
    "Not interested",
    "Existing customer",
]

# What a knock outcome does to the business's stage (never moves it back).
_STAGE_AFTER_OUTCOME = {
    "no_answer": "Contacted",
    "gatekeeper": "Contacted",
    "talked_dm": "Follow-up",
    "interested": "Follow-up",
    "callback": "Follow-up",
    "not_interested": "Not interested",
    "sold": "Signed",
}


_ACTIVE = [
    "Prospect",
    "Contacted",
    "Follow-up",
    "Site Survey",
    "ROE",
    "Signed",
    "Installed",
]


def advance_stage(current: str, new: str) -> str:
    """Move forward through the pipeline; never silently go backwards.

    "Not interested" only applies before a deal exists, and any new activity
    re-opens a business that had said no.
    """
    if current not in STAGES:
        return new
    if current == "Existing customer":
        return current
    if new == "Not interested":
        return (
            new
            if current in ("Prospect", "Contacted", "Follow-up")
            else current
        )
    if current == "Not interested":
        return new
    if new == "Existing customer":
        return new
    return new if _ACTIVE.index(new) > _ACTIVE.index(current) else current


def now() -> datetime:
    return datetime.now(config.TIMEZONE)


def today() -> str:
    return now().date().isoformat()


def _mine(col: str, owner: str) -> list[dict[str, Any]]:
    return [d for d in get_store().list(col) if d.get("owner") == owner]


def _get_mine(col: str, doc_id: str, owner: str) -> dict[str, Any]:
    doc = get_store().get(col, doc_id)
    if not doc or doc.get("owner") != owner:
        raise KeyError(f"{col} {doc_id} not found")
    return doc


# --- Settings -------------------------------------------------------------


def get_settings(owner: str) -> dict[str, Any]:
    saved = get_store().get("settings", owner) or {}
    merged = {**config.DEFAULT_APP_SETTINGS, **saved}
    merged["id"] = owner
    if not merged.get("rep_email") and "@" in owner:
        merged["rep_email"] = owner
    return merged


def save_settings(owner: str, values: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        k: v for k, v in values.items() if k in config.DEFAULT_APP_SETTINGS
    }
    if "daily_goal" in allowed:
        allowed["daily_goal"] = max(1, int(allowed["daily_goal"] or 1))
    current = get_store().get("settings", owner) or {"id": owner}
    current.update(allowed)
    current["id"] = owner
    get_store().put("settings", current)
    return get_settings(owner)


# --- Businesses & contacts ------------------------------------------------


def full_address(b: dict[str, Any]) -> str:
    street = " ".join(x for x in [b.get("street"), b.get("unit")] if x)
    city_line = " ".join(
        x for x in [b.get("city"), b.get("state"), b.get("zip")] if x
    )
    return ", ".join(x for x in [street, city_line] if x)


def list_businesses(owner: str, query: str = "") -> list[dict[str, Any]]:
    items = _mine("businesses", owner)
    q = query.strip().lower()
    if q:
        items = [
            b
            for b in items
            if q in (b.get("name", "") + " " + full_address(b)).lower()
        ]
    return sorted(items, key=lambda b: b.get("name", "").lower())


def get_business(owner: str, business_id: str) -> dict[str, Any]:
    return _get_mine("businesses", business_id, owner)


def save_business(owner: str, values: dict[str, Any]) -> dict[str, Any]:
    fields = [
        "name",
        "street",
        "unit",
        "city",
        "state",
        "zip",
        "phone",
        "email",
        "website",
        "stage",
        "priority",
        "notes",
        "area",
        "restriction",
    ]
    if values.get("id"):
        doc = get_business(owner, values["id"])
    else:
        doc = {
            "id": new_id("B"),
            "owner": owner,
            "stage": "Prospect",
            "state": "FL",
            "created_at": now().isoformat(),
            "source": values.get("source", "Added in app"),
        }
    for f in fields:
        if f in values and values[f] is not None:
            doc[f] = str(values[f]).strip()
    if not doc.get("name"):
        raise ValueError("Business name is required")
    if doc.get("stage") not in STAGES:
        doc["stage"] = "Prospect"
    return get_store().put("businesses", doc)


def contacts_for(owner: str, business_id: str) -> list[dict[str, Any]]:
    return [
        c
        for c in _mine("contacts", owner)
        if c.get("business_id") == business_id
    ]


def save_contact(owner: str, values: dict[str, Any]) -> dict[str, Any]:
    business = get_business(owner, values["business_id"])
    doc = {
        "id": values.get("id") or new_id("C"),
        "owner": owner,
        "business_id": business["id"],
        "created_at": now().isoformat(),
    }
    for f in [
        "first_name",
        "last_name",
        "title",
        "phone",
        "mobile",
        "email",
        "website",
        "source",
        "upload_id",
    ]:
        doc[f] = str(values.get(f) or "").strip()
    get_store().put("contacts", doc)
    # Fill gaps on the business from the card, never overwrite.
    changed = False
    for f in ["phone", "email", "website"]:
        if doc[f] and not business.get(f):
            business[f] = doc[f]
            changed = True
    if changed:
        get_store().put("businesses", business)
    return doc


def business_detail(owner: str, business_id: str) -> dict[str, Any]:
    b = get_business(owner, business_id)
    visits = sorted(
        (v for v in _mine("visits", owner) if v["business_id"] == business_id),
        key=lambda v: (v["date"], v.get("time", "")),
        reverse=True,
    )
    records = [
        r for r in _mine("records", owner) if r["business_id"] == business_id
    ]
    return {
        **b,
        "address": full_address(b),
        "contacts": contacts_for(owner, business_id),
        "visits": visits,
        "records": records,
    }


# --- Visits & follow-ups --------------------------------------------------


SATURDAY = 5


def default_followup(outcome: str, on: str | None = None) -> str:
    days = OUTCOME_KEYS.get(outcome, {}).get("followup_days")
    if not days:
        return ""
    start = date.fromisoformat(on or today())
    due = start + timedelta(days=days)
    while due.weekday() >= SATURDAY:  # land on a weekday
        due += timedelta(days=1)
    return due.isoformat()


def log_visit(
    owner: str,
    business_id: str,
    outcome: str,
    dm: bool | None = None,
    card: bool = False,
    notes: str = "",
    followup_date: str | None = None,
) -> dict[str, Any]:
    if outcome not in OUTCOME_KEYS:
        raise ValueError(f"Unknown outcome {outcome!r}")
    business = get_business(owner, business_id)
    stamp = now()
    if dm is None:
        dm = bool(OUTCOME_KEYS[outcome]["dm"])
    if followup_date is None:
        followup_date = default_followup(outcome, stamp.date().isoformat())
    visit = {
        "id": new_id("V"),
        "owner": owner,
        "business_id": business_id,
        "business_name": business.get("name", ""),
        "date": stamp.date().isoformat(),
        "time": stamp.strftime("%H:%M"),
        "outcome": outcome,
        "dm": bool(dm),
        "card": bool(card),
        "notes": notes.strip(),
        "followup_date": followup_date or "",
    }
    get_store().put("visits", visit)

    business["last_visit"] = visit["date"]
    business["last_outcome"] = outcome
    business["stage"] = advance_stage(
        business.get("stage", "Prospect"), _STAGE_AFTER_OUTCOME[outcome]
    )
    # One open follow-up per business: replace the old one.
    for t in open_tasks(owner):
        if t["business_id"] == business_id:
            t["status"] = "replaced"
            get_store().put("tasks", t)
    if visit["followup_date"]:
        get_store().put(
            "tasks",
            {
                "id": new_id("T"),
                "owner": owner,
                "business_id": business_id,
                "business_name": business.get("name", ""),
                "due": visit["followup_date"],
                "subject": f"Follow up: {OUTCOME_KEYS[outcome]['label']}",
                "status": "open",
                "visit_id": visit["id"],
            },
        )
        business["next_followup"] = visit["followup_date"]
    else:
        business["next_followup"] = ""
    get_store().put("businesses", business)
    return visit


def undo_visit(owner: str, visit_id: str) -> None:
    """Remove a mis-tapped knock and the follow-up it created."""
    visit = _get_mine("visits", visit_id, owner)
    for t in _mine("tasks", owner):
        if t.get("visit_id") == visit_id:
            get_store().delete("tasks", t["id"])
    get_store().delete("visits", visit_id)
    business = get_store().get("businesses", visit["business_id"])
    if business and business.get("next_followup") == visit["followup_date"]:
        business["next_followup"] = ""
        get_store().put("businesses", business)


def open_tasks(owner: str) -> list[dict[str, Any]]:
    return sorted(
        (t for t in _mine("tasks", owner) if t.get("status") == "open"),
        key=lambda t: t["due"],
    )


def complete_task(owner: str, task_id: str) -> dict[str, Any]:
    t = _get_mine("tasks", task_id, owner)
    t["status"] = "done"
    return get_store().put("tasks", t)


def due_followups(owner: str, on: str | None = None) -> list[dict[str, Any]]:
    on = on or today()
    return [t for t in open_tasks(owner) if t["due"] <= on]


# --- Surveys & ROEs -------------------------------------------------------


def add_record(
    owner: str, business_id: str, kind: str, status: str, details: dict
) -> dict[str, Any]:
    business = get_business(owner, business_id)
    rec = {
        "id": new_id("R"),
        "owner": owner,
        "business_id": business_id,
        "business_name": business.get("name", ""),
        "kind": kind,
        "status": status,
        "date": today(),
        "details": details,
    }
    get_store().put("records", rec)
    stage = {"survey": "Site Survey", "roe": "ROE"}[kind]
    business["stage"] = advance_stage(business.get("stage", "Prospect"), stage)
    get_store().put("businesses", business)
    return rec


# --- Plan, stats & submit -------------------------------------------------


def _plan_id(owner: str, day: str) -> str:
    return f"{owner}|{day}"


def get_plan(owner: str, day: str | None = None) -> dict[str, Any]:
    day = day or today()
    plan = get_store().get("plans", _plan_id(owner, day))
    if plan is None:
        plan = {
            "id": _plan_id(owner, day),
            "owner": owner,
            "date": day,
            "start": "",
            "stops": [],
        }
    return plan


def save_plan(
    owner: str, day: str, start: str, stops: list[dict[str, Any]]
) -> dict[str, Any]:
    clean = []
    seen = set()
    for s in stops:
        bid = s.get("business_id")
        if not bid or bid in seen:
            continue
        get_business(owner, bid)  # must exist and be mine
        seen.add(bid)
        clean.append({"business_id": bid, "core": bool(s.get("core", True))})
    plan = {
        "id": _plan_id(owner, day),
        "owner": owner,
        "date": day,
        "start": start.strip(),
        "stops": clean,
        "updated_at": now().isoformat(),
    }
    return get_store().put("plans", plan)


def suggested_stops(owner: str, day: str | None = None) -> list[dict[str, Any]]:
    """Follow-ups due first, then active deals, then never-visited."""
    day = day or today()
    due_ids = {t["business_id"]: t["due"] for t in due_followups(owner, day)}
    out = []
    for b in list_businesses(owner):
        if b.get("stage") in ("Not interested", "Installed"):
            continue
        if b["id"] in due_ids:
            out.append((0, due_ids[b["id"]], b, "Follow-up due"))
        elif b.get("stage") in ("Site Survey", "ROE", "Signed"):
            out.append((1, "", b, b["stage"]))
        elif not b.get("last_visit"):
            out.append((2, "", b, "Not visited yet"))
    out.sort(key=lambda x: (x[0], x[1], x[2].get("name", "")))
    return [
        {**b, "address": full_address(b), "reason": why} for _, _, b, why in out
    ]


def day_stats(owner: str, day: str | None = None) -> dict[str, Any]:
    day = day or today()
    visits = [v for v in _mine("visits", owner) if v["date"] == day]
    records = [r for r in _mine("records", owner) if r["date"] == day]
    settings = get_settings(owner)
    return {
        "date": day,
        "goal": int(settings["daily_goal"]),
        "knocks": len(visits),
        "dm": sum(1 for v in visits if v["dm"]),
        "cards": sum(1 for v in visits if v["card"]),
        "followups": sum(1 for v in visits if v["followup_date"]),
        "interested": sum(1 for v in visits if v["outcome"] == "interested"),
        "sales": sum(1 for v in visits if v["outcome"] == "sold"),
        "surveys": sum(1 for r in records if r["kind"] == "survey"),
        "roes": sum(1 for r in records if r["kind"] == "roe"),
        "visits": sorted(visits, key=lambda v: v["time"]),
    }


def week_stats(owner: str, day: str | None = None) -> dict[str, Any]:
    d = date.fromisoformat(day or today())
    monday = d - timedelta(days=d.weekday())
    days = [
        (monday + timedelta(days=i)).isoformat() for i in range(d.weekday() + 1)
    ]
    totals = {"knocks": 0, "dm": 0, "followups": 0, "sales": 0}
    for one in days:
        s = day_stats(owner, one)
        for k in totals:
            totals[k] += s[k]
    return {"from": days[0], "to": days[-1], "days": len(days), **totals}


def get_submission(owner: str, day: str) -> dict[str, Any] | None:
    return get_store().get("submissions", _plan_id(owner, day))


def submit_day(
    owner: str, day: str, wins: str = "", blockers: str = ""
) -> dict[str, Any]:
    stats = day_stats(owner, day)
    plan = get_plan(owner, day)
    visited = {v["business_id"] for v in stats["visits"]}
    skipped = [
        get_business(owner, s["business_id"]).get("name", "")
        for s in plan["stops"]
        if s["business_id"] not in visited
    ]
    sub = {
        "id": _plan_id(owner, day),
        "owner": owner,
        "date": day,
        "stats": {k: v for k, v in stats.items() if k != "visits"},
        "visits": stats["visits"],
        "skipped": skipped,
        "wins": wins.strip(),
        "blockers": blockers.strip(),
        "submitted_at": now().isoformat(),
    }
    get_store().put("submissions", sub)
    return sub


def summary_email(owner: str, sub: dict[str, Any]) -> dict[str, str]:
    s = get_settings(owner)
    st = sub["stats"]
    labels = {o["key"]: o["label"] for o in OUTCOMES}
    lines = [
        f"Daily field report: {s.get('rep_name') or owner}, {sub['date']}",
        "",
        f"Knocks: {st['knocks']} / {st['goal']} goal",
        f"Decision-maker conversations: {st['dm']}",
        f"Follow-ups set: {st['followups']}",
        f"Interested: {st['interested']}   Sales: {st['sales']}",
        f"Site surveys requested: {st['surveys']}   ROEs: {st['roes']}",
        "",
        "Visits:",
    ]
    lines += [
        f"  {v['time']}  {v['business_name']}: {labels[v['outcome']]}"
        + (" (DM)" if v["dm"] else "")
        + (f". {v['notes']}" if v["notes"] else "")
        for v in sub["visits"]
    ] or ["  (none)"]
    if sub["skipped"]:
        lines += ["", "Planned but not visited: " + ", ".join(sub["skipped"])]
    if sub["wins"]:
        lines += ["", "Wins: " + sub["wins"]]
    if sub["blockers"]:
        lines += ["", "Blockers / help needed: " + sub["blockers"]]
    return {
        "to": s.get("manager_email", ""),
        "subject": f"Field report {sub['date']}: {st['knocks']} knocks, "
        f"{st['dm']} DM, {st['sales']} sales",
        "body": "\n".join(lines),
    }
