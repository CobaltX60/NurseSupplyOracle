#!/usr/bin/env python3
"""
Diagnose why some PDF images may not be extracted during rebuild.
Run from project root: python scripts/diagnose_pdf_images.py <path-to.pdf> [page_number]

Prints per-page:
- get_images() count and each (xref, width, height)
- get_image_info() count and whether it adds any xrefs not in get_images()
- get_text("dict") image blocks (type==1): count and how many have non-empty "image" data
"""
import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
SOURCE_DIR = os.path.join(SCRIPT_DIR, "source_files")

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/diagnose_pdf_images.py <path-to.pdf> [page_number]", file=sys.stderr)
        print("  page_number is 1-based; if omitted, all pages are summarized.", file=sys.stderr)
        sys.exit(1)
    pdf_path = sys.argv[1]
    if not os.path.isfile(pdf_path):
        # Try under source_files
        alt = os.path.join(SOURCE_DIR, os.path.basename(pdf_path))
        if os.path.isfile(alt):
            pdf_path = alt
        else:
            print(f"File not found: {sys.argv[1]}", file=sys.stderr)
            sys.exit(1)
    page_one = int(sys.argv[2]) - 1 if len(sys.argv) > 2 else None  # 0-based

    import fitz
    doc = fitz.open(pdf_path)
    pages_to_show = [page_one] if page_one is not None else list(range(len(doc)))
    if page_one is not None and (page_one < 0 or page_one >= len(doc)):
        print(f"Page {page_one + 1} out of range (doc has {len(doc)} pages).", file=sys.stderr)
        doc.close()
        sys.exit(1)

    for pno in pages_to_show:
        page = doc.load_page(pno)
        print(f"\n--- Page {pno + 1} (0-index {pno}) ---")

        # get_images()
        imgs = page.get_images()
        print(f"  get_images(): {len(imgs)} image(s)")
        xrefs_from_get_images = set()
        for i, img in enumerate(imgs):
            xref = img[0]
            xrefs_from_get_images.add(xref)
            w = img[2] if len(img) > 2 else "?"
            h = img[3] if len(img) > 3 else "?"
            print(f"    [{i}] xref={xref} width={w} height={h}")

        # get_image_info() — show full first entry (xref may be under "number" or other key)
        if hasattr(page, "get_image_info"):
            try:
                info_list = page.get_image_info()
                print(f"  get_image_info(): {len(info_list)} entry/entries")
                if info_list and page_one is not None:
                    e0 = info_list[0]
                    if isinstance(e0, dict):
                        print(f"  First entry keys: {list(e0.keys())}")
                        for k, v in e0.items():
                            if k == "image" and isinstance(v, (bytes, bytearray)):
                                print(f"    {k}=<bytes len={len(v)}>")
                            else:
                                print(f"    {k}={v!r}")
                    else:
                        print(f"  First entry (list/tuple): len={len(e0)}, {e0!r}")
                extra = []
                for j, entry in enumerate(info_list):
                    if isinstance(entry, dict):
                        xref = entry.get("xref") or entry.get("number")
                        w = entry.get("width", "?")
                        h = entry.get("height", "?")
                    else:
                        xref = entry[0] if isinstance(entry, (list, tuple)) else None
                        w = entry[2] if isinstance(entry, (list, tuple)) and len(entry) > 2 else "?"
                        h = entry[3] if isinstance(entry, (list, tuple)) and len(entry) > 3 else "?"
                    if xref is not None and xref not in xrefs_from_get_images:
                        extra.append((xref, w, h))
                    if page_one is not None and j < 5:
                        print(f"    [{j}] xref={xref} width={w} height={h}")
                if extra:
                    print(f"  -> get_image_info() adds {len(extra)} xref(s) not in get_images(): {[e[0] for e in extra]}")
            except Exception as e:
                print(f"  get_image_info(): error {e}")
        else:
            print("  get_image_info(): not available")

        # Page XObjects (Form XObjects may contain the missing small images)
        if hasattr(doc, "get_page_xobjects"):
            try:
                xobjs = doc.get_page_xobjects(pno)
                print(f"  get_page_xobjects(): {len(xobjs)} XObject(s)")
                if page_one is not None and xobjs:
                    for xi, xo in enumerate(xobjs[:5]):
                        print(f"    [{xi}] {xo}")
            except Exception as e:
                print(f"  get_page_xobjects(): error {e}")

        # get_text("dict") image blocks
        try:
            kwargs = {"sort": False}
            if hasattr(fitz, "TEXTFLAGS_DICT"):
                kwargs["flags"] = fitz.TEXTFLAGS_DICT
            d = page.get_text("dict", **kwargs)
            blocks = d.get("blocks") or []
            type1 = [b for b in blocks if b.get("type") == 1]
            with_data = [b for b in type1 if b.get("image") and len(b.get("image") or b"") > 0]
            print(f"  get_text('dict') image blocks (type==1): {len(type1)} total, {len(with_data)} with non-empty 'image' data")
            if type1 and len(with_data) < len(type1):
                print("  -> Some image blocks have no or empty 'image' field (inline images may be missing in this PDF).")
        except Exception as e:
            print(f"  get_text('dict'): error {e}")

    # Document-wide: all image xrefs (images inside Form XObjects have xrefs but may not appear in page.get_images())
    if hasattr(doc, "xref_length") and doc.is_pdf:
        try:
            all_page_img_xrefs = set()
            for p in range(len(doc)):
                for img in doc.get_page_images(p):
                    all_page_img_xrefs.add(img[0])
            image_xrefs_in_doc = []
            for xref in range(1, doc.xref_length()):
                try:
                    info = doc.extract_image(xref)
                    if info and info.get("image"):
                        image_xrefs_in_doc.append((xref, info.get("width"), info.get("height")))
                except Exception:
                    pass
            print("\n--- Document-wide image xrefs ---")
            print(f"  Total image xrefs in PDF (from scan): {len(image_xrefs_in_doc)}")
            print(f"  Xrefs reported by get_page_images() across all pages: {len(all_page_img_xrefs)}")
            orphan = [(x, w, h) for x, w, h in image_xrefs_in_doc if x not in all_page_img_xrefs]
            if orphan:
                print(f"  Orphan image xrefs (not in any page.get_images()): {len(orphan)} — likely in Form XObjects")
                for x, w, h in orphan[:15]:
                    print(f"    xref={x} width={w} height={h}")
        except Exception as e:
            print(f"  Document xref scan: error {e}")

    doc.close()
    print()

if __name__ == "__main__":
    main()
