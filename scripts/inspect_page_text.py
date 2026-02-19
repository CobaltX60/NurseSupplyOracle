#!/usr/bin/env python3
"""
Inspect raw text extracted from a PDF (same logic as rebuild.py) for a given page or all pages.
Use this to verify that content visible in the PDF (e.g. part numbers like NL3720) is present in the ingested text.

Usage (from project root):
  python scripts/inspect_page_text.py <source_name_or_path> [page_number]

Examples:
  python scripts/inspect_page_text.py MyCatalog           # all pages from scripts/source_files/MyCatalog.pdf
  python scripts/inspect_page_text.py MyCatalog 20        # only page 20
  python scripts/inspect_page_text.py "C:/path/to/file.pdf" 20
"""
import os
import sys

import fitz  # PyMuPDF

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
SOURCE_DIR = os.path.join(SCRIPT_DIR, "source_files")


def _extract_text_blocks(page):
    """Same fallback as rebuild: extract from blocks for sparse/complex layouts."""
    try:
        blocks = page.get_text("dict").get("blocks", [])
        parts = []
        for block in blocks:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    s = (span.get("text") or "").strip()
                    if s:
                        parts.append(s)
        return " ".join(parts) if parts else ""
    except Exception:
        return ""


def extract_page_text(doc, page_num_0based):
    """Extract text for one page using same logic as rebuild.py (text first, then blocks)."""
    page = doc.load_page(page_num_0based)
    text = page.get_text("text")
    if not text or not text.strip():
        text = _extract_text_blocks(page)
    return (text or "").strip()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    source_arg = sys.argv[1]
    page_arg = int(sys.argv[2]) if len(sys.argv) > 2 else None

    pdf_path = source_arg
    if not os.path.isfile(pdf_path):
        candidate = os.path.join(SOURCE_DIR, source_arg + ".pdf")
        if os.path.isfile(candidate):
            pdf_path = candidate
        else:
            print(f"Not found: {source_arg}")
            print(f"Also tried: {candidate}")
            return 1

    doc = fitz.open(pdf_path)
    total = len(doc)
    source_name = os.path.splitext(os.path.basename(pdf_path))[0]

    if page_arg is not None:
        if page_arg < 1 or page_arg > total:
            print(f"Page {page_arg} is out of range (1..{total})")
            doc.close()
            return 1
        pages_to_show = [page_arg - 1]
    else:
        pages_to_show = list(range(total))

    print(f"PDF: {pdf_path}")
    print(f"Source name: {source_name}")
    print(f"Pages: 1..{total}")
    print()

    for pi in pages_to_show:
        text = extract_page_text(doc, pi)
        page_display = pi + 1
        print("=" * 60)
        print(f"PAGE {page_display} (index {pi})")
        print(f"Extracted length: {len(text)} chars")
        print("-" * 60)
        if text:
            print(text)
        else:
            print("(no text extracted)")
        print()

    doc.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
