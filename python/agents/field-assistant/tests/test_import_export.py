import csv
import io
import json
import zipfile

from field_assistant import field, importer, zoho_export

from .conftest import OWNER

CSV = """\
Business Name,Address,City,Zip,Phone,Email,Contact,Status,Next Follow-up,Notes
Sandbar Salon,1526 3rd St N,Jacksonville Beach,32250,904-555-0100,hi@sandbar.test,Jane Doe,Visited - not home,10/27/2026,Ask for Jane
Bluewater Law,1819 3rd St N,,,,,,Site survey scheduled,,
,,,,,,,,,
"""


def test_csv_import_maps_columns_and_is_idempotent():
    r = importer.import_file(
        OWNER, "t.csv", CSV.encode(), "Fernandina Beach", "32034"
    )
    assert r == {"imported": 2, "rows": 2}
    importer.import_file(OWNER, "t.csv", CSV.encode())
    bs = {b["name"]: b for b in field.list_businesses(OWNER)}
    assert len(bs) == 2
    s = bs["Sandbar Salon"]
    assert (s["city"], s["stage"], s["next_followup"]) == (
        "Jacksonville Beach",
        "Contacted",
        "2026-10-27",
    )
    assert bs["Bluewater Law"]["stage"] == "Site Survey"
    assert bs["Bluewater Law"]["city"] == "Fernandina Beach"  # default filled
    contacts = field.contacts_for(OWNER, s["id"])
    assert [(c["first_name"], c["last_name"]) for c in contacts] == [
        ("Jane", "Doe")
    ]


def test_import_does_not_move_stage_backwards():
    importer.import_file(OWNER, "t.csv", CSV.encode())
    b = next(
        b for b in field.list_businesses(OWNER) if b["name"] == "Bluewater Law"
    )
    field.add_record(OWNER, b["id"], "roe", "Requested", {})
    importer.import_file(OWNER, "t.csv", CSV.encode())
    assert field.get_business(OWNER, b["id"])["stage"] == "ROE"


def test_fieldnote_json_import():
    data = {
        "prospects": [
            {
                "id": "P_abc123",
                "business": "Sue's Market",
                "addresses": ["1941 Citrona Dr"],
                "status": "Email pending",
                "notes": ["Spoke with Val"],
                "restriction": "No outreach unless business re-engages",
                "bucket": "visited",
                "last_interaction": "2026-10-13",
                "contact_records": [
                    {"name": "Brandi; spoke with Val", "email": "info@sue.test"}
                ],
                "activities": [
                    {
                        "date": "2026-10-13",
                        "type": "Recorded door attempt",
                        "outcome": "Email pending",
                        "decision_maker": "Unknown",
                    }
                ],
            }
        ]
    }
    importer.import_file(
        OWNER,
        "data.json",
        json.dumps(data).encode(),
        "Fernandina Beach",
        "32034",
    )
    (b,) = field.list_businesses(OWNER)
    assert b["stage"] == "Follow-up"
    assert b["restriction"].startswith("No outreach")
    assert field.contacts_for(OWNER, b["id"])[0]["first_name"] == "Brandi"
    assert field.day_stats(OWNER, "2026-10-13")["knocks"] == 1


def test_zoho_zip_has_every_module(business):
    field.save_contact(
        OWNER,
        {
            "business_id": business["id"],
            "first_name": "Jane",
            "last_name": "Doe",
        },
    )
    field.log_visit(OWNER, business["id"], "interested")
    field.add_record(OWNER, business["id"], "survey", "Requested", {})
    z = zipfile.ZipFile(io.BytesIO(zoho_export.build_zip(OWNER)))
    assert set(z.namelist()) == {
        "Leads.csv",
        "Accounts.csv",
        "Contacts.csv",
        "Deals.csv",
        "Tasks.csv",
        "Visits.csv",
        "HOW_TO_IMPORT.txt",
    }
    leads = list(
        csv.DictReader(io.StringIO(z.read("Leads.csv").decode("utf-8-sig")))
    )
    assert leads[0]["Company"] == "Sandbar Salon"
    assert leads[0]["Last Name"] == "Doe"
    assert leads[0]["Lead Status"] == "Pre-Qualified"
    deals = list(
        csv.DictReader(io.StringIO(z.read("Deals.csv").decode("utf-8-sig")))
    )
    assert deals[0]["Stage"] == "Site Survey"
