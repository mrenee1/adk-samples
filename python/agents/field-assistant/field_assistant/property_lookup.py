"""Who owns the building? County property appraiser lookups for ROEs.

Both counties publish parcel data through public ArcGIS map services:

* Duval (Jacksonville, Jax/Atlantic/Neptune Beach): the City of
  Jacksonville geocoder finds the address point, then the parcel under it.
* Nassau (Fernandina Beach, Yulee, Callahan, Hilliard): the county 911
  address points find the address, then the parcel under it.

Using "the parcel under the address point" (instead of matching the parcel's
own situs address) is what makes plazas work: suite 1526 sits on the plaza's
1504 parcel, and the plaza owner is who signs the ROE.

Add a county by writing one ``_lookup_<county>`` function and listing its
ZIP codes in ``COUNTY_ZIPS``.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

import httpx

TIMEOUT = 20.0
# Below this the City geocoder is guessing (wrong street or city).
MIN_GEOCODE_SCORE = 85

COJ = "https://maps.coj.net/coj/rest/services"
NASSAU = (
    "https://maps.ncpafl.com/ncflpa_arcgis/rest/services/nassau/"
    "NassauCountyPublicTaxMap/MapServer"
)

COUNTY_ZIPS = {
    "Nassau": {"32034", "32035", "32009", "32011", "32046", "32097"},
    "Duval": {"32099", *(str(z) for z in range(32201, 32291))},
}
COUNTY_CITIES = {
    "Nassau": {
        "FERNANDINA BEACH",
        "FERNANDINA",
        "YULEE",
        "CALLAHAN",
        "HILLIARD",
        "BRYCEVILLE",
        "AMELIA ISLAND",
    },
    "Duval": {
        "JACKSONVILLE",
        "JACKSONVILLE BEACH",
        "ATLANTIC BEACH",
        "NEPTUNE BEACH",
        "BALDWIN",
    },
}

_DIRS = {
    "N",
    "S",
    "E",
    "W",
    "NE",
    "NW",
    "SE",
    "SW",
    "NORTH",
    "SOUTH",
    "EAST",
    "WEST",
}


def detect_county(city: str = "", zip_code: str = "") -> str:
    z = (zip_code or "")[:5]
    for county, zips in COUNTY_ZIPS.items():
        if z in zips:
            return county
    c = (city or "").strip().upper()
    for county, cities in COUNTY_CITIES.items():
        if c in cities:
            return county
    return ""


def parse_street(street: str) -> tuple[int | None, str]:
    """'1526 3rd St N' -> (1526, '3RD'); 'S 8th St' -> (None, '8TH')."""
    words = re.sub(r"[.,#]", " ", (street or "").upper()).split()
    number = None
    if words and words[0].isdigit():
        number = int(words.pop(0))
    elif words and re.fullmatch(r"\d+[A-Z]", words[0]):  # 2403A
        number = int(re.sub(r"\D", "", words.pop(0)))
    while words and words[0] in _DIRS:
        words.pop(0)
    return number, (words[0] if words else "")


def sunbiz_url(name: str) -> str:
    q = urllib.parse.quote(name or "")
    return (
        "https://search.sunbiz.org/Inquiry/CorporationSearch/SearchResults"
        f"?inquiryType=EntityName&searchTerm={q}"
    )


def is_company(owner: str) -> bool:
    return bool(
        re.search(
            r"\b(LLC|L\.L\.C|INC|CORP|CORPORATION|CO|LP|LLP|LTD|TRUST|"
            r"HOLDINGS|PROPERTIES|PARTNERS|ASSOCIATION|ASSN|COMPANY)\b",
            (owner or "").upper(),
        )
    )


def _query(client: httpx.Client, url: str, params: dict) -> list[dict]:
    r = client.get(url, params={**params, "f": "json"}, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("message", "map service error"))
    return data.get("features", [])


def _parcel_at(client, url, x, y, out_fields) -> dict | None:
    feats = _query(
        client,
        url,
        {
            "geometry": f"{x},{y}",
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": out_fields,
            "returnGeometry": "false",
        },
    )
    return feats[0]["attributes"] if feats else None


def _clean(*parts: Any) -> str:
    return " ".join(str(p).strip() for p in parts if p and str(p).strip())


def _lookup_duval(client, street, city, zip_code) -> dict | None:
    single = ", ".join(
        x for x in [street, city or "Jacksonville", "FL", zip_code] if x
    )
    cands = (
        client.get(
            f"{COJ}/Geocode/COMPOSITE_AddrPtFirst/GeocodeServer/findAddressCandidates",
            params={
                "SingleLine": single,
                "outSR": "4326",
                "maxLocations": 3,
                "f": "json",
            },
            timeout=TIMEOUT,
        )
        .json()
        .get("candidates", [])
    )
    cands = [c for c in cands if c.get("score", 0) >= MIN_GEOCODE_SCORE]
    if not cands:
        return None
    loc = cands[0]["location"]
    a = _parcel_at(
        client,
        f"{COJ}/CityBiz/Parcels/MapServer/0/query",
        loc["x"],
        loc["y"],
        "RE,RE_NOSPACE,LNAMEOWNER,MAILADDR1,MAILADDR2,MAILADDR3,MAILCITY,"
        "MAILSTATE,MAILZIP,STREET_NO,ST_DIR,ST_NAME,ST_TYPE,UNIT_NO,ADDRCITY,"
        "DESCPU,NBBLDGS",
    )
    if not a:
        return None
    re_no = (a.get("RE_NOSPACE") or a.get("RE") or "").replace(" ", "")
    return {
        "county": "Duval",
        "matched_address": cands[0]["address"],
        "parcel_id": a.get("RE", ""),
        "owner": _clean(a.get("LNAMEOWNER")),
        "owner_mailing": _clean(
            a.get("MAILADDR1"),
            a.get("MAILADDR2"),
            a.get("MAILADDR3"),
            a.get("MAILCITY"),
            a.get("MAILSTATE"),
            a.get("MAILZIP"),
        ),
        "parcel_address": _clean(
            a.get("STREET_NO"),
            a.get("ST_DIR"),
            a.get("ST_NAME"),
            a.get("ST_TYPE"),
            a.get("UNIT_NO"),
            a.get("ADDRCITY"),
        ),
        "property_use": _clean(a.get("DESCPU")),
        "appraiser_url": (
            "https://paopropertysearch.coj.net/Basic/Detail.aspx?RE=" + re_no
        ),
    }


def _lookup_nassau(client, street, city, zip_code) -> dict | None:
    number, name = parse_street(street)
    if number is None or not name:
        return None
    feats = _query(
        client,
        f"{NASSAU}/231/query",
        {
            "where": f"ADDRESS={number} AND UPPER(St_Name) LIKE '{name.replace(chr(39), '')}%'",
            "outFields": "FULLADDRESS,PostalCity,ZIP,PIN",
            "returnGeometry": "true",
            "outSR": "4326",
        },
    )
    if not feats:
        return None
    z = (zip_code or "")[:5]
    feats.sort(key=lambda f: 0 if f["attributes"].get("ZIP") == z else 1)
    hit = feats[0]
    g = hit["geometry"]
    a = _parcel_at(
        client,
        f"{NASSAU}/144/query",
        g["x"],
        g["y"],
        "PIN,Name,Maddr_1,M_addr_2,Mcity,Mstate,Mzip,parcel_use_cd,Situs_full",
    )
    if not a:
        return None
    return {
        "county": "Nassau",
        "matched_address": _clean(
            hit["attributes"].get("FULLADDRESS"),
            hit["attributes"].get("PostalCity"),
            hit["attributes"].get("ZIP"),
        ),
        "parcel_id": a.get("PIN", ""),
        "owner": _clean(a.get("Name")),
        "owner_mailing": _clean(
            a.get("Maddr_1"),
            a.get("M_addr_2"),
            a.get("Mcity"),
            a.get("Mstate"),
            a.get("Mzip"),
        ),
        "parcel_address": _clean(a.get("Situs_full")),
        "property_use": f"Use code {a['parcel_use_cd']}"
        if a.get("parcel_use_cd")
        else "",
        # The Nassau appraiser site has no stable deep link; search the PIN.
        "appraiser_url": "https://www.nassauflpa.com/",
    }


_LOOKUPS = {"Duval": _lookup_duval, "Nassau": _lookup_nassau}


def lookup_owner(
    street: str,
    city: str = "",
    zip_code: str = "",
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Return owner-of-record details, or ``found: False`` with a reason.

    Never raises for "not found"; the rep can always fill the card by hand.
    """
    county = detect_county(city, zip_code)
    base = {
        "found": False,
        "county": county,
        "searched": ", ".join(x for x in [street, city, zip_code] if x),
    }
    if county not in _LOOKUPS:
        return {
            **base,
            "reason": "County not supported yet. Check the appraiser site.",
        }
    own = client is None
    client = client or httpx.Client()
    try:
        result = _LOOKUPS[county](client, street, city, zip_code)
    except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as e:
        return {**base, "reason": f"County map service did not answer ({e})."}
    finally:
        if own:
            client.close()
    if not result:
        return {**base, "reason": "Address not found in county records."}
    result.update(found=True, searched=base["searched"])
    result["owner_is_company"] = is_company(result["owner"])
    result["sunbiz_url"] = (
        sunbiz_url(result["owner"]) if result["owner_is_company"] else ""
    )
    return result
