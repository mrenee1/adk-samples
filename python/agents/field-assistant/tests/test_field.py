from datetime import date

import pytest

from field_assistant import emails, field

from .conftest import OWNER


def test_knock_sets_stage_followup_and_task(business):
    v = field.log_visit(OWNER, business["id"], "talked_dm", notes="Owner Jane")
    assert v["dm"] is True
    assert v["followup_date"] > v["date"]
    assert date.fromisoformat(v["followup_date"]).weekday() < 5
    b = field.get_business(OWNER, business["id"])
    assert b["stage"] == "Follow-up"
    assert b["next_followup"] == v["followup_date"]
    tasks = field.open_tasks(OWNER)
    assert [t["business_id"] for t in tasks] == [business["id"]]


def test_new_knock_replaces_open_followup(business):
    field.log_visit(OWNER, business["id"], "gatekeeper")
    field.log_visit(
        OWNER, business["id"], "callback", followup_date="2030-01-02"
    )
    tasks = field.open_tasks(OWNER)
    assert len(tasks) == 1 and tasks[0]["due"] == "2030-01-02"


def test_undo_removes_visit_and_task(business):
    v = field.log_visit(OWNER, business["id"], "interested")
    field.undo_visit(OWNER, v["id"])
    assert field.day_stats(OWNER)["knocks"] == 0
    assert field.open_tasks(OWNER) == []


def test_other_reps_cannot_touch_my_records(business):
    with pytest.raises(KeyError):
        field.get_business("someone@else.com", business["id"])
    with pytest.raises(KeyError):
        field.log_visit("someone@else.com", business["id"], "no_answer")


@pytest.mark.parametrize(
    "current,new,expected",
    [
        ("Prospect", "Contacted", "Contacted"),
        ("ROE", "Follow-up", "ROE"),  # never backwards
        ("Follow-up", "Not interested", "Not interested"),
        ("Site Survey", "Not interested", "Site Survey"),
        ("Not interested", "Signed", "Signed"),  # they came back
        ("Existing customer", "Contacted", "Existing customer"),
    ],
)
def test_advance_stage(current, new, expected):
    assert field.advance_stage(current, new) == expected


def test_stats_and_submit(business):
    field.save_plan(
        OWNER,
        field.today(),
        "Start",
        [
            {"business_id": business["id"], "core": True},
        ],
    )
    other = field.save_business(OWNER, {"name": "Driftwood Gifts"})
    field.save_plan(
        OWNER,
        field.today(),
        "Start",
        [
            {"business_id": business["id"]},
            {"business_id": other["id"]},
        ],
    )
    field.log_visit(OWNER, business["id"], "sold")
    s = field.day_stats(OWNER)
    assert (s["knocks"], s["sales"], s["dm"]) == (1, 1, 1)
    sub = field.submit_day(OWNER, field.today(), wins="Signed Sandbar")
    assert sub["skipped"] == ["Driftwood Gifts"]
    mail = field.summary_email(OWNER, sub)
    assert "1 sales" in mail["subject"]
    assert "Wins: Signed Sandbar" in mail["body"]


def test_suggestions_put_due_followups_first(business):
    later = field.save_business(OWNER, {"name": "Aardvark Cafe"})
    field.log_visit(
        OWNER, business["id"], "callback", followup_date=field.today()
    )
    names = [s["name"] for s in field.suggested_stops(OWNER)]
    assert names[0] == "Sandbar Salon"
    assert later["name"] in names


def test_email_template_drops_empty_lines():
    text = emails.fill(
        "Hi {name},\n\nBusiness: {business}\nNotes: {notes}\n\nThanks,\n{rep}\n{phone}",
        {
            "name": "David",
            "business": "Sandbar",
            "notes": "",
            "rep": "Michelle",
        },
    )
    assert "Notes" not in text
    assert text == "Hi David,\n\nBusiness: Sandbar\n\nThanks,\nMichelle\n"
