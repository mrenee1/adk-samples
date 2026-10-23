"""One FastAPI app: the phone app (static), its REST API, and the agent.

uvicorn field_assistant.server:app --reload --port 8080
"""

from __future__ import annotations

import logging
from typing import Any

from ag_ui.core import RunAgentInput
from ag_ui_adk import ADKAgent, add_adk_fastapi_endpoint
from fastapi import Body, Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import auth, config, emails, field, importer, workflows, zoho_export
from .agent import root_agent
from .store import read_upload, save_upload

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("field_assistant")

app = FastAPI(title="Field Assistant")
User = Depends(auth.verify)


@app.exception_handler(KeyError)
async def _not_found(_: Request, e: KeyError):
    return JSONResponse({"detail": str(e).strip("'\"")}, status_code=404)


@app.exception_handler(ValueError)
async def _bad_request(_: Request, e: ValueError):
    return JSONResponse({"detail": str(e)}, status_code=400)


# --- App shell -------------------------------------------------------------


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return {
        "authMode": config.AUTH_MODE,
        "firebase": config.FIREBASE_WEB_CONFIG,
        "outcomes": field.OUTCOMES,
        "stages": field.STAGES,
    }


@app.get("/api/me")
def me(user: str = User) -> dict[str, Any]:
    return {"user": user, "settings": field.get_settings(user)}


@app.put("/api/settings")
def put_settings(values: dict = Body(...), user: str = User):
    return field.save_settings(user, values)


# --- Plan / Field / Submit -------------------------------------------------


def _stop_view(user: str, stop: dict, visits: list[dict]) -> dict:
    b = field.get_business(user, stop["business_id"])
    mine = [v for v in visits if v["business_id"] == b["id"]]
    return {
        **stop,
        "business": {**b, "address": field.full_address(b)},
        "visits_today": mine,
    }


@app.get("/api/today")
def today(date: str = "", user: str = User) -> dict[str, Any]:
    day = date or field.today()
    plan = field.get_plan(user, day)
    stats = field.day_stats(user, day)
    stops = []
    for s in plan["stops"]:
        try:
            stops.append(_stop_view(user, s, stats["visits"]))
        except KeyError:
            continue  # business was deleted
    planned = {s["business_id"] for s in plan["stops"]}
    walk_ins = sorted({v["business_id"] for v in stats["visits"]} - planned)
    return {
        "date": day,
        "plan": {**plan, "stops": stops},
        "walk_ins": [
            _stop_view(user, {"business_id": b, "core": False}, stats["visits"])
            for b in walk_ins
            if field.get_store().get("businesses", b)
        ],
        "stats": stats,
        "week": field.week_stats(user, day),
        "due": field.due_followups(user, day),
        "submission": field.get_submission(user, day),
    }


@app.get("/api/suggestions")
def suggestions(date: str = "", user: str = User):
    return field.suggested_stops(user, date or None)


@app.put("/api/plan")
def put_plan(body: dict = Body(...), user: str = User):
    return field.save_plan(
        user,
        body.get("date") or field.today(),
        body.get("start", ""),
        body.get("stops", []),
    )


@app.get("/api/businesses")
def businesses(q: str = "", user: str = User):
    return [
        {**b, "address": field.full_address(b)}
        for b in field.list_businesses(user, q)
    ]


@app.post("/api/businesses")
def save_business(body: dict = Body(...), user: str = User):
    b = field.save_business(user, body)
    return {**b, "address": field.full_address(b)}


@app.get("/api/businesses/{business_id}")
def business(business_id: str, user: str = User):
    return field.business_detail(user, business_id)


@app.post("/api/visits")
def post_visit(body: dict = Body(...), user: str = User):
    return field.log_visit(
        user,
        body["business_id"],
        body["outcome"],
        dm=body.get("dm"),
        card=bool(body.get("card")),
        notes=body.get("notes", ""),
        followup_date=body.get("followup_date"),
    )


@app.delete("/api/visits/{visit_id}")
def delete_visit(visit_id: str, user: str = User):
    field.undo_visit(user, visit_id)
    return {"ok": True}


@app.post("/api/tasks/{task_id}/done")
def task_done(task_id: str, user: str = User):
    return field.complete_task(user, task_id)


@app.post("/api/submit")
def submit(body: dict = Body(...), user: str = User):
    sub = field.submit_day(
        user,
        body.get("date") or field.today(),
        body.get("wins", ""),
        body.get("blockers", ""),
    )
    return {"submission": sub, "email": field.summary_email(user, sub)}


# --- Photos, workflows and their buttons -----------------------------------


@app.post("/api/uploads")
async def upload(file: UploadFile = File(...), user: str = User):
    data = await file.read()
    return {
        "upload_id": save_upload(data, file.content_type or "image/jpeg", user)
    }


@app.get("/api/uploads/{upload_id}")
def get_upload(upload_id: str, user: str = User):
    got = read_upload(upload_id)
    if not got:
        raise KeyError("Photo not found")
    return Response(content=got[0], media_type=got[1])


@app.post("/api/workflows/card")
def wf_card(body: dict = Body(...), user: str = User):
    return workflows.start_card_scan(
        user, body["business_id"], body["upload_id"]
    )


@app.post("/api/workflows/roe")
def wf_roe(body: dict = Body(...), user: str = User):
    return workflows.start_roe(user, body["business_id"])


@app.post("/api/workflows/survey")
def wf_survey(body: dict = Body(...), user: str = User):
    return workflows.start_survey(user, body["business_id"])


@app.post("/api/workflows/followup-email")
def wf_followup(body: dict = Body(...), user: str = User):
    b = field.get_business(user, body["business_id"])
    contacts = field.contacts_for(user, b["id"])
    return {
        "email": emails.followup_email(
            field.get_settings(user), b, contacts[-1] if contacts else None
        )
    }


@app.post("/api/actions/{name}")
def action(name: str, body: dict = Body(...), user: str = User):
    handler = workflows.ACTIONS.get(name)
    if handler is None:
        raise KeyError(f"Unknown action {name}")
    return handler(user, body.get("context") or {})


# --- Import / export -------------------------------------------------------


@app.get("/api/export/zoho.zip")
def export_zoho(user: str = User):
    return Response(
        content=zoho_export.build_zip(user),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="zoho-import-{field.today()}.zip"'
        },
    )


@app.post("/api/import")
async def import_tracker(
    file: UploadFile = File(...),
    city: str = Form(""),
    zip_code: str = Form(""),
    user: str = User,
):
    data = await file.read()
    return importer.import_file(user, file.filename or "", data, city, zip_code)


# --- Agent (AG-UI) ---------------------------------------------------------


async def _user_state(request: Request, _: RunAgentInput) -> dict[str, Any]:
    # Overrides anything the browser sent: tools only trust this value.
    return {"user": auth.verify(request)}


agent = ADKAgent(
    adk_agent=root_agent,
    app_name="field_assistant",
    user_id_extractor=lambda inp: (inp.state or {}).get(
        "user", config.LOCAL_USER
    ),
    session_timeout_seconds=3600,
    use_in_memory_services=True,
)
add_adk_fastapi_endpoint(
    app,
    agent,
    path="/api/agent",
    extract_state_from_request=_user_state,
    dependencies=[User],
)

# The phone app. Mounted last so /api/* wins.
app.mount("/", StaticFiles(directory=config.WEB_DIR, html=True), name="web")
