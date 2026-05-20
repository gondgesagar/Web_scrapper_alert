"""Fetchers for additional Maharashtra auction listing sources."""

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/json,*/*",
}

# Maharashtra city names for filtering aggregator sites
MAHARASHTRA_CITIES = {
    "mumbai", "pune", "thane", "kolhapur", "nashik", "solapur", "satara",
    "ratnagiri", "raigad", "latur", "kalyan", "bhiwandi", "sindhudurg",
    "ahmednagar", "aurangabad", "chhatrapati sambhaji nagar", "nagpur",
    "amravati", "jalgaon", "akola", "yavatmal", "parbhani", "nanded",
    "dhule", "nandurbar", "jalna", "beed", "wardha", "gondia", "chandrapur",
    "bhandara", "buldhana", "washim", "hingoli", "sangli", "palghar",
    "vasai", "virar", "panvel", "ulhasnagar", "dombivli", "ambernath",
    "badlapur", "navi mumbai", "shirdi", "ichalkaranji", "miraj",
}

FINDAUCTION_CITY_SLUGS = {
    "pune": "pune",
    "mumbai": "mumbai",
    "kolhapur": "kolhapur",
    "nashik": "nashik",
    "thane": "mumbai+thane",
    "solapur": "solapur",
    "satara": "satara",
    "ratnagiri": "ratnagiri",
    "raigad": "raigad",
    "latur": "latur",
    "kalyan": "kalyan",
    "bhiwandi": "bhiwandi",
    "sindhudurg": "sindhudurg",
    "ahmednagar": "ahmednagar",
}

MHADA_BOARDS = [
    ("Mumbai", "https://eauction.mhada.gov.in/eAuctionMumbaiMhada"),
    ("Pune", "https://eauction.mhada.gov.in/eAuctionPuneMhada"),
    ("Nashik", "https://eauction.mhada.gov.in/eAuctionNashikMhada"),
    ("Konkan Shops", "https://eauction.mhada.gov.in/eAuctionKonkanMhadaShops"),
]

MSTC_NPA_URL = "https://www.mstcecommerce.com/auctionhome/npa/index.jsp"
MSTC_IBAPI_URL = "https://www.mstcecommerce.com/auctionhome/ibapi/index.jsp"
BANKAUCTIONS_HOME = "https://bankauctions.in/"
FINDAUCTION_BASE = "https://findauction.in"


def _city_is_maharashtra(city):
    if not city:
        return False
    c = str(city).lower().strip()
    if "maharashtra" in c:
        return True
    if c in MAHARASHTRA_CITIES:
        return True
    for name in MAHARASHTRA_CITIES:
        if name in c:
            return True
    return False


def _playwright_browser():
    from playwright.sync_api import sync_playwright

    return sync_playwright()


def fetch_bankauctions(max_pages=None):
    """Fetch listings via BankAuctions.in WordPress REST API."""
    items = []
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    try:
        home = session.get(BANKAUCTIONS_HOME, timeout=45)
        home.raise_for_status()
        nonce_match = re.search(r'"nonce"\s*:\s*"([^"]+)"', home.text)
        if not nonce_match:
            print("  bankauctions: could not find API nonce")
            return items
        nonce = nonce_match.group(1)
        api_resp = session.post(
            f"{BANKAUCTIONS_HOME.rstrip('/')}/wp-json/eauc-table/v1/home_page",
            json={},
            headers={
                "Content-Type": "application/json",
                "X-WP-Nonce": nonce,
            },
            timeout=60,
        )
        api_resp.raise_for_status()
        data = api_resp.json()
        if not isinstance(data, list):
            print("  bankauctions: unexpected API response")
            return items
        for row in data:
            if not isinstance(row, dict):
                continue
            city = row.get("city") or ""
            if not _city_is_maharashtra(city):
                continue
            url = row.get("url") or ""
            if not url:
                continue
            items.append({
                "source": "bankauctions",
                "property_url": url,
                "property_name": row.get("property_details") or row.get("listing_id") or "",
                "price": row.get("reserve_price") or "",
                "auction_date": row.get("date_and_time_of_auction") or "",
                "application_last_date": row.get("last_date") or "",
                "city": city,
                "bankName": row.get("institution") or "",
                "listing_id": row.get("listing_id") or "",
            })
        print(f"  bankauctions: {len(items)} Maharashtra listings from API ({len(data)} total)")
    except Exception as e:
        print(f"  bankauctions: fetch failed: {e}")
    return items


def fetch_findauction_with_playwright(max_pages_per_city=3):
    """Scrape FindAuction.in city listing pages."""
    items = []
    try:
        with _playwright_browser() as p:
            browser = p.chromium.launch(headless=True)
            for city_label, slug in FINDAUCTION_CITY_SLUGS.items():
                for page_num in range(1, max_pages_per_city + 1):
                    list_url = f"{FINDAUCTION_BASE}/bank-property/{slug}/all/all/{page_num}"
                    try:
                        page = browser.new_page()
                        page.goto(list_url, wait_until="domcontentloaded", timeout=60000)
                        page.wait_for_timeout(2000)
                        html = page.content()
                        page.close()
                        soup = BeautifulSoup(html, "html.parser")
                        cards = soup.select(".property-list")
                        if not cards:
                            break
                        for card in cards:
                            link_el = card.select_one(".property-list-detail h5 a.linklist, a.linkview")
                            if not link_el or not link_el.get("href"):
                                continue
                            href = link_el["href"].strip()
                            if "/auction/" not in href:
                                continue
                            prop_url = href if href.startswith("http") else urljoin(FINDAUCTION_BASE, href)
                            title = link_el.get_text(strip=True)
                            price_el = card.select_one(".property-list-detail h6")
                            price = price_el.get_text(strip=True) if price_el else ""
                            meta = [li.get_text(strip=True) for li in card.select(".ul_subdesc li")]
                            auction_date = meta[0] if meta else ""
                            items.append({
                                "source": "findauction",
                                "property_url": prop_url,
                                "property_name": title,
                                "price": price,
                                "auction_date": auction_date,
                                "city": city_label.title(),
                                "raw_text": card.get_text(separator=" ", strip=True)[:300],
                            })
                        print(f"  findauction/{slug} page {page_num}: {len(cards)} cards")
                    except Exception as e:
                        print(f"  findauction/{slug} page {page_num}: {e}")
                        break
            browser.close()
    except Exception as e:
        print(f"  findauction: {e}")
    print(f"  findauction: {len(items)} total listings")
    return items


def fetch_mhada_with_playwright():
    """Scrape live tender tables from MHADA e-auction board portals."""
    items = []
    try:
        with _playwright_browser() as p:
            browser = p.chromium.launch(headless=True)
            for board_name, board_url in MHADA_BOARDS:
                entry_url = board_url.rstrip("/") + "/?0"
                try:
                    page = browser.new_page()
                    page.goto(entry_url, wait_until="domcontentloaded", timeout=90000)
                    page.wait_for_timeout(3000)
                    try:
                        page.click("#liveTenders", timeout=5000)
                        page.wait_for_timeout(1500)
                    except Exception:
                        pass
                    html = page.content()
                    page.close()
                    soup = BeautifulSoup(html, "html.parser")
                    table = soup.select_one("#liveTenders table, #id1c, table.table-striped")
                    if not table:
                        print(f"  mhada/{board_name}: no tender table found")
                        continue
                    rows = table.select("tbody tr")
                    count = 0
                    for row in rows:
                        cells = row.select("td")
                        if len(cells) < 2:
                            continue
                        scheme = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                        if not scheme or scheme.lower() in ("scheme name", "sr. no", "sr no"):
                            continue
                        emd_date = cells[3].get_text(strip=True) if len(cells) > 3 else ""
                        bid_close = cells[4].get_text(strip=True) if len(cells) > 4 else ""
                        items.append({
                            "source": "mhada",
                            "property_url": entry_url,
                            "property_name": scheme,
                            "city": board_name,
                            "auction_date": bid_close,
                            "emd_end_date": emd_date,
                            "address": f"MHADA {board_name}",
                        })
                        count += 1
                    print(f"  mhada/{board_name}: {count} schemes")
                except Exception as e:
                    print(f"  mhada/{board_name}: {e}")
            browser.close()
    except Exception as e:
        print(f"  mhada: {e}")
    print(f"  mhada: {len(items)} total listings")
    return items


def fetch_mstc_with_playwright():
    """Scrape MSTC e-Bikray NPA portal (IBAPI bank auctions are largely suspended)."""
    items = []
    try:
        with _playwright_browser() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(MSTC_NPA_URL, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(3000)
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            for row in soup.select("table tbody tr"):
                cells = row.select("td")
                if len(cells) < 3:
                    continue
                prop_id = cells[0].get_text(strip=True)
                if not prop_id or prop_id.lower() in ("property id", "s.no"):
                    continue
                address = ""
                reserve = ""
                for cell in cells:
                    txt = cell.get_text(strip=True)
                    if "₹" in txt or re.search(r"\d{1,3}(,\d{2,3})+", txt):
                        reserve = txt
                    elif len(txt) > 20:
                        address = txt
                onclick = row.select_one("[onclick*='getPropertyDetails']")
                token = ""
                if onclick:
                    m = re.search(r"getPropertyDetails\('([^']+)'\)", onclick.get("onclick", ""))
                    if m:
                        token = m.group(1)
                link = MSTC_NPA_URL
                if token:
                    link = f"{MSTC_NPA_URL}?prop={token}"
                items.append({
                    "source": "mstc",
                    "property_url": link,
                    "property_name": address or f"Property {prop_id}",
                    "price": reserve,
                    "listing_id": prop_id,
                    "address": address,
                })
            page.close()
            browser.close()
            print(f"  mstc/npa: {len(items)} listings")
    except Exception as e:
        print(f"  mstc: {e}")
    if not items:
        print("  mstc: no NPA listings (IBAPI bank auctions may be suspended)")
    return items
