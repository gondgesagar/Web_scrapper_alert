#!/usr/bin/env python3
"""Remove invalid postings from saved JSON (no URL, ads, blog links)."""

import argparse
import json
from pathlib import Path

from scraper import _is_valid_url

DEFAULT_PATHS = [
    Path("docs/data/property_listings.json"),
    Path("data/property_listings.json"),
]


def filter_file(path: Path) -> tuple[int, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array")
    filtered = [
        item
        for item in data
        if isinstance(item, dict) and _is_valid_url(item.get("link"), source=item.get("source"))
    ]
    path.write_text(json.dumps(filtered, indent=2, ensure_ascii=True), encoding="utf-8")
    return len(data), len(filtered)


def main():
    parser = argparse.ArgumentParser(description="Keep only listings with valid detail URLs.")
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=DEFAULT_PATHS,
        help="JSON files to filter (default: docs/data and data/)",
    )
    args = parser.parse_args()

    for path in args.paths:
        if not path.exists():
            print(f"Skip (not found): {path}")
            continue
        before, after = filter_file(path)
        print(f"{path}: {before} -> {after} listings")


if __name__ == "__main__":
    main()
