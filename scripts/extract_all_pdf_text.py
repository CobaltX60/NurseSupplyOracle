#!/usr/bin/env python3
"""
Extract every piece of text from a PDF that PyMuPDF can see.
Output is written to data/pdf_text_export/<source_name>/ so you can compare
with the PDF and see whether the problem is missing extraction or chunking/retrieval.

Uses:
  - get_text("text")  = plain text in reading order (what rebuild uses)
  - get_text("dict")  = every block → line → span; we dump all span text in order
  - get_text("words") = optional word-level dump for a page (see --words)

Usage (from project root):
  python scripts/extract_all_pdf_text.py <source_name_or_path> [options]

Examples:
  python scripts/extract_all_pdf_text.py MyCatalog
  python scripts/extract_all_pdf_text.py MyCatalog --pages 1-5,20
  python scripts/extract_all_pdf_text.py "C:/path/to/file.pdf" -o my_export
  python scripts/extract_all_pdf_text.py MyCatalog --words 20   # also dump words for page 20
  python scripts/extract_all_pdf_text.py MyCatalog --full-dump  # also write full_dump.txt (all pages) for grep/search
"""
import argparse
import os
import re
import sys

import fitz  # PyMuPDF

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
SOURCE_DIR = os.path.join(SCRIPT_DIR, "source_files")
EXPORT_BASE = os.path.join(ROOT, "data", "pdf_text_export")


def parse_page_range(spec):
    """Parse '1-5,20,22' -> [0,1,2,3,4,19,21] (0-based)."""
    out = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            try:
                lo, hi = int(a.strip()), int(b.strip())
                out.extend(range(lo - 1, hi))  # 1-based to 0-based
            except ValueError:
                continue
        else:
            try:
                out.append(int(part) - 1)
            except ValueError:
                continue
    return sorted(set(max(0, i) for i in out))


def extract_text_mode(page):
    """What rebuild uses: plain text."""
    return (page.get_text("text") or "").strip()


def extract_dict_all(page):
    """
    Every block → line → span; concatenate all span text in order.
    This is the most comprehensive extraction PyMuPDF offers (no text dropped by 'text' mode).
    """
    parts = []
    try:
        blocks = page.get_text("dict").get("blocks", [])
        for block in blocks:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    s = span.get("text") or ""
                    if s:
                        parts.append(s)
    except Exception:
        pass
    return " ".join(parts) if parts else ""


def extract_words(page):
    """Word-level list: list of (x0, y0, x1, y1, word)."""
    try:
        return page.get_text("words")
    except Exception:
        return []


