"""
Fetch and cache the latest HearthstoneJSON card data.

Usage:
    python scripts/fetch_cards.py
    python scripts/fetch_cards.py --force   # re-download even if cached

Output: data/cards.json
"""

import argparse
import json
import sys
from pathlib import Path

import requests

CARDS_URL = "https://api.hearthstonejson.com/v1/latest/enUS/cards.json"
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "cards.json"


def fetch_cards(force: bool = False) -> None:
    if OUTPUT_PATH.exists() and not force:
        size_mb = OUTPUT_PATH.stat().st_size / 1_000_000
        print(f"cards.json already cached ({size_mb:.1f} MB). Use --force to re-download.")
        return

    print(f"Fetching card data from {CARDS_URL} ...")
    resp = requests.get(CARDS_URL, timeout=60)
    resp.raise_for_status()

    data = resp.json()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    size_mb = OUTPUT_PATH.stat().st_size / 1_000_000
    print(f"Saved {len(data):,} card entries to {OUTPUT_PATH} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download HearthstoneJSON card data.")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached.")
    args = parser.parse_args()

    try:
        fetch_cards(force=args.force)
    except requests.RequestException as e:
        print(f"Network error: {e}", file=sys.stderr)
        sys.exit(1)
