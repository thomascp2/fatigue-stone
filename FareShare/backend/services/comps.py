"""
Comparable sales analysis — Alabama GIS and ATTOM Data.

Phase 1: Alabama GIS Portal (free, no API key needed for public queries).
Phase 2: ATTOM Data API (paid, more comprehensive).

Over-assessment flag: assessed value >15% above median comp adjusted value.

Alabama assessment ratios by class:
  Class I  (residential):  10% of appraised value
  Class II (agricultural): 10% of appraised value (Current Use) or market rate
  Class III (commercial):  20% of appraised value
  Class IV (utilities):    30% of appraised value
"""

import httpx
import statistics
from typing import Optional

from config import settings

# Alabama class → assessment ratio
ASSESSMENT_RATIOS = {
    "class i": 0.10,
    "class ii": 0.10,
    "class iii": 0.20,
    "class iv": 0.30,
    "residential": 0.10,
    "agricultural": 0.10,
    "commercial": 0.20,
    "utilities": 0.30,
}

FLAGGING_THRESHOLD = 0.15  # flag if >15% over median comp


def _get_assessment_ratio(property_class: Optional[str]) -> float:
    if not property_class:
        return 0.10
    key = property_class.lower()
    for k, v in ASSESSMENT_RATIOS.items():
        if k in key:
            return v
    return 0.10


