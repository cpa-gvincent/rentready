"""
Public real-estate portal search — Redfin, Zillow, Movoto.

Fetches listings matching a criteria (beds, baths, property type, location)
from publicly accessible search pages and writes structured JSONL records
to the bronze landing directory for the existing pipeline to consume.

Each record is tagged with ``source`` and ``estimate_source`` so the
pipeline can trace provenance.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

# Bronze landing path — matches reso_ingest.DEFAULT_LANDING
LANDING_DIR = os.environ.get("RENTREADY_LANDING", "/tmp/rentready/bronze_landing")

REQUEST_TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


@dataclass
class SearchCriteria:
    city: str = "Richardson"
    state: str = "TX"
    beds: int = 3
    baths: int = 2
    property_type: str = "house"  # house, condo, townhouse
    max_price: Optional[int] = None
    min_price: Optional[int] = None


@dataclass
class Listing:
    source: str
    listing_key: str
    address: str
    city: str
    state: str
    postal_code: str = ""
    list_price: Optional[float] = None
    property_type: str = "house"
    beds: int = 0
    baths: float = 0.0
    sqft: Optional[float] = None
    lot_sqft: Optional[float] = None
    year_built: Optional[int] = None
    url: str = ""
    annual_property_tax: Optional[float] = None
    monthly_hoa: float = 0.0
    has_hoa: bool = False
    apn: str = ""  # parcel number, if available
    # Value estimate for gold pipeline
    value_estimate: Optional[float] = None
    estimate_source: str = "public_search"

    def to_bronze_row(self) -> dict[str, Any]:
        """Convert to a bronze-compatible row that silver can process."""
        d = asdict(self)
        # Map to the field names silver.py expects from bronze:
        d["ParcelNumber"] = self.apn or f"PUBLIC-{self.source}-{self.listing_key}"
        d["ListingKey"] = f"{self.source}_{self.listing_key}"
        d["UnparsedAddress"] = self.address
        d["PostalCode"] = self.postal_code
        d["PropertyType"] = self.property_type
        d["ListPrice"] = self.list_price
        d["TaxAnnualAmount"] = self.annual_property_tax
        d["MonthlyHOAAmt"] = self.monthly_hoa
        d["BedroomsTotal"] = self.beds
        d["BathroomsTotal"] = self.baths
        d["LivingArea"] = self.sqft
        d["source"] = self.source
        d["estimate_source"] = self.estimate_source
        d["value_estimate"] = self.value_estimate or self.list_price
        return d


# --------------------------------------------------------------------------- #
# HTTP helper
# --------------------------------------------------------------------------- #
_session = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/json,*/*"})
        _session = s
    return _session


def _fetch(url: str) -> Optional[str]:
    try:
        resp = _get_session().get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            return resp.text
        logger.warning("%s returned %d", url, resp.status_code)
        return None
    except requests.RequestException as e:
        logger.warning("Failed to fetch %s: %s", url, e)
        return None


# --------------------------------------------------------------------------- #
# Redfin scraper
# --------------------------------------------------------------------------- #
def _redfin_search(criteria: SearchCriteria) -> list[dict]:
    """Search Redfin using their public Stingray API."""
    url = (
        f"https://www.redfin.com/stingray/api/gis"
        f"?al=1"
        f"&market=richardson"
        f"&region_id=17215"
        f"&region_type=6"
        f"&lat=32.9483"
        f"&lng=-96.7299"
        f"&num_homes=50"
        f"&ord=redfin-recommended-asc"
        f"&page_number=1"
        f"&poly=0"
        f"&property_type={criteria.property_type}"
        f"&num_beds={criteria.beds}"
        f"&num_baths={criteria.baths}"
        f"&max_price={criteria.max_price or ''}"
        f"&min_price={criteria.min_price or ''}"
        f"&status=9"
        f"&v=8"
        f"&region_type=6"
    )
    html = _fetch(url)
    if not html:
        return []

    records = []
    try:
        data = json.loads(html)
        homes = data.get("payload", {}).get("homes", []) if isinstance(data, dict) else []
        for h in homes:
            price = h.get("price")
            listing = Listing(
                source="redfin",
                listing_key=str(h.get("id", "")),
                address=h.get("streetLine", ""),
                city=h.get("city", criteria.city),
                state=h.get("state", criteria.state),
                postal_code=h.get("zip", ""),
                list_price=float(price) if price else None,
                property_type=criteria.property_type,
                beds=int(h.get("beds", 0)),
                baths=float(h.get("baths", 0)),
                sqft=float(h.get("sqFt", 0)) if h.get("sqFt") else None,
                lot_sqft=float(h.get("lotSize", 0)) if h.get("lotSize") else None,
                year_built=int(h["yearBuilt"]) if h.get("yearBuilt") else None,
                url=f"https://www.redfin.com{h.get('url', '')}" if h.get("url") else "",
                apn=str(h.get("parcelNumber", "")),
                value_estimate=float(price) if price else None,
            )
            records.append(listing.to_bronze_row())
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning("Redfin parse error: %s", e)

    return records


# --------------------------------------------------------------------------- #
# Zillow scraper
# --------------------------------------------------------------------------- #
def _zillow_search(criteria: SearchCriteria) -> list[dict]:
    """Search Zillow by fetching their search page and extracting embedded data."""
    params = {
        "searchQueryState": json.dumps({
            "pagination": {},
            "isMapVisible": True,
            "mapBounds": {
                "west": -96.83,
                "east": -96.63,
                "south": 32.88,
                "north": 33.02,
            },
            "regionSelection": [
                {"regionId": 43923, "regionType": 6}
            ],
            "filterState": {
                "fr": {"value": True},
                "fsba": {"value": False},
                "fsbo": {"value": False},
                "nc": {"value": False},
                "fore": {"value": False},
                "cmsn": {"value": False},
                "auc": {"value": False},
                "pmf": {"value": False},
                "pf": {"value": False},
                "mf": {"value": False},
                "land": {"value": False},
                "apa": {"value": False},
                "con": {"value": False},
            },
            "isListVisible": True,
        }),
        "wants": json.dumps({"cat1": ["listResults", "mapResults"]}),
        "requestId": 1,
    }
    # Zillow API endpoint
    url = f"https://www.zillow.com/async-create-search-page-state"
    html = _fetch(f"{url}?{urlencode(params)}")
    if not html:
        return []

    records = []
    try:
        data = json.loads(html)
        cat1 = data.get("cat1", {}) if isinstance(data, dict) else {}
        results = cat1.get("searchResults", cat1.get("listResults", []))
        for h in results:
            price_str = h.get("price", "").replace("$", "").replace(",", "").replace("+", "")
            price = float(price_str) if price_str and price_str.replace(".", "").isdigit() else None
            listing = Listing(
                source="zillow",
                listing_key=str(h.get("zpid", "")),
                address=h.get("address", h.get("addressStreet", "")),
                city=h.get("city", criteria.city),
                state=h.get("state", criteria.state),
                postal_code=h.get("zipcode", ""),
                list_price=price,
                property_type=criteria.property_type,
                beds=int(h.get("beds", 0)),
                baths=float(h.get("baths", 0)),
                sqft=float(h.get("area", 0)) if h.get("area") else None,
                url=h.get("detailUrl", ""),
                value_estimate=price,
            )
            records.append(listing.to_bronze_row())
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning("Zillow parse error: %s", e)

    return records


# --------------------------------------------------------------------------- #
# Movoto scraper
# --------------------------------------------------------------------------- #
def _movoto_search(criteria: SearchCriteria) -> list[dict]:
    """Search Movoto by fetching their search results page and parsing HTML."""
    city_slug = f"{criteria.city.lower()}-{criteria.state.lower()}"
    url = (
        f"https://www.movoto.com/{city_slug}"
        f"/{criteria.beds}b-{criteria.baths}b"
        f"/for-sale/"
    )
    html = _fetch(url)
    if not html:
        return []

    records = []
    # Look for embedded JSON in <script> tags
    patterns = [
        r'window\.__INITIAL_STATE__\s*=\s*({.*?});',
        r'<script[^>]*id="__NEXT_DATA__"[^>]*>({.*?})</script>',
        r'<script[^>]*type="application/json"[^>]*>({.*?})</script>',
    ]
    found_data = None
    for pat in patterns:
        m = re.search(pat, html, re.DOTALL)
        if m:
            try:
                found_data = json.loads(m.group(1))
                break
            except json.JSONDecodeError:
                continue

    if found_data and isinstance(found_data, dict):
        listings_data = (
            found_data.get("listings", [])
            or found_data.get("props", {}).get("pageProps", {}).get("listings", [])
            or found_data.get("searchResults", [])
        )
        for h in listings_data if isinstance(listings_data, list) else []:
            listing = Listing(
                source="movoto",
                listing_key=str(h.get("id", h.get("listingId", ""))),
                address=h.get("address", {}).get("streetAddress", "") if isinstance(h.get("address"), dict) else str(h.get("address", "")),
                city=h.get("address", {}).get("addressLocality", criteria.city) if isinstance(h.get("address"), dict) else criteria.city,
                state=h.get("address", {}).get("addressRegion", criteria.state) if isinstance(h.get("address"), dict) else criteria.state,
                postal_code=h.get("address", {}).get("postalCode", "") if isinstance(h.get("address"), dict) else "",
                list_price=float(h.get("price", 0) or 0) or None,
                property_type=criteria.property_type,
                beds=int(h.get("bedrooms", h.get("beds", 0))),
                baths=float(h.get("bathrooms", h.get("baths", 0))),
                sqft=float(h.get("sqft", h.get("livingArea", 0)) or 0) or None,
                url=h.get("url", ""),
                value_estimate=float(h.get("price", 0) or 0) or None,
                estimate_source="public_search",
            )
            records.append(listing.to_bronze_row())

    # Fallback: regex scrape listing cards from HTML
    if not records:
        cards = re.findall(
            r'data-listing-id=["\'](\d+)["\'][^>]*>.*?'
            r'<span[^>]*class=["\'][^"\']*price[^"\']*["\'][^>]*>\$?([\d,]+)',
            html, re.DOTALL,
        )
        for lid, price_str in cards[:30]:
            price = float(price_str.replace(",", ""))
            listing = Listing(
                source="movoto",
                listing_key=lid,
                address="",
                city=criteria.city,
                state=criteria.state,
                list_price=price,
                property_type=criteria.property_type,
                value_estimate=price,
            )
            records.append(listing.to_bronze_row())

    return records


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #
SOURCES = {
    "redfin": _redfin_search,
    "zillow": _zillow_search,
    "movoto": _movoto_search,
}


def search(
    criteria: SearchCriteria,
    *,
    sources: Optional[list[str]] = None,
    landing: str = LANDING_DIR,
    dry_run: bool = False,
) -> int:
    """
    Search public portals for listings matching *criteria*, write JSONL
    records to *landing* (the bronze directory), and return total count.
    """
    if sources is None:
        sources = list(SOURCES)

    all_records: list[dict] = []
    for name in sources:
        fn = SOURCES.get(name)
        if not fn:
            logger.warning("Unknown source: %s", name)
            continue
        try:
            records = fn(criteria)
            logger.info("%s: %d listings", name, len(records))
            all_records.extend(records)
        except Exception:
            logger.exception("%s search failed", name)

    if not all_records:
        logger.info("No listings found from any source")
        return 0

    if not dry_run:
        os.makedirs(landing, exist_ok=True)
        ts = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
        path = os.path.join(landing, f"public_search_{ts}.jsonl")
        with open(path, "w") as f:
            for rec in all_records:
                f.write(json.dumps(rec) + "\n")
        logger.info("Wrote %d records to %s", len(all_records), path)
    else:
        logger.info("Dry-run: %d records would be written", len(all_records))

    return len(all_records)


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point: python -m src.ingestion.public_search"""
    import argparse

    parser = argparse.ArgumentParser(description="Search public real-estate portals")
    parser.add_argument("--city", default="Richardson")
    parser.add_argument("--state", default="TX")
    parser.add_argument("--beds", type=int, default=3)
    parser.add_argument("--baths", type=int, default=2)
    parser.add_argument("--max-price", type=int, default=None)
    parser.add_argument("--min-price", type=int, default=None)
    parser.add_argument("--landing", default=LANDING_DIR)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--source", action="append", choices=list(SOURCES), help="Source(s) to search (default: all)")

    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    criteria = SearchCriteria(
        city=args.city,
        state=args.state,
        beds=args.beds,
        baths=args.baths,
        max_price=args.max_price,
        min_price=args.min_price,
    )

    count = search(
        criteria,
        sources=args.source,
        landing=args.landing,
        dry_run=args.dry_run,
    )
    logger.info("Total: %d listings", count)
    return count


if __name__ == "__main__":
    main()
