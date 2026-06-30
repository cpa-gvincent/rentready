"""
Public real-estate portal search — Redfin, Zillow, Movoto.

Uses Playwright (headless Chromium) to load JavaScript-rendered pages.
If scraping fails (sites use Cloudflare/anti-bot), falls back to
storing the direct search URLs as reference records.

Results are written as JSONL to the configured landing directory
(default: RENTREADY_LANDING or /tmp/rentready/bronze_landing).

When run via GitHub Actions, Playwright is installed with its browser
and the results are committed to ``data/listings.jsonl`` in the repo.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, asdict
from typing import Any, Optional

logger = logging.getLogger(__name__)

LANDING_DIR = os.environ.get("RENTREADY_LANDING", "/tmp/rentready/bronze_landing")
UC_VOLUME_PATH = "/Volumes/gjhinc/ingestion/bronze_landing"


@dataclass
class SearchCriteria:
    city: str = "Richardson"
    state: str = "TX"
    beds: int = 3
    baths: int = 2
    property_type: str = "house"
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
    apn: str = ""
    value_estimate: Optional[float] = None
    estimate_source: str = "public_search"

    def to_bronze_row(self) -> dict[str, Any]:
        d = asdict(self)
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
# Search URLs (always available even when scraping fails)
# --------------------------------------------------------------------------- #
def search_urls(criteria: SearchCriteria) -> dict[str, str]:
    return {
        "redfin": (
            f"https://www.redfin.com/city/17215/TX/{criteria.city}"
            f"/filter/beds={criteria.beds}-baths={criteria.baths}"
            f"-property-type={criteria.property_type}"
        ),
        "zillow": (
            f"https://www.zillow.com/{criteria.city.lower()}-{criteria.state.lower()}"
            f"/{criteria.beds}-beds-{criteria.baths}-baths/"
        ),
        "movoto": (
            f"https://www.movoto.com/{criteria.city.lower()}-{criteria.state.lower()}"
            f"/{criteria.beds}b-{criteria.baths}b/for-sale/"
        ),
    }


# --------------------------------------------------------------------------- #
# Playwright-based scrapers
# --------------------------------------------------------------------------- #
def _with_page(fn):
    """Decorator that provides a Playwright page to *fn*."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("playwright not installed")
        return lambda c: []

    def wrapper(criteria):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 900},
                locale="en-US",
            )
            page = ctx.new_page()
            page.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )
            try:
                return fn(criteria, page)
            finally:
                browser.close()

    return wrapper


