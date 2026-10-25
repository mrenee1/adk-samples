"""Load fake demo businesses so you can try the app without real data.

    python -m field_assistant.seed --owner me@example.com

Business names, people and phone numbers are made up. The street addresses
are real commercial addresses so the ROE owner lookup has something to find.
"""

from __future__ import annotations

import argparse

from . import field

DEMO = [
    ("Salt Marsh Coffee Co.", "1997 Sadler Rd", "Fernandina Beach", "32034"),
    ("Island Tide Dental", "2149 Sadler Rd", "Fernandina Beach", "32034"),
    ("Pelican Point Pilates", "1408 Sadler Rd", "Fernandina Beach", "32034"),
    ("Harbor Light Insurance", "870 Sadler Rd", "Fernandina Beach", "32034"),
    ("Sandbar Salon", "1526 3rd St N", "Jacksonville Beach", "32250"),
    ("Driftwood Gifts", "1514 3rd St N", "Jacksonville Beach", "32250"),
    ("Seagrass Yoga Studio", "1524 3rd St N", "Jacksonville Beach", "32250"),
    ("Bluewater Law Group", "1819 3rd St N", "Jacksonville Beach", "32250"),
]


def seed(owner: str) -> int:
    existing = {b["name"] for b in field.list_businesses(owner)}
    n = 0
    for i, (name, street, city, zip_code) in enumerate(DEMO):
        if name in existing:
            continue
        field.save_business(
            owner,
            {
                "name": name,
                "street": street,
                "city": city,
                "zip": zip_code,
                "phone": f"(904) 555-01{i:02d}",
                "source": "Demo data",
            },
        )
        n += 1
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", default="me@example.com")
    print(f"Added {seed(ap.parse_args().owner)} demo businesses.")