def main():
    parser = argparse.ArgumentParser(
        description="Extract all text from a PDF (PyMuPDF dict + text) for inspection."
    )
    parser.add_argument(
        "source",
        help="PDF filename (no .pdf) in scripts/source_files/, or full path to a PDF",
    )
    parser.add_argument(
        "--pages",
        metavar="RANGE",
        help="Page range: e.g. 1-5,20,22 (default: all pages)",
    )
    parser.add_argument(
        "-o", "--output-dir",
        metavar="DIR",
        help="Subdir under data/pdf_text_export/ (default: source name)",
    )
    parser.add_argument(
        "--words",
        type=int,
        metavar="PAGE",
        help="Also dump word-level extraction for this page (1-based) to page_NNN_words.txt",
    )
    parser.add_argument(
        "--full-dump",
        action="store_true",
        help="Also write one file (full_dump.txt) with all pages concatenated for easy search.",
    )
    args = parser.parse_args()

    source_arg = args.source
    pdf_path = source_arg
    if not os.path.isfile(pdf_path):
        candidate = os.path.join(SOURCE_DIR, source_arg + ".pdf" if not source_arg.lower().endswith(".pdf") else source_arg)
        if not candidate.endswith(".pdf"):
            candidate = candidate + ".pdf"
        if os.path.isfile(candidate):
            pdf_path = candidate
        else:
            print(f"Not found: {source_arg}", file=sys.stderr)
            print(f"Also tried: {candidate}", file=sys.stderr)
            return 1

    source_name = os.path.splitext(os.path.basename(pdf_path))[0]
    out_dir = os.path.join(EXPORT_BASE, args.output_dir or source_name)
    os.makedirs(out_dir, exist_ok=True)
    print(f"PDF: {pdf_path}")
    print(f"Export directory: {out_dir}")
    print()

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    page_indices = list(range(total_pages))
    if args.pages:
        page_indices = [i for i in parse_page_range(args.pages) if i < total_pages]
        if not page_indices:
            print("No valid pages in range.", file=sys.stderr)
            doc.close()
            return 1

    summary_lines = [
        f"Source: {source_name}",
        f"Total pages in PDF: {total_pages}",
        f"Pages extracted: {len(page_indices)}",
        "",
        "Per-page character counts (text = get_text('text'), dict = get_text('dict') spans):",
        "-" * 60,
    ]
    word_page_1based = args.words
    full_dump_parts = [] if args.full_dump else None

    for pi in page_indices:
        page = doc.load_page(pi)
        page_num = pi + 1

        text_mode = extract_text_mode(page)
        dict_mode = extract_dict_all(page)

        len_text = len(text_mode)
        len_dict = len(dict_mode)
        note = "  (dict has more than text)" if len_dict > len_text and len_text > 0 else ""
        summary_lines.append(f"  Page {page_num:4d}:  text={len_text:6d} chars  dict={len_dict:6d} chars{note}")
        if full_dump_parts is not None:
            full_dump_parts.append(f"\n\n{'='*60}\nPAGE {page_num}\n{'='*60}\n\n{dict_mode or '(no text)'}")

        # Write full page text (dict extraction = everything PyMuPDF sees, in order)
        page_file = os.path.join(out_dir, f"page_{page_num:04d}.txt")
        with open(page_file, "w", encoding="utf-8") as f:
            f.write(f"# Page {page_num} — dict extraction (all blocks/lines/spans)\n")
            f.write(f"# Length: {len_dict} chars\n")
            f.write("-" * 60 + "\n\n")
            if dict_mode:
                f.write(dict_mode)
                if not dict_mode.endswith("\n"):
                    f.write("\n")
            else:
                f.write("(no text extracted)\n")

        # Optionally dump words for this page
        if word_page_1based and page_num == word_page_1based:
            words = extract_words(page)
            words_file = os.path.join(out_dir, f"page_{page_num:04d}_words.txt")
            with open(words_file, "w", encoding="utf-8") as f:
                f.write(f"# Page {page_num} — word-level (x0, y0, x1, y1, word)\n")
                f.write(f"# Total words: {len(words)}\n")
                f.write("-" * 60 + "\n\n")
                for w in words:
                    f.write(f"{w}\n")
            print(f"  Page {page_num}: wrote {len(words)} words to {os.path.basename(words_file)}")

    doc.close()

    if full_dump_parts:
        full_dump_path = os.path.join(out_dir, "full_dump.txt")
        with open(full_dump_path, "w", encoding="utf-8") as f:
            f.write(f"# Full text dump: {source_name} — all extracted text (dict) in order\n")
            f.write("".join(full_dump_parts))
        summary_lines.append("")
        summary_lines.append(f"Full dump: {full_dump_path}")

    summary_lines.append("")
    summary_lines.append("Files written:")
    summary_lines.append(f"  - {out_dir}/")
    for pi in page_indices:
        summary_lines.append(f"    page_{pi + 1:04d}.txt")
    if full_dump_parts:
        summary_lines.append("    full_dump.txt")
    if word_page_1based and word_page_1based in [pi + 1 for pi in page_indices]:
        summary_lines.append(f"    page_{word_page_1based:04d}_words.txt")

    summary_path = os.path.join(out_dir, "summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(summary_lines))
    print(f"Summary: {summary_path}")
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
