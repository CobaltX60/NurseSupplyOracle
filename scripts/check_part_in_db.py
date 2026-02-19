#!/usr/bin/env python3
"""
Check whether any chunk in the knowledge base contains a given part number (or text).
Use this to verify that "information on NL3006" can be answered (chunk must exist).

Usage (from project root):
  python scripts/check_part_in_db.py NL3006
  python scripts/check_part_in_db.py "NL 3006"
"""
import os
import sys
import sqlite3

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
DB_PATH = os.path.join(ROOT, "data", "instrument_oracle.db")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    needle = sys.argv[1].strip()
    if not needle:
        print("Provide a part number or search string, e.g. NL3006")
        return 1

    if not os.path.isfile(DB_PATH):
        print(f"Database not found: {DB_PATH}")
        print("Run: python scripts/rebuild.py (after placing PDFs in scripts/source_files/)")
        return 1

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Exact substring (case-insensitive)
    pattern = f"%{needle}%"
    rows = conn.execute(
        """SELECT c.id, c.source_id, c.page_number, c.text, s.name AS source
           FROM chunks c JOIN sources s ON s.id = c.source_id
           WHERE LOWER(c.text) LIKE LOWER(?)
           ORDER BY s.name, c.page_number, c.id
           LIMIT 20""",
        (pattern,),
    ).fetchall()

    if not rows and len(needle.replace(" ", "")) >= 3:
        needle_compact = needle.replace(" ", "").replace("\t", "").lower()
        pattern_alt = f"%{needle_compact}%"
        rows = conn.execute(
            """SELECT c.id, c.source_id, c.page_number, c.text, s.name AS source
               FROM chunks c JOIN sources s ON s.id = c.source_id
               WHERE REPLACE(REPLACE(LOWER(c.text), ' ', ''), char(9), '') LIKE ?
               ORDER BY s.name, c.page_number, c.id
               LIMIT 20""",
            (pattern_alt,),
        ).fetchall()
        if rows:
            print(f"(Matched with spaces removed: '{needle}' -> '{needle_compact}')\n")

    conn.close()

    if not rows:
        print(f"No chunks contain '{needle}' in the knowledge base.")
        print()
        print("Possible causes:")
        print("  1. Rebuild was not run after adding your PDF. Run: python scripts/rebuild.py")
        print("  2. The PDF text does not contain this exact string (check full dump: python scripts/extract_all_pdf_text.py <source> --full-dump)")
        print("  3. Different spelling/spacing in the PDF (e.g. 'NL 3006' vs 'NL3006') - the script tries both.")
        return 1

    print(f"Found {len(rows)} chunk(s) containing '{needle}':\n")
    for i, r in enumerate(rows, 1):
        src = r["source"] or "?"
        page = r["page_number"] or "?"
        text = (r["text"] or "").strip()
        preview = text[:350] + "..." if len(text) > 350 else text
        # Avoid UnicodeEncodeError on Windows console (e.g. \u25c6)
        preview_safe = "".join(c if ord(c) < 128 else "?" for c in preview)
        print(f"--- Chunk {i}: {src} (Page {page}) ---")
        print(preview_safe)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