def _try_extract_json(html: str, patterns: list[str]) -> Optional[dict]:
    for pat in patterns:
        m = re.search(pat, html, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
    return None


# --------------------------------------------------------------------------- #
# Redfin
# --------------------------------------------------------------------------- #
@_with_page
def _redfin_search(criteria: SearchCriteria, page) -> list[dict]:
    url = (
        f"https://www.redfin.com/city/17215/TX/{criteria.city}"
        f"/filter/beds={criteria.beds}-baths={criteria.baths}"
        f"-property-type={criteria.property_type}"
    )
    records: list[dict] = []

    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(5_000)

    title = page.title()
    if "ERROR" in title or "captcha" in title.lower():
        logger.info("Redfin blocked (title=%s)", title[:60])
        return records

    html = page.content()
    data = _try_extract_json(html, [
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    ])
    if data:
        props = data.get("props", {}).get("pageProps", {})
        results = (
            props.get("searchResults")
            or props.get("listings")
            or props.get("homes")
            or []
        )
        if isinstance(results, str):
            try:
                results = json.loads(results)
            except json.JSONDecodeError:
                results = []
        for h in (results if isinstance(results, list) else []):
            price = h.get("price", h.get("listPrice", 0))
            listing = Listing(
                source="redfin",
                listing_key=str(h.get("id", h.get("listingId", ""))),
                address=(
                    h.get("address", {}).get("streetAddress", "")
                    if isinstance(h.get("address"), dict)
                    else str(h.get("address", ""))
                ),
                city=h.get("city", criteria.city),
                state=h.get("state", criteria.state),
                postal_code=h.get("zipCode", h.get("zip", "")),
                list_price=float(price) if price else None,
                property_type=criteria.property_type,
                beds=int(h.get("beds", h.get("bedrooms", 0))),
                baths=float(h.get("baths", h.get("bathrooms", 0))),
                sqft=float(h.get("sqft", h.get("livingArea", 0)) or 0) or None,
                url=h.get("url", h.get("listingUrl", "")),
                value_estimate=float(price) if price else None,
            )
            records.append(listing.to_bronze_row())

    # DOM fallback
    if not records:
        cards = page.query_selector_all('[data-rf-test-id="homecard"]')
        for card in cards:
            listing = Listing(
                source="redfin",
                listing_key=str(card.get_attribute("id") or ""),
                address="",
                city=criteria.city,
                state=criteria.state,
                list_price=None,
                property_type=criteria.property_type,
            )
            records.append(listing.to_bronze_row())

    return records


# --------------------------------------------------------------------------- #
# Zillow
# --------------------------------------------------------------------------- #
@_with_page
def _zillow_search(criteria: SearchCriteria, page) -> list[dict]:
    url = (
        f"https://www.zillow.com/{criteria.city.lower()}-{criteria.state.lower()}"
        f"/{criteria.beds}-beds-{criteria.baths}-baths/"
    )
    records: list[dict] = []

    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(5_000)

    title = page.title()
    if "captcha" in title.lower() or page.query_selector("#captcha"):
        logger.info("Zillow blocked")
        return records

    html = page.content()
    data = _try_extract_json(html, [
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    ])
    if data:
        props = data.get("props", {}).get("pageProps", {})
        results = (
            props.get("searchPageState", {}).get("cat1", {}).get("searchResults", [])
            or props.get("initialSearchState", {}).get("listings", [])
        )
        for h in results:
            price = _float_from_text(str(h.get("price", h.get("listPrice", ""))))
            listing = Listing(
                source="zillow",
                listing_key=str(h.get("zpid", h.get("id", ""))),
                address=h.get("address", h.get("addressStreet", "")),
                city=h.get("city", criteria.city),
                state=h.get("state", criteria.state),
                postal_code=h.get("zipcode", h.get("zip", "")),
                list_price=price,
                property_type=criteria.property_type,
                beds=int(h.get("beds", h.get("bedrooms", 0))),
                baths=float(h.get("baths", h.get("bathrooms", 0))),
                sqft=_float_from_text(str(h.get("area", h.get("livingArea", "")))),
                url=h.get("detailUrl", h.get("url", "")),
                value_estimate=price,
            )
            records.append(listing.to_bronze_row())

    return records


# --------------------------------------------------------------------------- #
# Movoto
# --------------------------------------------------------------------------- #
@_with_page
def _movoto_search(criteria: SearchCriteria, page) -> list[dict]:
    city_slug = f"{criteria.city.lower()}-{criteria.state.lower()}"
    url = f"https://www.movoto.com/{city_slug}/{criteria.beds}b-{criteria.baths}b/for-sale/"
    records: list[dict] = []

    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(5_000)

    title = page.title()
    if "captcha" in title.lower():
        return records

    html = page.content()
    data = _try_extract_json(html, [
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    ])
    if data:
        props = data.get("props", {}).get("pageProps", {})
        listings_data = props.get("listings", props.get("searchResults", []))
        for h in (listings_data if isinstance(listings_data, list) else []):
            addr = h.get("address", "")
            if isinstance(addr, dict):
                addr = addr.get("streetAddress", "")
            listing = Listing(
                source="movoto",
                listing_key=str(h.get("id", h.get("listingId", ""))),
                address=addr,
                city=h.get("city", criteria.city),
                state=h.get("state", criteria.state),
                postal_code=h.get("zip", h.get("postalCode", "")),
                list_price=float(h.get("price", 0) or 0) or None,
                property_type=criteria.property_type,
                beds=int(h.get("bedrooms", h.get("beds", 0))),
                baths=float(h.get("bathrooms", h.get("baths", 0))),
                sqft=float(h.get("sqft", h.get("livingArea", 0)) or 0) or None,
                url=h.get("url", ""),
                value_estimate=float(h.get("price", 0) or 0) or None,
            )
            records.append(listing.to_bronze_row())

    return records


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _float_from_text(t: str) -> Optional[float]:
    cleaned = re.sub(r"[^0-9.]", "", t)
    return float(cleaned) if cleaned else None


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

    # Add search-URL fallback records for sources with no data
    urls = search_urls(criteria)
    for name in sources:
        fn = SOURCES.get(name)
        if fn is None:
            continue  # unknown sources skipped earlier
        if not any(r.get("source") == name for r in all_records):
            fallback_listing = Listing(
                source=name,
                listing_key=f"{name}_search_url",
                address=f"{criteria.city}, {criteria.state}",
                city=criteria.city,
                state=criteria.state,
                beds=criteria.beds,
                baths=criteria.baths,
                property_type=criteria.property_type,
                estimate_source="public_search_url",
            )
            row = fallback_listing.to_bronze_row()
            row["search_url"] = urls.get(name, "")
            all_records.append(row)

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
    parser.add_argument("--source", action="append", choices=list(SOURCES))
    parser.add_argument("--repo-path", default="", help="Copy output to data/ in repo")

    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    criteria = SearchCriteria(
        city=args.city, state=args.state, beds=args.beds, baths=args.baths,
        max_price=args.max_price, min_price=args.min_price,
    )
    count = search(criteria, sources=args.source, landing=args.landing, dry_run=args.dry_run)

    if args.repo_path and not args.dry_run:
        import shutil
        os.makedirs(args.repo_path, exist_ok=True)
        for f in os.listdir(args.landing):
            if f.endswith(".jsonl"):
                shutil.copy2(os.path.join(args.landing, f), os.path.join(args.repo_path, f))
        logger.info("Copied results to %s", args.repo_path)

    return count


if __name__ == "__main__":
    main()
