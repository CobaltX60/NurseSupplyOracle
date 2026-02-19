#!/usr/bin/env python3
"""
Rebuild Instrument Oracle data from source documents.
Reads all PDFs in scripts/source_files/, chunks text, stores in SQLite, builds FAISS index.
Run from project root: python scripts/rebuild.py
Does not run automatically; the app starts and runs using existing data until you run this.
"""
import os
import re
import json
import sqlite3
import shutil
import zlib
import fitz  # PyMuPDF
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
SOURCE_DIR = os.path.join(SCRIPT_DIR, "source_files")
DATA_DIR = os.path.join(ROOT, "data")
DB_PATH = os.path.join(DATA_DIR, "instrument_oracle.db")
FAISS_PATH = os.path.join(DATA_DIR, "faiss_index.idx")
IMAGES_DIR = os.path.join(DATA_DIR, "images")

# Words per chunk (text is split by whitespace). Smaller = more chunks, better for precise recall.
CHUNK_SIZE = 200   # Was 400; 200 yields ~2x chunks from same PDF for finer-grained retrieval
CHUNK_OVERLAP = 50

# Minimum image dimensions to include (smaller images are skipped to avoid icons/noise).
MIN_IMAGE_WIDTH = 30
MIN_IMAGE_HEIGHT = 30

# Include small vector regions (e.g. xRef icons, line-art symbols) by rasterizing clip regions
# from page.get_drawings() / cluster_drawings(). Only regions within MIN/MAX size are added.
INCLUDE_VECTOR_REGIONS = True
MIN_VECTOR_REGION_PT = 8   # skip tiny noise (points, 1/72 inch)
MAX_VECTOR_REGION_PT = 220  # skip large diagrams
VECTOR_REGION_DPI_SCALE = 2  # 2x rasterization for small icons


def _image_passes_size_filter(w, h):
    """Return True if image should be included (unknown size or both dimensions >= min)."""
    if w is None or h is None:
        return True
    return w >= MIN_IMAGE_WIDTH and h >= MIN_IMAGE_HEIGHT


MIN_NARROW_ILLUSTRATION_PT = 40  # max-dimension threshold for narrow vector illustrations
MIN_STANDARD_VECTOR_PT = 15     # both-dimensions threshold for standard (non-adaptive) tier

