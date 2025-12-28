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

# In-memory cache for pincode lookups (loaded from/saved to persistent file)
PINCODE_CACHE = {}
PINCODE_CACHE_FILE = Path(".state/pincode_cache.json")

TARGET_URL = "https://baanknet.com/property-listing"
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

    # Fetch list from API endpoint for Maharashtra
    try:
        resp = requests.get("https://api.postalpincode.in/state/Maharashtra", timeout=20)
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
    except Exception as e:
        print(f"Warning: failed to fetch Maharashtra pincodes: {e}")


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


def run(output_path, max_items, state_path, send_email=True):
    # Load persistent pincode cache at start
    _load_pincode_cache()
    # Load or fetch Maharashtra pincodes list
    _load_maharashtra_pincodes()
    
    payloads = fetch_with_playwright()
    items = _normalize_payloads(payloads)

    previous_state = _load_state(state_path)
    previous_items = previous_state.get("items", {})

    results = []
    current_items = {}
    new_auctions = []
    
    for item in items[:max_items]:
        if isinstance(item, dict):
            # Filter for Maharashtra only
            if not _is_maharashtra(item):
                continue
            
            # Filter for auctions 1 month or more in the future
            if not _is_auction_within_month(item):
                continue
            
            entry = _extract_item_fields(item)
            entry["raw"] = item
            results.append(entry)
            entry_id = _item_id(entry)
            fingerprint = _fingerprint_item(entry)
            
            # Only track items with upcoming auctions
            current_items[entry_id] = fingerprint
            
            # Check if this is a new auction (not in previous log)
            if entry_id not in previous_items:
                new_auctions.append(entry)
        else:
            results.append({"raw": item})

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=True), encoding="utf-8")

    _save_state(state_path, current_items)

    # Only send an email when there are new auctions
    if send_email and new_auctions:
        subject = f"BAANKNET (Maharashtra): {len(new_auctions)} new auction(s)"
        body_sections = [
            '<h2 style="color: #333;">🔔 BAANKNET - New Auctions (Maharashtra)</h2>',
            '<p style="color: #666;">New property auctions with upcoming dates (1 month or more):</p>',
        ]
        for entry in new_auctions[:50]:
            body_sections.append(_format_item_for_email(entry))
        if len(new_auctions) > 50:
            body_sections.append(f'<p style="color: #999;"><em>...and {len(new_auctions) - 50} more.</em></p>')
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
    args = parser.parse_args()

    output_path = Path(args.output)
    state_path = Path(args.state)
    results = run(output_path, args.max_items, state_path, send_email=not args.no_email)
    print(f"Wrote {len(results)} items to {output_path}")


if __name__ == "__main__":
    main()
