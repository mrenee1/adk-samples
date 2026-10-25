"""The Field Assistant agent (ADK).

The phone app works without it: every screen is plain buttons. The agent is
the "Ask" tab for anything quicker to say than to tap ("log no answer at
Milano's", "who do I owe a follow-up?", "get the ROE going for Fortune
Law"). Tools that need a decision from the rep return A2UI sheets, which
the app renders exactly like the button-driven ones.
"""

from __future__ import annotations

from typing import Any

from google.adk.agents import LlmAgent
from google.adk.tools import ToolContext

from . import a2ui, config, emails, field, workflows

LOCAL_USER = config.LOCAL_USER


def _owner(tool_context: ToolContext) -> str:
    # server.py writes the verified sign-in email into state on every run.
    return tool_context.state.get("user") or LOCAL_USER


def _brief(b: dict) -> dict:
    return {
        "business_id": b["id"],
        "name": b.get("name", ""),
        "address": field.full_address(b),
        "stage": b.get("stage", ""),
        "last_visit": b.get("last_visit", ""),
        "next_followup": b.get("next_followup", ""),
        "restriction": b.get("restriction", ""),
    }


def find_business(query: str, tool_context: ToolContext) -> dict[str, Any]:
    """Search the rep's businesses by name or address.

    Args:
        query: Part of the business name or street, e.g. "milano".
    """
    hits = field.list_businesses(_owner(tool_context), query)
    return {"matches": [_brief(b) for b in hits[:8]], "total": len(hits)}


def add_business(
    name: str,
    street: str,
    tool_context: ToolContext,
    city: str = "",
    zip_code: str = "",
    phone: str = "",
) -> dict[str, Any]:
    """Add a walk-in business that isn't in the list yet.

    Args:
        name: Business name.
        street: Street address, e.g. "1526 3rd St N".
        city: City.
        zip_code: ZIP code.
        phone: Business phone, if known.
    """
    b = field.save_business(
        _owner(tool_context),
        {
            "name": name,
            "street": street,
            "city": city,
            "zip": zip_code,
            "phone": phone,
            "source": "Added by assistant",
        },
    )
    return _brief(b)


def log_visit(
    business_id: str,
    outcome: str,
    tool_context: ToolContext,
    talked_to_decision_maker: bool | None = None,
    card_captured: bool = False,
    notes: str = "",
    followup_date: str = "",
) -> dict[str, Any]:
    """Record a door knock.

    Args:
        business_id: From find_business.
        outcome: One of no_answer, gatekeeper, talked_dm, interested,
            callback, not_interested, sold.
        talked_to_decision_maker: Leave unset to use the outcome's default.
        card_captured: True if they got a business card.
        notes: Short note in the rep's words.
        followup_date: YYYY-MM-DD; leave empty for the automatic date.
    """
    v = field.log_visit(
        _owner(tool_context),
        business_id,
        outcome,
        dm=talked_to_decision_maker,
        card=card_captured,
        notes=notes,
        followup_date=followup_date or None,
    )
    return {"logged": v, "today": _progress(_owner(tool_context))}


def _progress(owner: str) -> dict[str, Any]:
    s = field.day_stats(owner)
    s.pop("visits")
    return s


def todays_progress(tool_context: ToolContext) -> dict[str, Any]:
    """Today's knocks, decision-maker talks, follow-ups and sales vs. goal,
    plus this week's totals."""
    owner = _owner(tool_context)
    return {"today": _progress(owner), "week": field.week_stats(owner)}


def follow_ups_due(tool_context: ToolContext) -> dict[str, Any]:
    """Follow-ups that are due today or overdue."""
    return {"due": field.due_followups(_owner(tool_context))}


def scan_business_card(
    business_id: str, upload_id: str, tool_context: ToolContext
) -> dict[str, Any]:
    """Read a business card photo the rep uploaded and show it for checking.

    Args:
        business_id: The business the card belongs to.
        upload_id: The photo's id (given in the rep's message).
    """
    return workflows.start_card_scan(
        _owner(tool_context), business_id, upload_id
    )


def start_roe(business_id: str, tool_context: ToolContext) -> dict[str, Any]:
    """Look up the property owner in county records and prepare the ROE
    request email.

    Args:
        business_id: From find_business.
    """
    return workflows.start_roe(_owner(tool_context), business_id)


def order_site_survey(
    business_id: str, tool_context: ToolContext
) -> dict[str, Any]:
    """Prepare a site survey request with the details pre-filled.

    Args:
        business_id: From find_business.
    """
    return workflows.start_survey(_owner(tool_context), business_id)


def draft_followup_email(
    business_id: str, tool_context: ToolContext
) -> dict[str, Any]:
    """Write the rep's standard follow-up email for a business.

    Args:
        business_id: From find_business.
    """
    owner = _owner(tool_context)
    b = field.get_business(owner, business_id)
    contacts = field.contacts_for(owner, business_id)
    email = emails.followup_email(
        field.get_settings(owner), b, contacts[-1] if contacts else None
    )
    return a2ui.email_card(email, f"followup-{business_id}")


INSTRUCTION = f"""You help a door-to-door business sales rep during the day.
Be brief: they are standing on a sidewalk. One or two short sentences.

- Always call find_business before acting on a business named in words.
  If several match, ask which one (list names and streets).
- If a business has a "restriction", say it before anything else and do
  not suggest outreach that breaks it.
- Logging a knock: map their words to an outcome ({", ".join(field.OUTCOME_KEYS)}).
  "Not home", "closed", "nobody there" -> no_answer. "Left a card with the
  front desk" -> gatekeeper. "Spoke with the owner/manager" -> talked_dm.
- Business card photos arrive as "upload_id=..." in the message: call
  scan_business_card.
- ROE / right of entry / "who owns the building" -> start_roe.
- Site survey -> order_site_survey.
- Follow-up email -> draft_followup_email.
- scan_business_card, start_roe, order_site_survey and draft_followup_email
  show a card on screen. After calling one, say only something like "Check
  the details and tap the button." Never repeat the card's data.
- Never invent phone numbers, emails, owners or dates.
"""

root_agent = LlmAgent(
    name="field_assistant",
    model=config.MODEL,
    description="Field sales helper: log knocks, scan cards, order surveys and ROEs.",
    instruction=INSTRUCTION,
    tools=[
        find_business,
        add_business,
        log_visit,
        todays_progress,
        follow_ups_due,
        scan_business_card,
        start_roe,
        order_site_survey,
        draft_followup_email,
    ],
)