def _small_vector_region_bboxes(page):
    """Return list of ``(fitz.Rect, needs_adaptive_dpi)`` tuples for vector drawings
    suitable for region rasterization.

    Two tiers:
      * Standard — both dimensions >= 15 pt.  Rasterised at default DPI; the caller
        applies the normal pixel-size filter.
      * Narrow illustration — max dimension >= 40 pt, min dimension >= 5 pt, but
        min < 15 pt.  These are tall-narrow or wide-thin drawings (e.g. blade details)
        that need adaptive DPI scaling; the caller skips the pixel-size filter.
    """
    results = []
    if not INCLUDE_VECTOR_REGIONS:
        return results

    def _classify(w, h):
        if w > MAX_VECTOR_REGION_PT or h > MAX_VECTOR_REGION_PT:
            return None
        if w >= MIN_STANDARD_VECTOR_PT and h >= MIN_STANDARD_VECTOR_PT:
            return False  # standard — no adaptive DPI needed
        if max(w, h) >= MIN_NARROW_ILLUSTRATION_PT and min(w, h) >= 5:
            return True   # narrow illustration — needs adaptive DPI
        return None

    try:
        if hasattr(page, "cluster_drawings"):
            clusters = page.cluster_drawings()
            for r in clusters:
                if hasattr(r, "width") and hasattr(r, "height"):
                    w, h = r.width, r.height
                elif hasattr(r, "x0"):
                    w, h = r.x1 - r.x0, r.y1 - r.y0
                else:
                    continue
                tier = _classify(w, h)
                if tier is not None:
                    results.append((r if hasattr(r, "x0") else fitz.Rect(r), tier))
        elif hasattr(page, "get_drawings"):
            for path in page.get_drawings():
                r = path.get("rect")
                if r is None:
                    continue
                if hasattr(r, "width") and hasattr(r, "height"):
                    w, h = r.width, r.height
                elif hasattr(r, "x0"):
                    w, h = r.x1 - r.x0, r.y1 - r.y0
                else:
                    w = r[2] - r[0] if len(r) >= 4 else 0
                    h = r[3] - r[1] if len(r) >= 4 else 0
                tier = _classify(w, h)
                if tier is not None:
                    results.append((r if hasattr(r, "x0") else fitz.Rect(r), tier))
    except Exception:
        pass
    return results


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def init_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            profile_path TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL REFERENCES sources(id),
            page_number INTEGER,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            type TEXT DEFAULT 'text',
            metadata_json TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_source_id ON chunks(source_id);
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL REFERENCES sources(id),
            page_number INTEGER NOT NULL,
            image_index INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            width INTEGER,
            height INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(source_id, page_number, image_index)
        );
        CREATE INDEX IF NOT EXISTS idx_images_source_page ON images(source_id, page_number);
        CREATE TABLE IF NOT EXISTS catalog_config (source_id INTEGER PRIMARY KEY REFERENCES sources(id), config_json TEXT, updated_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS catalog_profiles (source_id INTEGER PRIMARY KEY REFERENCES sources(id), catalog_id TEXT, source_filename TEXT NOT NULL, manufacturer TEXT, profile_json TEXT NOT NULL, analyzed_at TEXT, analyzed_by_model TEXT, sample_pages TEXT, status TEXT DEFAULT 'pending');
        CREATE TABLE IF NOT EXISTS catalog_samples (id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id), page_number INTEGER, sample_type TEXT NOT NULL, value_text TEXT NOT NULL, notes TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE INDEX IF NOT EXISTS idx_catalog_samples_source ON catalog_samples(source_id);
        CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id), page_number INTEGER, manufacturer TEXT, manufacturer_part_number TEXT NOT NULL, product_name TEXT, description TEXT, secondary_description TEXT, category TEXT, language TEXT DEFAULT 'en', verification_status TEXT DEFAULT 'unverified', raw_snippet TEXT, created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')));
        CREATE INDEX IF NOT EXISTS idx_products_source ON products(source_id);
        CREATE TABLE IF NOT EXISTS product_images (id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE, image_id INTEGER NOT NULL REFERENCES images(id), display_order INTEGER DEFAULT 0, UNIQUE(product_id, image_id));
        CREATE INDEX IF NOT EXISTS idx_product_images_product ON product_images(product_id);
        CREATE TABLE IF NOT EXISTS page_blocks (id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id), page_number INTEGER NOT NULL, block_index INTEGER NOT NULL, bbox_json TEXT NOT NULL, text TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_page_blocks_source_page ON page_blocks(source_id, page_number);
    """)
    conn.commit()
    # Migration: add bbox_json to images if missing (for layout-based proximity)
    try:
        info = conn.execute("PRAGMA table_info(images)").fetchall()
        if not any(row[1] == "bbox_json" for row in info):
            conn.execute("ALTER TABLE images ADD COLUMN bbox_json TEXT")
            conn.commit()
    except Exception:
        pass
    # Migration: add profile_path to sources if missing (catalog profile per source)
    try:
        info = conn.execute("PRAGMA table_info(sources)").fetchall()
        if not any(row[1] == "profile_path" for row in info):
            conn.execute("ALTER TABLE sources ADD COLUMN profile_path TEXT")
            conn.commit()
    except Exception:
        pass
    # Migration: create catalog_profiles if missing
    try:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='catalog_profiles'")
        if not cur.fetchone():
            conn.execute("""
                CREATE TABLE catalog_profiles (
                    source_id INTEGER PRIMARY KEY REFERENCES sources(id),
                    catalog_id TEXT,
                    source_filename TEXT NOT NULL,
                    manufacturer TEXT,
                    profile_json TEXT NOT NULL,
                    analyzed_at TEXT,
                    analyzed_by_model TEXT,
                    sample_pages TEXT,
                    status TEXT DEFAULT 'pending'
                )
            """)
            conn.commit()
    except Exception:
        pass
    # Migration: add last_rebuild_at to sources (per-catalog rebuild timestamp)
    try:
        info = conn.execute("PRAGMA table_info(sources)").fetchall()
        if not any(row[1] == "last_rebuild_at" for row in info):
            conn.execute("ALTER TABLE sources ADD COLUMN last_rebuild_at TEXT")
            conn.commit()
    except Exception:
        pass


def clear_tables(conn):
    """Remove chunks, images, and page_blocks so rebuild can repopulate. Preserve sources and catalog_profiles so analysis profiles and source IDs persist across rebuilds."""
    conn.execute("DELETE FROM page_blocks")
    conn.execute("DELETE FROM images")
    conn.execute("DELETE FROM chunks")
    # Do NOT delete catalog_profiles or sources — analysis profiles and source_id stability persist across rebuilds
    conn.commit()


def clear_one_source(conn, source_id: int, images_dir: str):
    """Remove chunks, images, page_blocks, product_images, and products for one source. Delete that source's image files. Preserve catalog_profiles and the source row."""
    cursor = conn.cursor()
    cursor.execute("DELETE FROM product_images WHERE product_id IN (SELECT id FROM products WHERE source_id = ?)", (source_id,))
    cursor.execute("DELETE FROM products WHERE source_id = ?", (source_id,))
    cursor.execute("DELETE FROM page_blocks WHERE source_id = ?", (source_id,))
    cursor.execute("DELETE FROM images WHERE source_id = ?", (source_id,))
    cursor.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))
    conn.commit()
    sid_dir = os.path.join(images_dir, str(source_id))
    if os.path.isdir(sid_dir):
        try:
            shutil.rmtree(sid_dir)
        except Exception as e:
            print(f"  [--] Could not remove images dir {sid_dir}: {e}")


