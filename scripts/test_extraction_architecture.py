#!/usr/bin/env python3
"""
Test the new extraction architecture: LLM-only product extraction + image association by catalog-number proximity.

Usage:
  python scripts/test_extraction_architecture.py --source-id 1 --page 5
  python scripts/test_extraction_architecture.py --source-id 1 --page 5 --no-replace

Requires:
  - Flask server running (e.g. python scripts/chat_server.py)
  - GEMINI_API_KEY set (for LLM extraction)
  - DB with the given source_id having chunks (and ideally images + catalog profile)
"""

import argparse
import json
import os
import sqlite3
import sys

try:
    import requests
except ImportError:
    print("Install requests: pip install requests")
    sys.exit(1)

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(ROOT, "data")
DB_PATH = os.path.join(DATA_DIR, "instrument_oracle.db")
DEFAULT_BASE_URL = os.environ.get("FLASK_URL", "http://localhost:5001")


def main():
    ap = argparse.ArgumentParser(description="Test extraction architecture: build one page, then report products and image links.")
    ap.add_argument("--source-id", type=int, required=True, help="Catalog (source) id in the DB")
    ap.add_argument("--page", type=int, required=True, help="Page number (1-based)")
    ap.add_argument("--no-replace", action="store_true", help="Do not replace existing products for this page")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Flask server base URL")
    args = ap.parse_args()

    source_id = args.source_id
    page_number = args.page
    replace = not args.no_replace
    base_url = args.base_url.rstrip("/")

    print("Testing new extraction architecture")
    print("  source_id:", source_id)
    print("  page:", page_number)
    print("  replace:", replace)
    print("  base_url:", base_url)
    print()

    # 1) Health check
    try:
        r = requests.get(f"{base_url}/health", timeout=5)
        if r.status_code != 200:
            print("Server health check failed:", r.status_code)
            sys.exit(1)
        print("Server OK:", r.json().get("status", "ok"))
    except requests.exceptions.RequestException as e:
        print("Cannot reach server. Start it with: python scripts/chat_server.py")
        print("Error:", e)
        sys.exit(1)

    # 2) Call build-product-listing for one page
    url = f"{base_url}/api/catalogs/{source_id}/build-product-listing/page/{page_number}"
    payload = {"replace": replace}
    print("POST", url, payload)
    try:
        r = requests.post(url, json=payload, timeout=120)
        r.raise_for_status()
        result = r.json()
    except requests.exceptions.RequestException as e:
        print("Request failed:", e)
        if hasattr(e, "response") and e.response is not None:
            print("Response:", e.response.text[:500])
        sys.exit(1)

    created = result.get("created", 0)
    errors = result.get("errors", [])
    print("Result: created =", created, "errors =", errors)
    if errors:
        for err in errors:
            print("  -", err)
    print()

    # 3) Validate DB: products and product_images for this page
    if not os.path.isfile(DB_PATH):
        print("DB not found at", DB_PATH)
        return
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        products = conn.execute(
            "SELECT id, manufacturer_part_number, product_name, description, category FROM products WHERE source_id=? AND page_number=? ORDER BY id",
            (source_id, page_number),
        ).fetchall()
        links = conn.execute(
            """SELECT pi.product_id, pi.image_id, pi.display_order, p.manufacturer_part_number
               FROM product_images pi
               JOIN products p ON p.id = pi.product_id
               WHERE p.source_id=? AND p.page_number=?""",
            (source_id, page_number),
        ).fetchall()
    finally:
        conn.close()

    print("DB validation for source_id=%s page=%s" % (source_id, page_number))
    print("  Products: %d" % len(products))
    for i, row in enumerate(products[:10]):
        mpn = (row["manufacturer_part_number"] or "").strip()
        name = (row["product_name"] or "").strip()[:50]
        print("    %d. %s | %s" % (i + 1, mpn, name))
    if len(products) > 10:
        print("    ... and %d more" % (len(products) - 10))
    print("  Image links: %d" % len(links))
    for i, row in enumerate(links[:10]):
        print("    product_id=%s (MPN=%s) <- image_id=%s order=%s" % (
            row["product_id"], row["manufacturer_part_number"], row["image_id"], row["display_order"]))
    if len(links) > 10:
        print("    ... and %d more" % (len(links) - 10))
    print()
    print("Done. Check server console for [Build listing] and image association logs.")


if __name__ == "__main__":
    main()
