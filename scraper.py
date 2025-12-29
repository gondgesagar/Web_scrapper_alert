import argparse
import hashlib
import json
import os
import re
import smtplib
from email.message import EmailMessage
from pathlib import Path
from datetime import datetime, timedelta
import requests
import time
from bs4 import BeautifulSoup

# In-memory cache for pincode lookups (loaded from/saved to persistent file)
PINCODE_CACHE = {}
PINCODE_CACHE_FILE = Path(".state/pincode_cache.json")

TARGET_URL = "https://baanknet.com/property-listing"
EAUCTIONSINDIA_CITIES = [
    "https://www.eauctionsindia.com/city/bhiwandi",
    "https://www.eauctionsindia.com/city/kolhapur",
    "https://www.eauctionsindia.com/city/kalyan",
    "https://www.eauctionsindia.com/city/latur",
    "https://www.eauctionsindia.com/city/mumbai",
    "https://www.eauctionsindia.com/city/sindhudurg",
    "https://www.eauctionsindia.com/city/solapur",
    "https://www.eauctionsindia.com/city/thane",
    "https://www.eauctionsindia.com/city/satara",
    "https://www.eauctionsindia.com/city/ratnagiri",
    "https://www.eauctionsindia.com/city/raigad",
    "https://www.eauctionsindia.com/city/pune",
]
STATE_SCHEMA_VERSION = 1