def _image_ext_from_bytes(img_bytes):
    """Detect image format from magic bytes. Returns 'png', 'jpeg', or 'png' as fallback."""
    if img_bytes[:8][:4] == b"\x89PNG":
        return "png"
    if img_bytes[:2] == b"\xff\xd8":
        return "jpeg"
    if img_bytes[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return "png"


def _get_decompressed_stream(doc, xref):
    """Return decompressed stream bytes for a stream xref. Handles /Filter /FlateDecode."""
    try:
        raw = None
        if hasattr(doc, "xref_stream_raw"):
            try:
                raw = doc.xref_stream_raw(xref)
            except Exception:
                pass
        if raw is None:
            raw = doc.xref_stream(xref)
        if not raw:
            return b""
        try:
            kind, val = doc.xref_get_key(xref, "Filter")
            if kind == "name" and val and "Flate" in str(val):
                return zlib.decompress(raw)
            if kind == "array":
                return zlib.decompress(raw)
        except Exception:
            pass
        return raw
    except Exception:
        try:
            return doc.xref_stream(xref) or b""
        except Exception:
            return b""


def _xobject_image_xrefs(doc, xobj_xref, seen):
    """Recursively collect image xrefs from a Form XObject's /Resources/XObject."""
    out = set()
    try:
        kind, res_val = doc.xref_get_key(xobj_xref, "Resources")
        if kind != "ref" or not res_val:
            return out
        res_xref = int(res_val.split()[0])
        kind2, xobj_val = doc.xref_get_key(res_xref, "XObject")
        if kind2 != "ref" or not xobj_val:
            return out
        xobj_dict_xref = int(xobj_val.split()[0])
        keys = doc.xref_get_keys(xobj_dict_xref)
        for k in keys:
            kkind, v = doc.xref_get_key(xobj_dict_xref, k)
            if kkind != "ref" or not v:
                continue
            ref_xref = int(v.split()[0])
            if ref_xref in seen:
                continue
            seen.add(ref_xref)
            try:
                doc.extract_image(ref_xref)
                out.add(ref_xref)
            except Exception:
                out |= _xobject_image_xrefs(doc, ref_xref, seen)
    except Exception:
        pass
    return out


def _page_references_xref(doc, page, xref):
    """Return True if the given image xref is referenced by this page's content or its Form XObject streams/resources."""
    ref = str(xref).encode()
    ref_0_r = ref + b" 0 R"
    patterns = (ref_0_r, b"/" + ref)
    def stream_contains(stream):
        if not stream:
            return False
        for p in patterns:
            if p in stream:
                return True
        return False
    # Page content streams (decompressed)
    try:
        for cxref in page.get_contents():
            try:
                stream = _get_decompressed_stream(doc, cxref)
                if stream_contains(stream):
                    return True
            except Exception:
                continue
    except Exception:
        pass
    # Form XObjects: check stream content and also /Resources/XObject for image refs
    try:
        for item in doc.get_page_xobjects(page.number):
            xobj_xref = item[0] if isinstance(item, (list, tuple)) else item
            try:
                stream = _get_decompressed_stream(doc, xobj_xref)
                if stream_contains(stream):
                    return True
            except Exception:
                pass
            # Form may reference images via /Resources/XObject << /Im1 1005 0 R >> (ref in dict, not in stream)
            try:
                img_xrefs = _xobject_image_xrefs(doc, xobj_xref, set())
                if xref in img_xrefs:
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _inline_images_from_page(page):
    """Extract inline images from page (BI/ID/EI inline bitmaps; get_images() only finds XObject refs).
    Uses get_text('dict') with TEXT_PRESERVE_IMAGES so blocks with type==1 contain image data."""
    out = []
    try:
        kwargs = {"sort": False}
        flags = 0
        if hasattr(fitz, "TEXT_PRESERVE_IMAGES"):
            flags |= fitz.TEXT_PRESERVE_IMAGES
        if hasattr(fitz, "TEXTFLAGS_DICT"):
            flags |= fitz.TEXTFLAGS_DICT
        if flags:
            kwargs["flags"] = flags
        d = page.get_text("dict", **kwargs)
        blocks = d.get("blocks") or []
        for block in blocks:
            if block.get("type") != 1:
                continue
            img_bytes = block.get("image")
            if img_bytes is None:
                continue
            # PyMuPDF may return bytes or a buffer-like; ensure bytes
            if not isinstance(img_bytes, (bytes, bytearray)):
                if hasattr(img_bytes, "tobytes"):
                    img_bytes = img_bytes.tobytes()
                elif hasattr(img_bytes, "read"):
                    img_bytes = img_bytes.read()
                else:
                    continue
            if len(img_bytes) == 0:
                continue
            bbox = block.get("bbox") or (0, 0, 0, 0)
            if hasattr(bbox, "x0"):
                bbox = (bbox.x0, bbox.y0, bbox.x1, bbox.y1)
            w = block.get("width")
            h = block.get("height")
            if w is None or h is None:
                try:
                    w = int(bbox[2] - bbox[0]) if len(bbox) >= 4 else None
                    h = int(bbox[3] - bbox[1]) if len(bbox) >= 4 else None
                except (TypeError, ValueError):
                    pass
            ext = block.get("ext") or _image_ext_from_bytes(img_bytes)
            if ext and ext.lower() == "jpg":
                ext = "jpeg"
            out.append({"img_bytes": img_bytes, "ext": ext or "png", "width": w, "height": h, "bbox": bbox})
    except Exception as e:
        # Log so we can see if dict extraction fails (e.g. flags not available)
        import sys
        print(f"  [inline images] {e}", file=sys.stderr)
    return out


def extract_images_from_pdf(pdf_path, source_name):
    """Extract all embedded images from PDF (xref + inline + orphans).
    Returns list of {source_name, page_number, image_index, img_bytes, ext, width, height}.
    Images smaller than MIN_IMAGE_WIDTH x MIN_IMAGE_HEIGHT (30x30) are skipped. Multiple images per page are ordered by position (left-to-right, top-to-bottom)."""
    out = []
    try:
        doc = fitz.open(pdf_path)
        total_xref, total_with_inline = 0, 0
        # Image xrefs that exist in the doc but are not in any page.get_images() (e.g. inside Form XObjects)
        orphan_xrefs = set()
        if getattr(doc, "is_pdf", True) and hasattr(doc, "xref_length"):
            try:
                all_image_xrefs = set()
                for xref in range(1, doc.xref_length()):
                    try:
                        doc.extract_image(xref)
                        all_image_xrefs.add(xref)
                    except Exception:
                        pass
                all_direct = set()
                for p in range(len(doc)):
                    for img in doc.load_page(p).get_images():
                        all_direct.add(img[0])
                orphan_xrefs = all_image_xrefs - all_direct
            except Exception:
                pass
        if orphan_xrefs:
            print(f"  [orphans] Found {len(orphan_xrefs)} orphan image xrefs (not in get_images(); may be in Form XObjects)")
        assigned_orphans = set()
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            page_images = []

            # 1) Xref-based images; get_images(full=True) when available includes more refs (e.g. from Forms)
            seen_xrefs = set()
            try:
                img_list = page.get_images(full=True)
            except TypeError:
                img_list = page.get_images()
            for img in (img_list or []):
                try:
                    xref = img[0]
                    seen_xrefs.add(xref)
                    info = doc.extract_image(xref)
                    img_bytes = info["image"]
                    ext = info["ext"] if info.get("ext") else "png"
                    if ext.lower() == "jpg":
                        ext = "jpeg"
                    try:
                        rect = page.get_image_bbox(img)
                        bbox = (rect.x0, rect.y0, rect.x1, rect.y1)
                    except Exception:
                        bbox = (0, 0, info.get("width") or 0, info.get("height") or 0)
                    if not _image_passes_size_filter(info.get("width"), info.get("height")):
                        continue
                    page_images.append({
                        "img_bytes": img_bytes,
                        "ext": ext,
                        "width": info.get("width"),
                        "height": info.get("height"),
                        "bbox": bbox,
                    })
                except Exception:
                    continue

            # 2) Extra xrefs from get_image_info() (can include images inside Form XObjects / nested refs)
            if hasattr(page, "get_image_info"):
                try:
                    for entry in page.get_image_info():
                        # Use "xref" only; "number" in get_image_info() is an internal index, not the PDF xref
                        xref = entry.get("xref") if isinstance(entry, dict) else (entry[0] if isinstance(entry, (list, tuple)) else None)
                        if xref is None or xref in seen_xrefs:
                            continue
                        try:
                            info = doc.extract_image(xref)
                            if not info or not info.get("image"):
                                continue
                            seen_xrefs.add(xref)
                            img_bytes = info["image"]
                            ext = info.get("ext") or "png"
                            if ext and ext.lower() == "jpg":
                                ext = "jpeg"
                            w = info.get("width") or (entry.get("width") if isinstance(entry, dict) else None)
                            h = info.get("height") or (entry.get("height") if isinstance(entry, dict) else None)
                            bbox = (0, 0, w or 0, h or 0)
                            if isinstance(entry, dict):
                                for key in ("bbox", "rect"):
                                    r = entry.get(key)
                                    if r is not None:
                                        if hasattr(r, "x0"):
                                            bbox = (r.x0, r.y0, r.x1, r.y1)
                                        elif isinstance(r, (list, tuple)) and len(r) >= 4:
                                            bbox = tuple(r[:4])
                                        break
                            if not _image_passes_size_filter(w, h):
                                continue
                            page_images.append({
                                "img_bytes": img_bytes,
                                "ext": ext,
                                "width": w,
                                "height": h,
                                "bbox": bbox,
                            })
                        except Exception:
                            continue
                except Exception:
                    pass

            # 3) Inline images from get_text("dict") (often missed by get_images(), e.g. small or in content stream)
            n_before_inline = len(page_images)
            inline = _inline_images_from_page(page)
            for rec in inline:
                # Avoid duplicates: same size + same length is likely the same image already from xref
                ib = rec["img_bytes"]
                same = any(
                    p.get("width") == rec.get("width") and p.get("height") == rec.get("height") and len(p.get("img_bytes") or b"") == len(ib)
                    for p in page_images
                )
                if not same and _image_passes_size_filter(rec.get("width"), rec.get("height")):
                    page_images.append({
                        "img_bytes": ib,
                        "ext": rec["ext"],
                        "width": rec.get("width"),
                        "height": rec.get("height"),
                        "bbox": rec.get("bbox") or (0, 0, 0, 0),
                    })

            # 4) Orphan image xrefs (images in Form XObjects etc. not returned by get_images())
            n_orphans_added_this_page = 0
            for xref in orphan_xrefs:
                if xref in seen_xrefs:
                    continue
                if not _page_references_xref(doc, page, xref):
                    continue
                try:
                    info = doc.extract_image(xref)
                    if not info or not info.get("image"):
                        continue
                    img_bytes = info["image"]
                    ext = info.get("ext") or "png"
                    if ext and ext.lower() == "jpg":
                        ext = "jpeg"
                    w, h = info.get("width"), info.get("height")
                except Exception:
                    continue
                if not _image_passes_size_filter(w, h):
                    continue
                seen_xrefs.add(xref)
                page_images.append({
                    "img_bytes": img_bytes,
                    "ext": ext,
                    "width": w,
                    "height": h,
                    "bbox": (0, 0, w or 0, h or 0),
                })
                n_orphans_added_this_page += 1
                assigned_orphans.add(xref)
            if orphan_xrefs and n_orphans_added_this_page:
                print(f"  [orphans] Page {page_num + 1}: assigned {n_orphans_added_this_page} orphan image(s)")

            # Sort by position (top-left to bottom-right) so order is stable and matches visual layout
            page_images.sort(key=lambda p: (p["bbox"][1], p["bbox"][0]) if p.get("bbox") else (0, 0))
            total_xref += n_before_inline
            total_with_inline += len(page_images)

            # Optional: small vector regions (xRef icons, line-art symbols) — rasterize clip regions at higher DPI
            if INCLUDE_VECTOR_REGIONS:
                try:
                    import math as _math
                    vector_results = _small_vector_region_bboxes(page)
                    std_mat = fitz.Matrix(VECTOR_REGION_DPI_SCALE, VECTOR_REGION_DPI_SCALE)
                    for rect, needs_adaptive in vector_results[:30]:
                        try:
                            if needs_adaptive:
                                min_pts = min(rect.width, rect.height) if hasattr(rect, "width") else min(rect.x1 - rect.x0, rect.y1 - rect.y0)
                                scale = max(VECTOR_REGION_DPI_SCALE, _math.ceil(MIN_IMAGE_WIDTH / max(min_pts, 0.1)))
                                scale = min(scale, 15)
                                cur_mat = fitz.Matrix(scale, scale)
                            else:
                                cur_mat = std_mat
                            pix = page.get_pixmap(matrix=cur_mat, clip=rect, alpha=False)
                            if not (pix and pix.samples):
                                continue
                            if not needs_adaptive and (pix.width < MIN_IMAGE_WIDTH or pix.height < MIN_IMAGE_HEIGHT):
                                continue
                            # Skip solid-color decorative elements (e.g. orange grid markers).
                            # Real illustrations have bright background + dark lines; decorative
                            # bars are mid-tone with neither very bright nor very dark pixels.
                            _n_ch = pix.n
                            _total_px = len(pix.samples) // max(_n_ch, 1)
                            if _total_px > 10:
                                _step = max(1, _total_px // 300)
                                _bright = _dark = _sampled = 0
                                for _si in range(0, _total_px, _step):
                                    _off = _si * _n_ch
                                    if _n_ch >= 3:
                                        _lum = (0.299 * pix.samples[_off]
                                                + 0.587 * pix.samples[_off + 1]
                                                + 0.114 * pix.samples[_off + 2])
                                    else:
                                        _lum = float(pix.samples[_off])
                                    _sampled += 1
                                    if _lum > 220:
                                        _bright += 1
                                    elif _lum < 50:
                                        _dark += 1
                                if _sampled > 0 and (_bright + _dark) / _sampled < 0.08:
                                    continue
                            png_bytes = pix.tobytes("png")
                            if png_bytes and len(png_bytes) > 0:
                                page_images.append({
                                    "img_bytes": png_bytes,
                                    "ext": "png",
                                    "width": pix.width,
                                    "height": pix.height,
                                    "bbox": (getattr(rect, "x0", 0), getattr(rect, "y0", 0), getattr(rect, "x1", 0), getattr(rect, "y1", 0)),
                                })
                        except Exception:
                            continue
                    if vector_results:
                        print(f"  [vector] Page {page_num + 1}: rasterized {min(len(vector_results), 30)} vector region(s)")
                except Exception:
                    pass

            # Re-sort so vector regions are ordered by position with the rest
            page_images.sort(key=lambda p: (p["bbox"][1], p["bbox"][0]) if p.get("bbox") else (0, 0))

            for img_index, rec in enumerate(page_images):
                bbox = rec.get("bbox")
                if not bbox or len(bbox) < 4:
                    w, h = rec.get("width"), rec.get("height")
                    bbox = (0, 0, w or 0, h or 0)
                elif hasattr(bbox, "x0"):
                    bbox = (bbox.x0, bbox.y0, bbox.x1, bbox.y1)
                else:
                    bbox = tuple(float(bbox[i]) for i in range(4))
                out.append({
                    "source_name": source_name,
                    "page_number": page_num + 1,
                    "image_index": img_index,
                    "img_bytes": rec["img_bytes"],
                    "ext": rec["ext"],
                    "width": rec.get("width"),
                    "height": rec.get("height"),
                    "bbox": bbox,
                })
        # Fallback: assign any orphans that stream/Resources lookup did not place
        unassigned = orphan_xrefs - assigned_orphans
        if unassigned and hasattr(doc, "get_page_xobjects"):
            fallback_page = 1
            for p in range(len(doc)):
                try:
                    if doc.get_page_xobjects(p):
                        fallback_page = p + 1
                        break
                except Exception:
                    pass
            next_index = sum(1 for r in out if r["page_number"] == fallback_page)
            for xref in unassigned:
                try:
                    info = doc.extract_image(xref)
                    if not info or not info.get("image"):
                        continue
                    img_bytes = info["image"]
                    ext = info.get("ext") or "png"
                    if ext and ext.lower() == "jpg":
                        ext = "jpeg"
                    w, h = info.get("width"), info.get("height")
                except Exception:
                    continue
                if not _image_passes_size_filter(w, h):
                    continue
                out.append({
                    "source_name": source_name,
                    "page_number": fallback_page,
                    "image_index": next_index,
                    "img_bytes": img_bytes,
                    "ext": ext,
                    "width": w,
                    "height": h,
                    "bbox": (0, 0, w or 0, h or 0),
                })
                next_index += 1
                print(f"  [orphans] Fallback: assigned xref {xref} to page {fallback_page} (stream/Resources did not link it)")
        elif unassigned:
            print(f"  [orphans] Warning: {len(unassigned)} orphan(s) never assigned (no fallback run)")
        doc.close()
        if total_with_inline > total_xref:
            print(f"  [images] Extracted {total_with_inline} total ({total_with_inline - total_xref} from inline/dict in addition to {total_xref} xref)")
    except Exception as e:
        print(f"  Error extracting images from {pdf_path}: {e}")
    return out


def extract_text_from_pdf(pdf_path, source_name):
    """Extract text from PDF with page numbers. Returns list of {text, page_number, source}.
    Uses block-based extraction when plain text is short, so catalog pages with sparse text (e.g. part numbers) are not missed."""
    out = []
    try:
        doc = fitz.open(pdf_path)
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text = page.get_text("text")
            if not text or not text.strip():
                text = _extract_text_blocks(page)
            if not text or not text.strip():
                continue
            out.append({
                "text": text,
                "page_number": page_num + 1,
                "source": source_name,
            })
        doc.close()
    except Exception as e:
        print(f"  Error reading {pdf_path}: {e}")
    return out


def _extract_text_blocks(page):
    """Fallback: extract text from blocks (dict) so we capture sparse or complex layouts."""
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


def extract_page_blocks_from_pdf(pdf_path, source_name):
    """Extract text blocks with bbox per page for layout-based image–product proximity.
    Returns list of {source_name, page_number, block_index, bbox, text}."""
    out = []
    try:
        doc = fitz.open(pdf_path)
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            try:
                d = page.get_text("dict")
            except Exception:
                continue
            blocks = d.get("blocks") or []
            for bi, block in enumerate(blocks):
                bbox = block.get("bbox") or (0, 0, 0, 0)
                if hasattr(bbox, "x0"):
                    bbox = (bbox.x0, bbox.y0, bbox.x1, bbox.y1)
                parts = []
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        s = (span.get("text") or "").strip()
                        if s:
                            parts.append(s)
                text = " ".join(parts).strip()
                if not text:
                    continue
                out.append({
                    "source_name": source_name,
                    "page_number": page_num + 1,
                    "block_index": bi,
                    "bbox": bbox,
                    "text": text,
                })
        doc.close()
    except Exception as e:
        print(f"  Error extracting page blocks from {pdf_path}: {e}")
    return out


def chunk_page_texts(page_data_list):
    """Split page texts into overlapping chunks. Yields dicts with text, source, page_number, chunk_index."""
    for page_data in page_data_list:
        text = page_data["text"]
        page_number = page_data["page_number"]
        source = page_data["source"]
        tokens = text.split()
        idx = 0
        for i in range(0, len(tokens), CHUNK_SIZE - CHUNK_OVERLAP):
            chunk_text = " ".join(tokens[i : i + CHUNK_SIZE])
            if chunk_text.strip():
                yield {
                    "text": chunk_text,
                    "source": source,
                    "page_number": page_number,
                    "chunk_index": idx,
                    "type": "text",
                }
                idx += 1


def rebuild_faiss_from_db(conn):
    """Load all chunks from DB (ordered by id), embed, and write FAISS index. Call after changing chunks."""
    cursor = conn.cursor()
    rows = cursor.execute("SELECT id, text FROM chunks ORDER BY id").fetchall()
    if not rows:
        print("[--] No chunks in database; skipping FAISS rebuild.")
        return
    texts = [r[1] for r in rows]
    print("Loading embedding model...")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    print("Creating embeddings...")
    embeddings = model.encode(texts, show_progress_bar=True)
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)
    faiss.normalize_L2(embeddings)
    index.add(embeddings.astype("float32"))
    faiss.write_index(index, FAISS_PATH)
    print(f"[OK] FAISS index saved: {FAISS_PATH} ({len(texts)} vectors, dim={dimension})")


def rebuild_one_catalog(source_id: int) -> int:
    """Rebuild a single catalog: clear its data, re-extract from PDF, insert chunks/images/page_blocks, rebuild FAISS, set last_rebuild_at. Returns 0 on success, 1 on error."""
    ensure_data_dir()
    conn = sqlite3.connect(DB_PATH)
    try:
        init_schema(conn)
        cursor = conn.cursor()
        row = cursor.execute("SELECT id, name, file_path FROM sources WHERE id = ?", (source_id,)).fetchone()
        if not row:
            print(f"[--] Source id {source_id} not found.")
            return 1
        sid, name, file_path = row[0], row[1], row[2]
        pdf_path = file_path if file_path and os.path.isfile(file_path) else os.path.join(SOURCE_DIR, name + ".pdf")
        if not os.path.isfile(pdf_path):
            print(f"[--] PDF not found: {pdf_path}")
            return 1
        print(f"  Rebuilding catalog: {name} (source_id={source_id})")
        clear_one_source(conn, source_id, IMAGES_DIR)
        pages = extract_text_from_pdf(pdf_path, name)
        imgs = extract_images_from_pdf(pdf_path, name)
        blocks = extract_page_blocks_from_pdf(pdf_path, name)
        all_chunks = list(chunk_page_texts(pages))
        if not all_chunks:
            print("[--] No chunks produced for this PDF.")
            return 1
        for c in all_chunks:
            cursor.execute(
                """INSERT INTO chunks (source_id, page_number, chunk_index, text, type, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (sid, c.get("page_number"), c.get("chunk_index", 0), c["text"], c.get("type", "text"), None),
            )
        conn.commit()
        for rec in imgs:
            img_dir = os.path.join(IMAGES_DIR, str(sid))
            os.makedirs(img_dir, exist_ok=True)
            ext = rec["ext"]
            fname = f"page_{rec['page_number']}_{rec['image_index']}.{ext}"
            rel_path = os.path.join("images", str(sid), fname)
            abs_path = os.path.join(DATA_DIR, rel_path)
            with open(abs_path, "wb") as f:
                f.write(rec["img_bytes"])
            bbox = rec.get("bbox")
            bbox_json = json.dumps(list(bbox)) if bbox and len(bbox) >= 4 else None
            cursor.execute(
                """INSERT INTO images (source_id, page_number, image_index, file_path, width, height, bbox_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (sid, rec["page_number"], rec["image_index"], rel_path.replace("\\", "/"), rec.get("width"), rec.get("height"), bbox_json),
            )
        conn.commit()
        for b in blocks:
            cursor.execute(
                """INSERT INTO page_blocks (source_id, page_number, block_index, bbox_json, text)
                   VALUES (?, ?, ?, ?, ?)""",
                (sid, b["page_number"], b["block_index"], json.dumps(list(b["bbox"])), b["text"]),
            )
        conn.commit()
        rebuild_faiss_from_db(conn)
        cursor.execute("UPDATE sources SET last_rebuild_at = datetime('now') WHERE id = ?", (sid,))
        conn.commit()
        print(f"[OK] Rebuild complete for catalog {name}. Restart the chat server to load the new index.")
    except Exception as e:
        print(f"[--] Rebuild failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        conn.close()
    return 0


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Rebuild Instrument Oracle data from source PDFs.")
    parser.add_argument("--source-id", type=int, default=None, help="Rebuild only this catalog (source id). If omitted, rebuild all.")
    args = parser.parse_args()
    if args.source_id is not None:
        return rebuild_one_catalog(args.source_id)

    print("Instrument Oracle - Rebuild from source files")
    print("=" * 50)
    print(f"Source directory: {SOURCE_DIR}")
    print(f"Database: {DB_PATH}")
    print(f"FAISS index: {FAISS_PATH}")
    print()

    if not os.path.isdir(SOURCE_DIR):
        print(f"[--] Source directory not found: {SOURCE_DIR}")
        print("Create it and add PDF files, then run this script again.")
        return 1

    pdf_files = [f for f in os.listdir(SOURCE_DIR) if f.lower().endswith(".pdf")]
    if not pdf_files:
        print(f"[--] No PDF files found in {SOURCE_DIR}")
        print("Add PDFs and run this script again.")
        return 1

    print(f"[OK] Found {len(pdf_files)} PDF(s): {', '.join(pdf_files)}")
    ensure_data_dir()

    # Remove legacy data: response cache (so old Q&A are not returned after rebuild)
    cache_file = os.path.join(ROOT, "response_cache.pkl")
    if os.path.exists(cache_file):
        try:
            os.remove(cache_file)
            print("[OK] Cleared legacy response cache (response_cache.pkl)")
        except Exception as e:
            print(f"[--] Could not remove response cache: {e}")

    conn = sqlite3.connect(DB_PATH)
    try:
        init_schema(conn)
        clear_tables(conn)
    except Exception as e:
        print(f"[--] DB error: {e}")
        return 1

    # Remove legacy images directory so we only keep images from current rebuild
    if os.path.isdir(IMAGES_DIR):
        try:
            shutil.rmtree(IMAGES_DIR)
        except Exception as e:
            print(f"[--] Could not remove old images dir: {e}")

    all_chunks = []
    all_images = []
    all_page_blocks = []
    for fn in sorted(pdf_files):
        path = os.path.join(SOURCE_DIR, fn)
        name = os.path.splitext(fn)[0]
        print(f"  Processing: {fn} ...")
        pages = extract_text_from_pdf(path, name)
        imgs = extract_images_from_pdf(path, name)
        all_images.extend(imgs)
        blocks = extract_page_blocks_from_pdf(path, name)
        all_page_blocks.extend(blocks)
        if not pages:
            print(f"    No text extracted, skipping.")
            continue
        for c in chunk_page_texts(pages):
            all_chunks.append(c)
        print(f"    Pages: {len(pages)}, chunks: {sum(1 for c in all_chunks if c['source'] == name)}, images: {len(imgs)}, blocks: {len(blocks)}")

    if not all_chunks:
        print("[--] No chunks produced. Check PDF content.")
        conn.close()
        return 1

    total_words = sum(len(c["text"].split()) for c in all_chunks)
    pages_with_text = len({(c["source"], c["page_number"]) for c in all_chunks})
    print(f"\n[OK] Total chunks: {len(all_chunks)}  (from {pages_with_text} pages, ~{total_words} words)")
    print(f"     Avg ~{total_words // max(1, len(all_chunks))} words/chunk, ~{len(all_chunks) // max(1, pages_with_text)} chunks/page")

    # Get or create sources (by unique name) so existing source_id and catalog_profiles persist
    source_names = set(c["source"] for c in all_chunks)
    cursor = conn.cursor()
    file_path_by_name = {name: os.path.join(SOURCE_DIR, name + ".pdf") for name in source_names}
    for name in source_names:
        existing = cursor.execute("SELECT id FROM sources WHERE name = ?", (name,)).fetchone()
        if existing:
            cursor.execute("UPDATE sources SET file_path = ? WHERE id = ?", (file_path_by_name[name], existing[0]))
        else:
            cursor.execute(
                "INSERT INTO sources (name, file_path) VALUES (?, ?)",
                (name, file_path_by_name[name]),
            )
    # Remove sources (and their catalog_profiles, products) for PDFs no longer in source_files
    for row in cursor.execute("SELECT id, name FROM sources").fetchall():
        sid, sname = row[0], row[1]
        if sname not in source_names:
            cursor.execute("DELETE FROM product_images WHERE product_id IN (SELECT id FROM products WHERE source_id = ?)", (sid,))
            cursor.execute("DELETE FROM products WHERE source_id = ?", (sid,))
            cursor.execute("DELETE FROM catalog_profiles WHERE source_id = ?", (sid,))
            cursor.execute("DELETE FROM sources WHERE id = ?", (sid,))
    conn.commit()
    source_ids = {row[1]: row[0] for row in cursor.execute("SELECT id, name FROM sources").fetchall()}

    # Insert chunks in order (order must match FAISS index)
    for i, c in enumerate(all_chunks):
        sid = source_ids[c["source"]]
        cursor.execute(
            """INSERT INTO chunks (source_id, page_number, chunk_index, text, type, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (sid, c.get("page_number"), c.get("chunk_index", 0), c["text"], c.get("type", "text"), None),
        )
    conn.commit()

    # Write image files and insert into images table
    if all_images:
        for rec in all_images:
            sid = source_ids.get(rec["source_name"])
            if sid is None:
                continue
            img_dir = os.path.join(IMAGES_DIR, str(sid))
            os.makedirs(img_dir, exist_ok=True)
            ext = rec["ext"]
            fname = f"page_{rec['page_number']}_{rec['image_index']}.{ext}"
            rel_path = os.path.join("images", str(sid), fname)
            abs_path = os.path.join(DATA_DIR, rel_path)
            with open(abs_path, "wb") as f:
                f.write(rec["img_bytes"])
            bbox = rec.get("bbox")
            bbox_json = json.dumps(list(bbox)) if bbox and len(bbox) >= 4 else None
            cursor.execute(
                """INSERT INTO images (source_id, page_number, image_index, file_path, width, height, bbox_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (sid, rec["page_number"], rec["image_index"], rel_path.replace("\\", "/"), rec.get("width"), rec.get("height"), bbox_json),
            )
        conn.commit()
        print(f"[OK] Extracted and saved {len(all_images)} images to {IMAGES_DIR}")

    # Insert page blocks (for layout-based image–product proximity)
    if all_page_blocks:
        for b in all_page_blocks:
            sid = source_ids.get(b["source_name"])
            if sid is None:
                continue
            cursor.execute(
                """INSERT INTO page_blocks (source_id, page_number, block_index, bbox_json, text)
                   VALUES (?, ?, ?, ?, ?)""",
                (sid, b["page_number"], b["block_index"], json.dumps(list(b["bbox"])), b["text"]),
            )
        conn.commit()
        print(f"[OK] Inserted {len(all_page_blocks)} page blocks for proximity linking")

    # Embeddings and FAISS
    print("Loading embedding model...")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    texts = [c["text"] for c in all_chunks]
    print("Creating embeddings...")
    embeddings = model.encode(texts, show_progress_bar=True)
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)
    faiss.normalize_L2(embeddings)
    index.add(embeddings.astype("float32"))
    faiss.write_index(index, FAISS_PATH)
    print(f"[OK] FAISS index saved: {FAISS_PATH} ({len(all_chunks)} vectors, dim={dimension})")

    # Record last_rebuild_at for each rebuilt source
    for sid in source_ids.values():
        cursor.execute("UPDATE sources SET last_rebuild_at = datetime('now') WHERE id = ?", (sid,))
    conn.commit()

    conn.close()
    print("\n[OK] Rebuild complete. Chunks, images, and page blocks repopulated from current source PDFs.")
    print("     Catalog analysis profiles (catalog_profiles table) are preserved across rebuilds.")
    print("     Restart the chat server so it loads the new index.")
    return 0


if __name__ == "__main__":
    exit(main())
