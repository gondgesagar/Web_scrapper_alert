"""Debug script to inspect the actual API response structure"""
import json
from scraper import fetch_with_playwright, _normalize_payloads

print("Fetching data from BAANKNET...")
payloads = fetch_with_playwright()
items = _normalize_payloads(payloads)

print(f"\nTotal items fetched: {len(items)}")
print("\n" + "="*80)
print("FIRST 3 ITEMS (full structure):")
print("="*80)

for i, item in enumerate(items[:3]):
    print(f"\n--- ITEM {i+1} ---")
    print(json.dumps(item, indent=2, ensure_ascii=True)[:2000])  # First 2000 chars
    print("\n")

print("\n" + "="*80)
print("CHECKING STATE-RELATED FIELDS IN FIRST 10 ITEMS:")
print("="*80)

for i, item in enumerate(items[:10]):
    if isinstance(item, dict):
        print(f"\nItem {i+1}:")
        # Print all keys
        print(f"  Keys: {list(item.keys())}")
        
        # Look for state-related fields
        for key in item.keys():
            if "state" in key.lower() or "address" in key.lower() or "location" in key.lower():
                print(f"  {key}: {item[key]}")