def fetch_comps_alabama_gis(
    county: str,
    parcel_id: str,
    acreage: Optional[float],
    property_class: Optional[str],
) -> list[dict]:
    """
    Query Madison County / Alabama GIS public parcel search.

    Alabama GIS Portal (alabamagis.com) provides ArcGIS REST endpoints
    for parcel searches. We query the FeatureServer for comparable
    parcels in the same county and property class.

    Returns list of comp dicts: {parcel_id, address, appraised_value, acreage, source}
    """
    # Alabama GIS ArcGIS REST endpoint — publicly accessible
    # Endpoint varies by county; Madison County is well-digitized
    county_endpoints = {
        "madison": "https://gis.madisoncountyal.gov/arcgis/rest/services/Assessment/MadisonParcelData/MapServer/0",
        "limestone": "https://gis.limestonecountyal.com/arcgis/rest/services/Parcels/MapServer/0",
        "morgan": "https://gisweb.morgancountyal.org/arcgis/rest/services/Parcels/MapServer/0",
    }

    county_key = county.lower().replace(" county", "").strip()
    endpoint = county_endpoints.get(county_key)

    if not endpoint:
        # Fall back to Alabama GIS aggregator
        endpoint = f"https://gis.alabamagis.com/arcgis/rest/services/{county_key}/Parcels/MapServer/0"

    # Build where clause for comparable parcels
    # Match same property class, similar acreage (±50%), exclude subject parcel
    acreage_min = (acreage or 1) * 0.5
    acreage_max = (acreage or 1) * 1.5

    # Normalize property class for GIS query
    prop_class_filter = ""
    if property_class:
        pc = property_class.lower()
        if "agri" in pc or "class ii" in pc:
            prop_class_filter = "AND (PROPCLASS = 'II' OR PROPCLASS = '2' OR LAND_USE LIKE '%agri%')"
        elif "resid" in pc or "class i" in pc:
            prop_class_filter = "AND (PROPCLASS = 'I' OR PROPCLASS = '1' OR LAND_USE LIKE '%resid%')"

    where = f"PARCELID <> '{parcel_id}' AND ACRES >= {acreage_min} AND ACRES <= {acreage_max} {prop_class_filter}"

    params = {
        "where": where,
        "outFields": "PARCELID,SITEADDRESS,APPRVALUE,ACRES,PROPCLASS",
        "returnGeometry": "false",
        "f": "json",
        "resultRecordCount": 25,
        "orderByFields": "APPRVALUE DESC",
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(f"{endpoint}/query", params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        # GIS endpoints can be finicky — return empty and log
        print(f"[comps] Alabama GIS fetch failed for {county}: {exc}")
        return []

    comps = []
    for feature in data.get("features", []):
        attrs = feature.get("attributes", {})
        appraised = attrs.get("APPRVALUE") or attrs.get("APPR_VALUE") or attrs.get("APPRAISED_VALUE")
        if not appraised or appraised <= 0:
            continue
        acres = attrs.get("ACRES") or attrs.get("ACREAGE")
        comps.append({
            "parcel_id": attrs.get("PARCELID", ""),
            "address": attrs.get("SITEADDRESS", attrs.get("SITE_ADDRESS", "")),
            "appraised_value": float(appraised),
            "acreage": float(acres) if acres else None,
            "price_per_acre": float(appraised) / float(acres) if acres and float(acres) > 0 else None,
            "data_source": "alabama_gis",
        })

    return comps


def fetch_comps_attom(
    county: str,
    parcel_id: str,
    acreage: Optional[float],
    property_class: Optional[str],
) -> list[dict]:
    """ATTOM Data API comp fetch — requires paid API key."""
    if not settings.attom_api_key:
        return []

    # ATTOM property detail by APN
    headers = {"apikey": settings.attom_api_key, "accept": "application/json"}
    params = {
        "county": county,
        "propertytype": "SFR" if "resid" in (property_class or "").lower() else "FARM",
        "radius": "5",
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(
                "https://api.gateway.attomdata.com/propertyapi/v1.0.0/sale/snapshot",
                headers=headers,
                params=params,
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        print(f"[comps] ATTOM fetch failed: {exc}")
        return []

    comps = []
    for prop in data.get("property", []):
        sale = prop.get("sale", {})
        lot = prop.get("lot", {})
        amount = sale.get("amount", {})
        sale_price = amount.get("saleamt")
        if not sale_price:
            continue
        acres = lot.get("lotsize2")
        comps.append({
            "parcel_id": prop.get("identifier", {}).get("apn", ""),
            "address": prop.get("address", {}).get("oneLine", ""),
            "appraised_value": float(sale_price),
            "acreage": float(acres) if acres else None,
            "price_per_acre": float(sale_price) / float(acres) if acres and float(acres) > 0 else None,
            "sale_date": sale.get("saleTransDate", ""),
            "data_source": "attom",
        })

    return comps


def analyze_assessment(
    assessed_value: float,
    appraised_value: Optional[float],
    county: str,
    parcel_id: str,
    acreage: Optional[float],
    property_class: Optional[str],
) -> dict:
    """
    Core over-assessment detection logic.

    Returns:
      comps: list of comparable sales
      median_comp_appraised: median appraised value of comps
      expected_assessed: what assessed value should be based on comps
      overassessment_pct: how much over the expected assessed value
      is_flagged: True if >15% over
      ratio: Alabama class assessment ratio used
      summary: human-readable finding
    """
    ratio = _get_assessment_ratio(property_class)

    # Fetch comps — GIS first, ATTOM if key available
    comps = fetch_comps_alabama_gis(county, parcel_id, acreage, property_class)
    if not comps and settings.attom_api_key:
        comps = fetch_comps_attom(county, parcel_id, acreage, property_class)

    result = {
        "comps": comps,
        "comp_count": len(comps),
        "median_comp_appraised": None,
        "expected_assessed": None,
        "overassessment_pct": None,
        "is_flagged": False,
        "ratio": ratio,
        "summary": "",
    }

    if not comps:
        result["summary"] = (
            "No comparable sales data available from Alabama GIS. "
            "Manual comp research required before filing appeal."
        )
        return result

    appraised_values = [c["appraised_value"] for c in comps if c["appraised_value"]]
    if not appraised_values:
        result["summary"] = "Comp data returned but no appraised values found."
        return result

    median_comp = statistics.median(appraised_values)
    expected_assessed = median_comp * ratio
    result["median_comp_appraised"] = median_comp
    result["expected_assessed"] = expected_assessed

    if expected_assessed > 0:
        overassessment_pct = (assessed_value - expected_assessed) / expected_assessed
        result["overassessment_pct"] = overassessment_pct
        result["is_flagged"] = overassessment_pct > FLAGGING_THRESHOLD

        if result["is_flagged"]:
            over_dollars = assessed_value - expected_assessed
            result["summary"] = (
                f"OVER-ASSESSED: Current assessed value ${assessed_value:,.0f} is "
                f"{overassessment_pct:.1%} above expected ${expected_assessed:,.0f} "
                f"(based on {len(comps)} comps, median appraised ${median_comp:,.0f}). "
                f"Excess assessment: ${over_dollars:,.0f}. "
                f"Strong grounds for Board of Equalization appeal."
            )
        else:
            result["summary"] = (
                f"Assessment appears within normal range. Current assessed value "
                f"${assessed_value:,.0f} vs expected ${expected_assessed:,.0f} "
                f"({overassessment_pct:.1%} over comp median). "
                f"Below the 15% flagging threshold."
            )

    return result
