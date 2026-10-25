import httpx
import pytest
from fastapi.testclient import TestClient

from field_assistant import a2ui, card_scanner, property_lookup, server

from .conftest import OWNER


def _ids_resolve(env):
    ops = env["a2ui_operations"]
    assert [next(k for k in o if k != "version") for o in ops] == [
        "createSurface",
        "updateComponents",
        "updateDataModel",
    ]
    comps = ops[1]["updateComponents"]["components"]
    ids = [c["id"] for c in comps]
    assert len(ids) == len(set(ids)) and "root" in ids
    for c in comps:
        for ref in [c.get("child"), *(c.get("children") or [])]:
            if ref:
                assert ref in ids, f"{c['id']} points at missing {ref}"
    return ops[2]["updateDataModel"]["value"]


def test_surfaces_are_well_formed(business):
    biz = {**business, "address": "1526 3rd St N"}
    _ids_resolve(a2ui.card_review(biz, {"first_name": "Jane"}, "U_1"))
    _ids_resolve(a2ui.roe_review(biz, {"found": False, "reason": "x"}, {}))
    _ids_resolve(a2ui.survey_review(biz, None, {}))
    _ids_resolve(a2ui.email_card({"to": "", "subject": "s", "body": "b"}, "e1"))


def test_parse_street_and_county():
    assert property_lookup.parse_street("1526 3rd St N") == (1526, "3RD")
    assert property_lookup.parse_street("S 8th Street") == (None, "8TH")
    assert property_lookup.parse_street("2403A 3rd St S") == (2403, "3RD")
    assert property_lookup.detect_county("", "32034") == "Nassau"
    assert property_lookup.detect_county("Jacksonville Beach", "") == "Duval"
    assert property_lookup.detect_county("Orlando", "32801") == ""


def test_nassau_lookup_uses_parcel_under_address_point():
    def handler(request: httpx.Request):
        if "/231/query" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "features": [
                        {
                            "attributes": {
                                "FULLADDRESS": "1997 SADLER RD",
                                "PostalCity": "Fernandina Beach",
                                "ZIP": "32034",
                            },
                            "geometry": {"x": -81.45, "y": 30.64},
                        }
                    ]
                },
            )
        assert request.url.params["geometry"] == "-81.45,30.64"
        return httpx.Response(
            200,
            json={
                "features": [
                    {
                        "attributes": {
                            "PIN": "00-00-30",
                            "Name": "SADLER PLAZA LLC",
                            "Maddr_1": "PO BOX 1",
                            "Mcity": "YULEE",
                            "Mstate": "FL",
                            "Mzip": "32097",
                            "parcel_use_cd": "1600",
                            "Situs_full": "1999 SADLER RD",
                        }
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        r = property_lookup.lookup_owner(
            "1997 Sadler Rd", "Fernandina Beach", "32034", client=client
        )
    assert r["found"] and r["owner"] == "SADLER PLAZA LLC"
    assert r["owner_is_company"] and "SADLER%20PLAZA%20LLC" in r["sunbiz_url"]


def test_lookup_reports_outage_instead_of_raising():
    def handler(request):
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        r = property_lookup.lookup_owner(
            "1997 Sadler Rd", "", "32034", client=client
        )
    assert r["found"] is False and "did not answer" in r["reason"]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        property_lookup,
        "lookup_owner",
        lambda *a, **k: {
            "found": True,
            "county": "Duval",
            "owner": "UBW 1 LLC",
            "owner_mailing": "8650 OLD KINGS RD",
            "parcel_id": "174708 0000",
            "property_use": "Shopping Ctr",
            "appraiser_url": "https://pa.test",
            "sunbiz_url": "https://sunbiz.test",
            "searched": "1526 3rd St N",
        },
    )
    monkeypatch.setattr(
        card_scanner,
        "scan_card",
        lambda data, mime: {
            "first_name": "Jane",
            "last_name": "Doe",
            "title": "Owner",
            "phone": "",
            "mobile": "904-555-0199",
            "email": "jane@sandbar.test",
            "website": "",
            "confidence": "high",
        },
    )
    monkeypatch.setattr(server.config, "LOCAL_USER", OWNER)
    return TestClient(server.app)


def test_card_scan_flow(client, business):
    up = client.post(
        "/api/uploads", files={"file": ("c.jpg", b"\xff\xd8fake", "image/jpeg")}
    ).json()
    env = client.post(
        "/api/workflows/card",
        json={"business_id": business["id"], "upload_id": up["upload_id"]},
    ).json()
    form = _ids_resolve(env)["form"]
    assert form["first_name"] == "Jane"
    r = client.post(
        "/api/actions/save_contact",
        json={
            "context": {
                **form,
                "business_id": business["id"],
                "upload_id": up["upload_id"],
            }
        },
    ).json()
    assert r["message"] == "Saved Jane Doe."
    detail = client.get(f"/api/businesses/{business['id']}").json()
    assert detail["contacts"][0]["mobile"] == "904-555-0199"
    assert detail["email"] == "jane@sandbar.test"  # filled from the card


def test_roe_flow_builds_email_and_moves_stage(client, business):
    client.put(
        "/api/settings",
        json={"roe_to_email": "david@iq.test", "rep_name": "Michelle"},
    )
    env = client.post(
        "/api/workflows/roe", json={"business_id": business["id"]}
    ).json()
    data = _ids_resolve(env)
    r = client.post(
        "/api/actions/draft_roe_email",
        json={
            "context": {
                **data["form"],
                "site_contact": "Jane 904-555-0199",
                "business_id": business["id"],
                "county": "Duval",
            }
        },
    ).json()
    assert r["email"]["to"] == "david@iq.test"
    assert (
        "UBW 1 LLC" in r["email"]["body"]
        and "Jane 904-555-0199" in r["email"]["body"]
    )
    assert r["email"]["body"].rstrip().endswith("Michelle")
    assert (
        client.get(f"/api/businesses/{business['id']}").json()["stage"] == "ROE"
    )


def test_survey_form_mode_returns_filled_link(client, business):
    client.put(
        "/api/settings",
        json={
            "survey_mode": "form",
            "survey_form_url": "https://forms.test/?b={business}&a={address}",
        },
    )
    r = client.post(
        "/api/actions/request_survey",
        json={"context": {"business_id": business["id"]}},
    ).json()
    assert r["url"].startswith("https://forms.test/?b=Sandbar%20Salon&a=1526")
    assert client.get("/api/today").json()["stats"]["surveys"] == 1