def _load_pincode_cache():
    """Load persistent pincode cache from file."""
    global PINCODE_CACHE
    if PINCODE_CACHE_FILE.exists():
        try:
            data = json.loads(PINCODE_CACHE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                PINCODE_CACHE = data
                print(f"Loaded {len(PINCODE_CACHE)} cached pincodes.")
        except Exception as e:
            print(f"Warning: Could not load pincode cache: {e}")
            PINCODE_CACHE = {}
    else:
        PINCODE_CACHE = {}


def _save_pincode_cache():
    """Save in-memory pincode cache to persistent file."""
    try:
        PINCODE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        PINCODE_CACHE_FILE.write_text(
            json.dumps(PINCODE_CACHE, indent=2, ensure_ascii=True),
            encoding="utf-8"
        )
        print(f"Saved {len(PINCODE_CACHE)} pincodes to cache.")
    except Exception as e:
        print(f"Warning: Could not save pincode cache: {e}")


# Persisted set of known Maharashtra pincodes (to avoid repeated per-state API calls)
MAHARASHTRA_PINCODES = set()
MAHARASHTRA_PINCODES_FILE = Path(".state/maharashtra_pincodes.json")


def _load_maharashtra_pincodes():
    """Load persisted Maharashtra pincodes or fetch from postalpincode API if missing."""
    global MAHARASHTRA_PINCODES
    if MAHARASHTRA_PINCODES_FILE.exists():
        try:
            data = json.loads(MAHARASHTRA_PINCODES_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                MAHARASHTRA_PINCODES = set(str(x) for x in data)
                print(f"Loaded {len(MAHARASHTRA_PINCODES)} Maharashtra pincodes from cache.")
                return
        except Exception as e:
            print(f"Warning: Could not load Maharashtra pincodes: {e}")

    # Fetch list from API endpoint for Maharashtra with retry logic
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"Fetching Maharashtra pincodes (attempt {attempt + 1}/{max_retries})...")
            resp = requests.get(
                "https://api.postalpincode.in/state/Maharashtra",
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            data = resp.json()
            pincodes = set()
            if isinstance(data, list):
                for entry in data:
                    pos = entry.get("PostOffice") or []
                    for po in pos:
                        p = po.get("Pincode") or po.get("pincode")
                        if p:
                            pincodes.add(str(p))
            MAHARASHTRA_PINCODES = pincodes
            # persist
            try:
                MAHARASHTRA_PINCODES_FILE.parent.mkdir(parents=True, exist_ok=True)
                MAHARASHTRA_PINCODES_FILE.write_text(json.dumps(sorted(list(MAHARASHTRA_PINCODES))), encoding="utf-8")
                print(f"Fetched and saved {len(MAHARASHTRA_PINCODES)} Maharashtra pincodes.")
            except Exception:
                pass
            return  # Success
        except Exception as e:
            wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
            if attempt < max_retries - 1:
                print(f"Warning: failed to fetch Maharashtra pincodes (attempt {attempt + 1}): {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"Warning: failed to fetch Maharashtra pincodes after {max_retries} attempts: {e}")
                # Continue without Maharashtra pincode list (will fall back to address text)
                MAHARASHTRA_PINCODES = set()


def _save_maharashtra_pincodes():
    """Save current MAHARASHTRA_PINCODES to disk."""
    try:
        MAHARASHTRA_PINCODES_FILE.parent.mkdir(parents=True, exist_ok=True)
        MAHARASHTRA_PINCODES_FILE.write_text(json.dumps(sorted(list(MAHARASHTRA_PINCODES))), encoding="utf-8")
    except Exception as e:
        print(f"Warning: Could not save Maharashtra pincodes: {e}")


def _extract_key_value_pairs(obj, prefix=""):
    pairs = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_path = f"{prefix}.{key}" if prefix else str(key)
            pairs.extend(_extract_key_value_pairs(value, key_path))
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            key_path = f"{prefix}[{i}]" if prefix else f"[{i}]"
            pairs.extend(_extract_key_value_pairs(value, key_path))
    else:
        pairs.append((prefix, obj))
    return pairs


def _find_first_value(pairs, key_regexes):
    for key_re in key_regexes:
        regex = re.compile(key_re, re.IGNORECASE)
        for key, value in pairs:
            if regex.search(key):
                return value
    return None


def _collect_date_fields(pairs):
    date_pairs = []
    date_key_re = re.compile(r"(date|deadline|start|end|auction|bid)", re.IGNORECASE)
    for key, value in pairs:
        if date_key_re.search(key) and value not in (None, "", []):
            date_pairs.append({"key": key, "value": value})
    return date_pairs


def _extract_pincode(item):
    """Try to extract a 6-digit Indian pincode from item dict or address text."""
    if not isinstance(item, dict):
        return None

    # look in top-level keys
    keys = [
        "postalCode",
        "postalcode",
        "pincode",
        "pin",
        "zip",
        "zipCode",
        "zipcode",
        "postal_code",
    ]
    for k in keys:
        v = item.get(k)
        if v:
            s = str(v)
            digits = "".join(ch for ch in s if ch.isdigit())
            if len(digits) >= 6:
                return digits[:6]

    # try nested raw fields
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else item
    if isinstance(raw, dict):
        for k in keys:
            v = raw.get(k)
            if v:
                s = str(v)
                digits = "".join(ch for ch in s if ch.isdigit())
                if len(digits) >= 6:
                    return digits[:6]

    # fallback: search address text for 6-digit number
    addr = item.get("address") or item.get("Address") or (raw.get("address") if isinstance(raw, dict) else "")
    if addr:
        m = re.search(r"\b(\d{6})\b", str(addr))
        if m:
            return m.group(1)

    return None


def _pincode_is_maharashtra(pincode):
    """Return True if pincode belongs to Maharashtra using postalpincode.in API. Caches results."""
    if not pincode or not str(pincode).isdigit():
        return False
    p = str(pincode)
    # Fast path: check pre-fetched Maharashtra pincodes
    if p in MAHARASHTRA_PINCODES:
        PINCODE_CACHE[p] = True
        return True
    if p in PINCODE_CACHE:
        return PINCODE_CACHE[p]
    try:
        resp = requests.get(f"https://api.postalpincode.in/pincode/{p}", timeout=10)
        data = resp.json()
        if isinstance(data, list) and data:
            first = data[0]
            if first.get("Status") == "Success":
                post_offices = first.get("PostOffice") or []
                for po in post_offices:
                    state = po.get("State") or ""
                    if "maharashtra" in str(state).lower():
                        PINCODE_CACHE[p] = True
                        return True
    except Exception:
        pass
    PINCODE_CACHE[p] = False
    return False


def _is_maharashtra(item):
    """Check if item is from Maharashtra using several heuristics: state/stateName/stateID, pincode, or address text."""
    if not isinstance(item, dict):
        return False

    # check common state fields
    state_keys = ["state", "State", "stateName", "statename", "stateID", "state_id", "stateCode"]
    for k in state_keys:
        v = item.get(k)
        if not v and isinstance(item.get("raw"), dict):
            v = item.get("raw", {}).get(k)
        if v:
            s = str(v).lower()
            if "maharashtra" in s or s.strip().upper() in ("MH", "MAH"):
                return True

    # check pincode
    pincode = _extract_pincode(item)
    if pincode and _pincode_is_maharashtra(pincode):
        return True

    # check address text
    addr = item.get("address") or item.get("Address") or (item.get("raw") or {}).get("address", "")
    if addr and "maharashtra" in str(addr).lower():
        return True

    return False


def _extract_auction_date(item):
    """Extract auction date from item. Returns datetime object or None."""
    if not isinstance(item, dict):
        return None
    
    # Check various auction date fields
    auction_keys = [
        "auctionStartDateTime",
        "auctionEndDateTime",
        "auction_start_date",
        "auction_end_date",
        "auctionDate",
        "auction_date",
    ]
    
    for key in auction_keys:
        date_str = item.get(key)
        if date_str:
            try:
                # Try ISO format first
                if isinstance(date_str, str):
                    # Handle ISO format with or without timezone
                    if "T" in date_str:
                        date_obj = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    else:
                        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                    return date_obj
            except (ValueError, TypeError):
                continue
    
    return None


def _is_auction_within_month(item):
    """Check if item has auction date within the next 1 month or more."""
    auction_date = _extract_auction_date(item)
    
    if not auction_date:
        return False
    
    # Make both aware for comparison
    now = datetime.now(auction_date.tzinfo) if auction_date.tzinfo else datetime.now()
    one_month_from_now = now + timedelta(days=30)
    
    # Auction should be in the future but not within 1 month
    # Actually re-reading: "upcoming 1 month or more" means >= 1 month away
    return auction_date >= one_month_from_now


def _extract_eauctionsindia_fields(item):
    """Extract fields from eauctionsindia property item."""
    # eauctionsindia items come from HTML parsing
    if not isinstance(item, dict):
        return None
    
    # Try to extract structured data
    pairs = _extract_key_value_pairs(item)
    
    details = item.get("property_name") or item.get("title") or item.get("raw_text", "")[:100] or ""
    
    # Try to find auction/bid dates
    auction_date = None
    auction_date_str = None
    for key in ["auction_date", "bidding_end_date", "e_auction_date"]:
        if key in item:
            auction_date_str = item[key]
            try:
                auction_date = _parse_date_string(item[key])
                if auction_date:
                    break
            except Exception:
                pass
    
    # Extract price/reserve price
    price = item.get("reserve_price") or item.get("upset_price") or item.get("price") or ""
    
    # Extract location from raw_text (Pune is in URL, so extract from city_url)
    location = item.get("location") or item.get("address") or ""
    city_url = item.get("city_url", "")
    if "pune" in city_url.lower():
        location = "Pune, Maharashtra" if not location else location
    
    # Property URL
    link = item.get("property_url") or item.get("url") or ""
    
    # Extract auction dates
    important_dates = []
    for key in ["auction_date", "bidding_start_date", "bidding_end_date", "e_auction_date"]:
        if key in item and item[key]:
            important_dates.append({"key": key, "value": item[key]})
    
    return {
        "emd_cost": item.get("emd") or item.get("emd_amount") or "",
        "details": str(details)[:200],
        "important_dates": important_dates,
        "link": link,
        "photos": item.get("image_url") or item.get("photos") or "",
        "source": "eauctionsindia",
        "auction_date": auction_date_str or auction_date,
        "address": location,
        "stateName": "Maharashtra",
    }


def _parse_date_string(date_str):
    """Try to parse various date string formats."""
    if not date_str:
        return None
    date_str = str(date_str).strip()
    
    # Common formats
    formats = [
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d %b %Y",
        "%d %B %Y",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            pass
    
    # Try ISO format with fromisoformat
    try:
        if "T" in date_str:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        pass
    
    return None


def _normalize_link(link, source=None, city_url=None):
    """Ensure links are absolute for known sources."""
    if not link:
        return ""
    if isinstance(link, str) and link.startswith("http"):
        return link
    s = str(link)
    # eauctionsindia relative links
    if source == "eauctionsindia":
        if s.startswith("/"):
            return "https://www.eauctionsindia.com" + s
        if s.startswith("city"):
            return "https://www.eauctionsindia.com/" + s
        # fallback: if city_url provided, join
        if city_url and s:
            return city_url.rstrip("/") + "/" + s.lstrip("/")
        return "https://www.eauctionsindia.com/" + s.lstrip("/")
    # baanknet
    if source == "baanknet":
        if s.startswith("/"):
            return "https://baanknet.com" + s
        return "https://baanknet.com/" + s.lstrip("/")
    # generic fallback
    if s.startswith("/"):
        return "https://" + s.lstrip("/")
    return s


def _classify_property_type(item):
    """Classify property into a canonical type string."""
    text_sources = []
    if isinstance(item.get("details"), str):
        text_sources.append(item.get("details"))
    raw = item.get("raw") or {}
    if isinstance(raw, dict):
        text_sources.append(raw.get("summaryDesc") or "")
        text_sources.append(raw.get("projectName") or "")
        text_sources.append(raw.get("assetType") or "")
        text_sources.append(raw.get("propertyType") or "")
        text_sources.append(raw.get("category") or "")
        text_sources.append(raw.get("property_name") or "")
    if isinstance(item.get("link"), str):
        text_sources.append(item.get("link"))
    text = " ".join([t for t in text_sources if t]).lower()

    # Priority list and patterns
    mapping = [
        (r"\bflat\b|\bapartment\b|\bflat in\b", "Flat"),
        (r"\bvilla\b", "Villa"),
        (r"\bbungalow\b|\bbunglow\b", "Bungalow"),
        (r"\bplot\b|\bplots\b|\bsite\b", "Plot"),
        (r"\bland\b|\bagricultural\b|\bfarm\b", "Land"),
        (r"\bshop\b|\bshowroom\b|\bcommercial\b|\boffice\b", "Commercial"),
        (r"\bwarehouse\b|\bfactory\b|\bindustrial\b", "Industrial"),
        (r"\bhotel\b|\bguesthouse\b", "Hospitality"),
    ]

    for pat, label in mapping:
        if re.search(pat, text, re.I):
            return label

    # Try to pick common keywords
    if "residential" in text:
        return "Residential"
    if "agri" in text:
        return "Land"

    return "Other"


def _normalize_property_type_inputs(raw_list):
    """Normalize user-provided property-type strings to canonical lower-case keys.

    Accepts values like 'plots', 'land', 'farm hous', 'bunglow' and maps them to
    canonical keys used by the classifier (lower-case): 'plot', 'land', 'farmhouse', 'bungalow'.
    """
    if not raw_list:
        return set()
    mapping = {
        "plots": "plot",
        "plot": "plot",
        "land": "land",
        "farm hous": "farmhouse",
        "farmhouse": "farmhouse",
        "farm house": "farmhouse",
        "farm": "farmhouse",
        "bunglow": "bungalow",
        "bungalow": "bungalow",
        "flat": "flat",
        "apartment": "flat",
        "villa": "villa",
        "bungalow": "bungalow",
        "commercial": "commercial",
    }
    out = set()
    for v in raw_list:
        if not v:
            continue
        key = str(v).strip().lower()
        norm = mapping.get(key, key)
        out.add(norm)
    return out


def _extract_item_fields(item):
    pairs = _extract_key_value_pairs(item)

    emd_cost = _find_first_value(
        pairs,
        [
            r"\bemd\b",
            r"emd[_-]?amount",
            r"earnest[_-]?money",
        ],
    )
    details = _find_first_value(
        pairs,
        [
            r"summarydesc",
            r"address",
            r"projectname",
            r"details",
            r"description",
            r"asset",
            r"property",
            r"title",
        ],
    )
    link = _find_first_value(
        pairs,
        [
            r"link",
            r"url",
            r"document",
            r"property[_-]?url",
        ],
    )
    if link and isinstance(link, str) and link.startswith("Production/"):
        link = f"https://baanknet.com/property-listing"
    
    photos = _find_first_value(
        pairs,
        [
            r"photos",
            r"images",
            r"imageurl",
            r"image[_-]?url",
        ],
    )
    if photos and isinstance(photos, str) and photos.startswith("Production/"):
        photos = f"https://d14q55p4nerl4m.cloudfront.net/{photos}"
    
    important_dates = _collect_date_fields(pairs)

    return {
        "emd_cost": emd_cost,
        "details": details,
        "important_dates": important_dates,
        "link": link,
        "photos": photos,
    }


def _normalize_payloads(payloads):
    items = []
    for payload in payloads:
        if isinstance(payload, dict):
            if isinstance(payload.get("data"), list):
                items.extend(payload["data"])
            elif isinstance(payload.get("content"), list):
                items.extend(payload["content"])
            else:
                items.append(payload)
        elif isinstance(payload, list):
            items.extend(payload)
    return items


def _load_state(state_path):
    if not state_path.exists():
        return {"schema_version": STATE_SCHEMA_VERSION, "items": {}}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {"schema_version": STATE_SCHEMA_VERSION, "items": {}}
    if data.get("schema_version") != STATE_SCHEMA_VERSION:
        return {"schema_version": STATE_SCHEMA_VERSION, "items": {}}
    if "items" not in data or not isinstance(data["items"], dict):
        return {"schema_version": STATE_SCHEMA_VERSION, "items": {}}
    return data


def _save_state(state_path, items_map):
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": STATE_SCHEMA_VERSION, "items": items_map}
    state_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _item_id(item):
    raw = item.get("raw")
    if isinstance(raw, dict):
        if raw.get("propertyId"):
            return str(raw["propertyId"])
        if raw.get("bankPropertyId"):
            return str(raw["bankPropertyId"])
    if item.get("details"):
        return str(item["details"])[:200]
    return hashlib.sha256(json.dumps(item, sort_keys=True).encode("utf-8")).hexdigest()


def _fingerprint_item(item):
    raw = item.get("raw")
    raw_subset = {}
    if isinstance(raw, dict):
        keep_keys = [
            "propertyId",
            "bankPropertyId",
            "projectName",
            "price",
            "summaryDesc",
            "address",
            "bankName",
            "postedOn",
            "inspectionStartDateTime",
            "inspectionEndDateTime",
            "auctionStartDateTime",
            "auctionEndDateTime",
            "emdStartDateTime",
            "emdEndDateTime",
            "photos",
        ]
        for key in keep_keys:
            if key in raw:
                raw_subset[key] = raw[key]
    payload = {
        "emd_cost": item.get("emd_cost"),
        "details": item.get("details"),
        "important_dates": item.get("important_dates"),
        "link": item.get("link"),
        "raw_subset": raw_subset,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return digest


def _format_item_for_email(item):
    """Format item as HTML with embedded images and clickable link."""
    raw = item.get("raw") if isinstance(item, dict) else {}
    summary = item.get("details") or ""
    bank = raw.get("bankName") if isinstance(raw, dict) else ""
    price = raw.get("price") if isinstance(raw, dict) else ""
    posted = raw.get("postedOn") if isinstance(raw, dict) else ""
    link = item.get("link") or ""
    photos = item.get("photos") or ""
    dates = item.get("important_dates") or []
    
    # Format dates
    date_lines = []
    for entry in dates:
        key = entry.get("key")
        value = entry.get("value")
        date_lines.append(f"<li><strong>{key}</strong>: {value}</li>")
    dates_html = "<ul>" + "".join(date_lines) + "</ul>" if date_lines else "<p><em>(none)</em></p>"
    
    # Build HTML
    html = f"""
    <div style="border: 1px solid #ddd; padding: 15px; margin-bottom: 20px; border-radius: 5px;">
        <h3 style="color: #333; margin-top: 0;">{summary}</h3>
        
        <p><strong>Bank:</strong> {bank}</p>
        <p><strong>Price:</strong> {price}</p>
        <p><strong>Posted:</strong> {posted}</p>
        
        <h4>Important Dates:</h4>
        {dates_html}
        
        <p><strong>EMD Cost:</strong> {item.get('emd_cost') or '(not specified)'}</p>
    """
    
    # Add image if available
    if photos:
        if isinstance(photos, str):
            # Handle both single image and list of images
            image_urls = [photos] if not isinstance(photos, list) else photos
            for img_url in image_urls[:3]:  # Limit to 3 images per email
                if isinstance(img_url, str):
                    html += f'<img src="{img_url}" style="max-width: 100%; height: auto; margin: 10px 0; border-radius: 5px;" alt="Property image">'
    
    # Add clickable link
    if link:
        html += f'<p><a href="{link}" style="display: inline-block; padding: 10px 20px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px; margin-top: 10px;">View Full Listing</a></p>'
    
    html += "</div>"
    
    return html


def _send_email(subject, body, is_html=True):
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = os.getenv("SMTP_PORT")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    email_from = os.getenv("EMAIL_FROM")
    email_to = os.getenv("EMAIL_TO")

    if not all([smtp_host, smtp_port, smtp_user, smtp_pass, email_from, email_to]):
        print("Email settings missing; skipping email notification.")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = email_to
    
    if is_html:
        msg.set_content("This email requires HTML support to display properly.")
        msg.add_alternative(body, subtype="html")
    else:
        msg.set_content(body)

    with smtplib.SMTP(smtp_host, int(smtp_port)) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)


def fetch_with_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError(
            "Playwright is required for this target. Install dependencies "
            "with: pip install -r requirements.txt and "
            "python -m playwright install chromium"
        ) from exc

    payloads = []

    def handle_response(response):
        content_type = response.headers.get("content-type", "")
        if "property-listing-data" in response.url and "application/json" in content_type:
            try:
                payloads.append(response.json())
            except Exception:
                pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("response", handle_response)
        page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(5000)
        browser.close()

    return payloads


def fetch_eauctionsindia_with_playwright(cities=None):
    """Fetch properties from eauctionsindia.com for multiple Maharashtra cities."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError(
            "Playwright is required for this target. Install dependencies "
            "with: pip install -r requirements.txt and "
            "python -m playwright install chromium"
        ) from exc

    all_properties = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        cities_to_scrape = cities or EAUCTIONSINDIA_CITIES
        for city_url in cities_to_scrape:
            try:
                print(f"Scraping {city_url}...")
                page = browser.new_page()
                # Use DOMContentLoaded to avoid long networkidle waits; then wait for cards
                try:
                    page.goto(city_url, wait_until="domcontentloaded", timeout=90000)
                except Exception:
                    # fallback to networkidle if domcontentloaded fails
                    page.goto(city_url, wait_until="networkidle", timeout=90000)
                page.wait_for_timeout(3000)
                
                # Remove common ad containers from the DOM to avoid picking up placeholders
                try:
                    selectors = [
                        "div[class*='ezoic']",
                        "div[class*='ad-']",
                        "div[id^='ad']",
                        "ins[data-ad-client]",
                        "div[class*='advert']",
                        "span.ezoic-ad",
                        "div[id^='ezoic']",
                        "div[id^='ezoic-pub-ad-placeholder']",
                        "iframe[src*='ads']",
                        "div[class*='banner']",
                    ]
                    sel = ",".join(selectors)
                    # Remove ad elements, then remove any empty .card containers left behind
                    page.evaluate(
                        "(sel) => {\n                            try { document.querySelectorAll(sel).forEach(e => e.remove()); } catch(e) {}\n                            try { document.querySelectorAll('script').forEach(s => { try { var t = s.textContent || ''; var src = s.src || ''; if(/ezstandalone|showAds|ezoic/i.test(t) || /ezoic|ads|doubleclick|googlesyndication|adservice/i.test(src)) s.remove(); } catch(e) {} }); } catch(e) {}\n                            try { document.querySelectorAll('div.card').forEach(c => { if(!c.textContent || c.textContent.trim().length === 0) c.remove(); }); } catch(e) {}\n                        }",
                        sel,
                    )
                except Exception:
                    # If ad-removal fails, continue with the raw HTML
                    pass

                # Get the HTML and parse with BeautifulSoup
                html_content = page.content()
                soup = BeautifulSoup(html_content, 'html.parser')
                
                # Attempt robust extraction by matching visible text keywords rather than brittle classes.
                property_cards = []
                try:
                    candidate_html_list = page.evaluate("""
                        () => {
                            const keywords = ['Auction ID', 'Reserve Price', 'View More', 'eAuction', 'Auction Date'];
                            const matches = [];
                            const seen = new Set();
                            const els = Array.from(document.querySelectorAll('div, article, section, li'));
                            for (const el of els) {
                                try {
                                    const txt = (el.innerText || '').trim();
                                    if (txt.length < 40) continue;
                                    let hasKeyword = false;
                                    for (const kw of keywords) {
                                        if (txt.indexOf(kw) !== -1) { hasKeyword = true; break; }
                                    }
                                    if (hasKeyword) {
                                        const h = el.outerHTML;
                                        if (!seen.has(h)) { matches.push(h); seen.add(h); }
                                    }
                                } catch(e) {}
                            }
                            return matches.slice(0, 50);
                        }
                    """)
                except Exception as e:
                    print(f"    Error extracting by text-match: {e}")
                    candidate_html_list = []

                if candidate_html_list:
                    print(f"  Found {len(candidate_html_list)} candidate card fragments by text-match")
                    property_cards = [BeautifulSoup(h, 'html.parser').body or BeautifulSoup(h, 'html.parser') for h in candidate_html_list]
                else:
                    # Fallback: try class-based selectors
                    selectors_to_try = [
                        'div.property-card',
                        'div.property-item',
                        'div[data-property-id]',
                        'div.auction-item',
                        'div.listing-card',
                        'article.property',
                        'div.col-md-6',
                        'div.card',
                    ]
                    for selector in selectors_to_try:
                        property_cards = soup.select(selector)
                        if property_cards:
                            print(f"  Found {len(property_cards)} cards with selector: {selector}")
                            break

                    # If still no cards found, try waiting briefly then reparsing
                    if not property_cards:
                        try:
                            page.wait_for_selector('div.card, div.property-card, div.property-item', timeout=5000)
                            html_content = page.content()
                            soup = BeautifulSoup(html_content, 'html.parser')
                            for selector in selectors_to_try:
                                property_cards = soup.select(selector)
                                if property_cards:
                                    print(f"  After waiting, found {len(property_cards)} cards with selector: {selector}")
                                    break
                        except Exception:
                            pass
                
                # Extract property data from cards
                for card in property_cards[:20]:  # Limit to 20 per city
                    try:
                        prop = {}
                        
                        # Try to extract various fields from card HTML
                        # Look for title/property name
                        title_elem = card.find(['h2', 'h3', 'h4', 'span'], class_=re.compile('.*title.*|.*name.*', re.I))
                        if title_elem:
                            prop['property_name'] = title_elem.get_text(strip=True)
                        
                        # Look for price/reserve price
                        price_elem = card.find(string=re.compile(r'(?:₹|Rs\.?|Price|Reserve)', re.I))
                        if price_elem:
                            prop['price'] = price_elem.get_text(strip=True)
                        
                        # Look for auction date
                        date_elem = card.find(string=re.compile(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}'))
                        if date_elem:
                            prop['auction_date'] = date_elem.get_text(strip=True)
                        
                        # Look for property link
                        link_elem = card.find('a', href=True)
                        if link_elem:
                            prop['property_url'] = link_elem['href']
                            if not prop['property_url'].startswith('http'):
                                prop['property_url'] = 'https://www.eauctionsindia.com' + prop['property_url']
                        
                        # Try to get all text as fallback
                        prop['raw_text'] = card.get_text(separator=' ', strip=True)[:300]
                        
                        # Relaxed: add if we found at least a name, URL, or substantial raw text
                        if prop.get('property_name') or prop.get('property_url') or (prop.get('raw_text') and len(prop.get('raw_text')) > 30):
                            prop['source'] = 'eauctionsindia'
                            prop['city_url'] = city_url
                            all_properties.append(prop)
                        else:
                            # Log skipped card HTML for debugging
                            try:
                                snippet = str(card)[:300]
                                print(f"  Skipped card (no name/url): {snippet}")
                            except Exception:
                                pass
                    except Exception as e:
                        print(f"  Error parsing card: {e}")
                        continue
                
                page.close()
                print(f"  Extracted {len(all_properties)} properties so far from {city_url}")
            except Exception as e:
                print(f"Warning: Failed to fetch {city_url}: {e}")
                continue
        
        browser.close()

    print(f"Total eauctionsindia properties fetched: {len(all_properties)}")
    return all_properties


def run(output_path, max_items, state_path, send_email=True, eauctions_cities=None, property_types=None):
    # Load persistent pincode cache at start
    _load_pincode_cache()
    # Load or fetch Maharashtra pincodes list
    _load_maharashtra_pincodes()
    
    # Fetch from both sources
    print("Fetching BAANKNET properties...")
    baanknet_payloads = fetch_with_playwright()
    baanknet_items = _normalize_payloads(baanknet_payloads)
    print(f"BAANKNET: {len(baanknet_items)} properties fetched")
    
    print("Fetching eauctionsindia properties...")
    # Pass through optional city list if provided via run caller
    eauctionsindia_items = fetch_eauctionsindia_with_playwright(cities=eauctions_cities)
    print(f"eauctionsindia: {len(eauctionsindia_items)} properties fetched")
    
    # Combine items from both sources
    all_items = baanknet_items + eauctionsindia_items

    previous_state = _load_state(state_path)
    previous_items = previous_state.get("items", {})

    results = []
    current_items = {}
    new_auctions = []
    
    for item in all_items[:max_items]:
        if not isinstance(item, dict):
            results.append({"raw": item})
            continue
        
        # Determine source and extract fields accordingly
        source = item.get("source", "baanknet")
        
        # Filter BAANKNET for Maharashtra only
        if source != "eauctionsindia" and not _is_maharashtra(item):
            continue
        
        if source == "eauctionsindia":
            # For eauctionsindia, use raw item directly (skip _extract_eauctionsindia_fields filters)
            entry = {
                "details": item.get("property_name") or item.get("raw_text", "")[:100] or "",
                "link": item.get("property_url") or "",
                "photos": item.get("image_url") or item.get("photos") or "",
                "important_dates": [{"key": "auction_date", "value": item.get("auction_date")}] if item.get("auction_date") else [],
                "emd_cost": "",
            }
        else:
            entry = _extract_item_fields(item)
        
        # Ensure metadata
        entry["raw"] = item
        # ensure source marker
        if source == "eauctionsindia":
            entry["source"] = "eauctionsindia"
            # derive city name from city_url if available
            city_url = item.get("city_url") or item.get("city") or ""
            city_name = ""
            try:
                if city_url:
                    city_name = city_url.rstrip("/").split("/")[-1].replace('-', ' ').title()
            except Exception:
                city_name = ""
            entry["city"] = city_name
        else:
            entry["source"] = "baanknet"

        # normalize links
        entry["link"] = _normalize_link(entry.get("link"), source=entry.get("source"), city_url=item.get("city_url"))

        results.append(entry)
        entry_id = _item_id(entry)
        fingerprint = _fingerprint_item(entry)
        
        # Only track items with upcoming auctions
        current_items[entry_id] = fingerprint
        
        # Check if this is a new auction (not in previous log)
        if entry_id not in previous_items:
            new_auctions.append(entry)
        # else: item already seen before, skip to prevent duplicate email

    # Log deduplication stats
    duplicates_skipped = len(current_items) - len(new_auctions)
    print(f"Processing stats: {len(results)} total items, {len(new_auctions)} new, {duplicates_skipped} duplicates skipped")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=True), encoding="utf-8")

    _save_state(state_path, current_items)
    print(f"Saved state with {len(current_items)} total tracked items to {state_path}")

    # Only send an email when there are new auctions
    if send_email and new_auctions:
        # If property_types filter provided, restrict new_auctions to those types
        allowed_set = None
        if property_types:
            # normalize: accept comma-separated or list and map aliases to canonical keys
            if isinstance(property_types, str):
                raw = [p.strip() for p in property_types.split(',') if p.strip()]
            elif isinstance(property_types, (list, tuple, set)):
                raw = [str(p).strip() for p in property_types if str(p).strip()]
            else:
                raw = []
            allowed_set = _normalize_property_type_inputs(raw)
            if allowed_set:
                before = len(new_auctions)
                new_auctions = [e for e in new_auctions if _classify_property_type(e).lower() in allowed_set]
                print(f"Applied property-types filter: {', '.join(raw)} — {len(new_auctions)}/{before} items remain")
        # Classify and group all new auctions by property type across sources/cities
        type_groups = {}
        for e in new_auctions:
            t = _classify_property_type(e)
            type_groups.setdefault(t, []).append(e)

        # Preferred ordering for types
        preferred = ["Flat", "Villa", "Bungalow", "Plot", "Land", "Commercial", "Industrial", "Hospitality", "Residential", "Other"]

        body_sections = []
        subject_parts = []
        total_count = 0

        for t in preferred:
            items = type_groups.get(t, [])
            if not items:
                continue
            total_count += len(items)
            subject_parts.append(f"{t}: {len(items)}")
            body_sections.append(f'<h2 style="color: #333;">🔔 {t} ({len(items)})</h2>')
            # Within each type, list items (they may be from different cities)
            for entry in items:
                # annotate city/source in the details header
                city = entry.get("city") or (entry.get("raw") or {}).get("city_url") or ""
                prefix = ""
                if entry.get("source"):
                    prefix += entry.get("source")
                if city:
                    if prefix:
                        prefix += " — "
                    prefix += city
                if prefix:
                    # Prepend a small subheading
                    body_sections.append(f'<p style="color:#666; font-size:0.95em; margin:6px 0;"><strong>{prefix}</strong></p>')
                body_sections.append(_format_item_for_email(entry))

        if not subject_parts:
            print("No new auctions found; skipping email.")
        else:
            subject = "New Auctions by Type - " + ", ".join(subject_parts)
            body_html = "\n".join(body_sections)
            _send_email(subject, body_html, is_html=True)
    else:
        print("No new auctions found; skipping email.")

    # Save persistent pincode cache and Maharashtra pincodes before returning
    _save_pincode_cache()
    _save_maharashtra_pincodes()

    # Print machine-parsable count for CI workflows
    try:
        print(f"NEW_AUCTIONS_COUNT={len(new_auctions)}")
    except Exception:
        print("NEW_AUCTIONS_COUNT=0")

    return results


def main():
    parser = argparse.ArgumentParser(description="Scrape BAANKNET property listings.")
    parser.add_argument(
        "--output",
        default="data/property_listings.json",
        help="Where to write scraped data JSON.",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=50,
        help="Maximum number of listing items to process.",
    )
    parser.add_argument(
        "--state",
        default=".state/state.json",
        help="Where to store state between runs for change detection.",
    )
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="Do not send email notifications even if changes are detected.",
    )
    parser.add_argument(
        "--cities",
        default=None,
        help="Comma-separated eauctionsindia city URLs (or slugs) to limit scraping (for testing).",
    )
    parser.add_argument(
        "--property-types",
        default=None,
        help="Comma-separated list of property types to include in email (e.g. Plot,Flat,Villa).",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    state_path = Path(args.state)
    # If --cities provided, build a list to pass through to the run() function
    cities_list = None
    if args.cities:
        # Allow either full URLs or city slugs; normalize simple slug input
        raw = [c.strip() for c in args.cities.split(',') if c.strip()]
        # If values look like slugs (no https://), convert to full eauctionsindia URLs
        cities_list = [
            (c if c.startswith('http') else f'https://www.eauctionsindia.com/city/{c}')
            for c in raw
        ]

    results = run(
        output_path,
        args.max_items,
        state_path,
        send_email=not args.no_email,
        eauctions_cities=cities_list,
        property_types=args.property_types,
    )
    print(f"Wrote {len(results)} items to {output_path}")


if __name__ == "__main__":
    main()
