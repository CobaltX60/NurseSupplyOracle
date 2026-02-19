#!/usr/bin/env python3
"""
Catalog profile loader and zone detection for per-catalog image–product association.
Profiles are YAML files that describe delimiter rules (e.g. orange horizontal lines) and
zone-based image association. Used by the product listing build when linking images to products.
"""
import os
import re
import sqlite3

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
CATALOG_PROFILES_DIR = os.path.join(ROOT, "catalog_profiles")

try:
    import yaml
except ImportError:
    yaml = None


def load_profile(profile_path: str) -> dict | None:
    """Load a catalog profile from a YAML file. Returns None if file missing or invalid."""
    if not profile_path or not os.path.isfile(profile_path):
        return None
    if not yaml:
        return None
    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return None


def resolve_profile_for_source(conn, source_id: int) -> tuple[dict | None, str | None]:
    """
    Resolve the catalog profile for a source.
    Returns (profile_dict, profile_path) or (None, None).
    Uses: 1) source.profile_path if set, 2) catalog_profiles/<source_name>.yaml.
    """
    row = conn.execute(
        "SELECT name, file_path FROM sources WHERE id = ?",
        (source_id,),
    ).fetchone()
    if not row:
        return None, None
    name, file_path = row[0], row[1]

    # 1) Explicit profile_path (if we add the column and it's set)
    try:
        r2 = conn.execute(
            "SELECT profile_path FROM sources WHERE id = ?",
            (source_id,),
        ).fetchone()
        if r2 and r2[0] and isinstance(r2[0], str) and r2[0].strip():
            ppath = r2[0].strip()
            if not os.path.isabs(ppath):
                ppath = os.path.join(ROOT, ppath)
            prof = load_profile(ppath)
            if prof is not None:
                return prof, ppath
    except (sqlite3.OperationalError, TypeError):
        pass

    # 2) By source name: catalog_profiles/<name>.yaml
    for candidate in (name, os.path.splitext(os.path.basename(file_path or ""))[0]):
        if not candidate:
            continue
        safe = re.sub(r"[^\w\-]", "_", candidate).strip("_")
        if not safe:
            safe = candidate
        ppath = os.path.join(CATALOG_PROFILES_DIR, safe + ".yaml")
        if os.path.isfile(ppath):
            prof = load_profile(ppath)
            if prof is not None:
                return prof, ppath
        ppath = os.path.join(CATALOG_PROFILES_DIR, candidate + ".yaml")
        if os.path.isfile(ppath):
            prof = load_profile(ppath)
            if prof is not None:
                return prof, ppath
    return None, None


def normalize_color_rgb(rgb) -> list[float]:
    """
    Return [r, g, b] in 0-1 range. If any value exceeds 1.0, assume 0-255 and divide all by 255.
    PyMuPDF uses 0-1; Gemini may return 0-255. Call when loading/using zone_detection.color_rgb.
    """
    if not rgb or len(rgb) < 3:
        return [0.95, 0.47, 0.15]
    r, g, b = float(rgb[0]), float(rgb[1]), float(rgb[2])
    if max(r, g, b) > 1.0:
        r, g, b = r / 255.0, g / 255.0, b / 255.0
    return [r, g, b]


def get_zone_boundaries(
    pdf_path: str, page_index: int, profile: dict, return_diagnostics: bool = False
) -> list | tuple:
    """
    Detect zone boundaries on a PDF page using the profile's zone_detection (from catalog layout analysis).
    Profile must have zone_detection.method (e.g. colored_horizontal_rules) and optional color_rgb, etc.
    Returns a list of (y0, y1) in page coordinates (points), one per zone.
    If return_diagnostics=True, returns (zones, diagnostics_dict) where diagnostics_dict has:
    color_rgb, tolerance, drawings_checked, color_matches, zone_divider_y_coords, zones_list.
    If detection fails or profile has no zone_detection, returns empty list (caller may treat as single zone).
    """
    try:
        import fitz
    except ImportError:
        return [] if not return_diagnostics else ([], {})

    zd = profile.get("zone_detection") or {}
    method = zd.get("method")
    # When method is whitespace (or missing), return single zone (full page) so spatial pipeline can run with column detection only
    if method == "whitespace" or method not in ("colored_horizontal_rules", "colored_horizontal_rule", "orange_horizontal_rule"):
        try:
            doc = fitz.open(pdf_path)
            if page_index < 0 or page_index >= len(doc):
                doc.close()
                return [] if not return_diagnostics else ([], {})
            page = doc.load_page(page_index)
            page_height = page.rect.height
            doc.close()
            page_num = page_index + 1
            print(f"[Page {page_num}] Zone detection: method={method or 'none'} -> single zone (full page). Zones created: 1")
            zones = [(0.0, page_height)]
            if return_diagnostics:
                return zones, {"method": method or "none", "color_rgb": None, "tolerance": None, "drawings_checked": 0, "color_matches": 0, "zone_divider_y_coords": [], "zones_list": zones}
            return zones
        except Exception:
            return [] if not return_diagnostics else ([], {})
    det = zd

    color_rgb = normalize_color_rgb(det.get("color_rgb") or [0.95, 0.47, 0.15])
    tolerance = float(det.get("color_tolerance") or 0.15)
    min_width = float(det.get("min_width_pts") or 100)
    max_height = float(det.get("max_height_pts") or 5)

    page_num = page_index + 1
    print(f"[Page {page_num}] Zone detection: color_rgb (normalized) = {color_rgb}, tolerance = {tolerance}")

    try:
        doc = fitz.open(pdf_path)
        if page_index < 0 or page_index >= len(doc):
            doc.close()
            return [] if not return_diagnostics else ([], {})
        page = doc.load_page(page_index)
        page_height = page.rect.height
        page_width = page.rect.width
        y_coords = []
        drawings = page.get_drawings()
        doc.close()
    except Exception:
        return [] if not return_diagnostics else ([], {})

    # Debug: print first 10 wide drawings (width > 100pt) to see actual orange line color/fill
    wide = []
    for d in drawings:
        rect = d.get("rect")
        if rect is None:
            continue
        if hasattr(rect, "x0"):
            w = rect.x1 - rect.x0
            h = rect.y1 - rect.y0
            r = rect
        else:
            w = rect[2] - rect[0] if len(rect) >= 4 else 0
            h = rect[3] - rect[1] if len(rect) >= 4 else 0
            r = rect
        if w > 100:
            wide.append((r, w, h, d.get("color"), d.get("fill")))
    print(f"[Page {page_num}] Wide drawings (width > 100pts):")
    for idx, (rect, w, h, color, fill) in enumerate(wide[:10]):
        if hasattr(rect, "x0"):
            rect_str = f"[{rect.x0:.1f},{rect.y0:.1f},{rect.x1:.1f},{rect.y1:.1f}]"
        else:
            rect_str = str(list(rect)[:4]) if len(rect) >= 4 else str(rect)
        print(f"  drawing {idx}: rect={rect_str} width={w:.1f} height={h:.1f} color={color} fill={fill}")

    def color_matches(c, tol):
        if not c or len(c) < 3:
            return False
        r, g, b = float(c[0]), float(c[1]), float(c[2])
        tr, tg, tb = color_rgb[0], color_rgb[1], color_rgb[2]
        return (
            abs(r - tr) <= tol
            and abs(g - tg) <= tol
            and abs(b - tb) <= tol
        )

    def count_matches(tol):
        y_list = []
        m = 0
        for d in drawings:
            color = d.get("color")
            fill = d.get("fill")
            if not color_matches(color, tol) and not color_matches(fill, tol):
                continue
            rect = d.get("rect")
            if rect is None:
                continue
            if hasattr(rect, "x0"):
                w = rect.x1 - rect.x0
                h = rect.y1 - rect.y0
                y0 = rect.y0
            else:
                w = rect[2] - rect[0] if len(rect) >= 4 else 0
                h = rect[3] - rect[1] if len(rect) >= 4 else 0
                y0 = rect[1] if len(rect) >= 2 else 0
            if w >= min_width and 0 < h <= max_height:
                y_list.append(y0)
                m += 1
        return y_list, m

    y_coords, matched = count_matches(tolerance)
    if matched == 0 and tolerance < 0.15:
        tolerance_fallback = 0.15
        print(f"[Page {page_num}] Zone detection: 0 matches with tolerance={tolerance}; retrying with tolerance={tolerance_fallback} (profile may need updating)")
        y_coords, matched = count_matches(tolerance_fallback)
        tolerance = tolerance_fallback

    num_drawings = len(drawings)
    print(f"[Page {page_num}] Found {num_drawings} drawings, {matched} matched zone divider criteria")

    y_coords = sorted(set(y_coords))
    print(f"[Page {page_num}] Zone divider y-coordinates: {y_coords}")

    if not y_coords:
        zones = [(0.0, page_height)]
    else:
        zones = []
        zones.append((0.0, y_coords[0]))
        for i in range(len(y_coords) - 1):
            zones.append((y_coords[i], y_coords[i + 1]))
        zones.append((y_coords[-1], page_height))

    print(f"[Page {page_num}] Zones created: {len(zones)}")
    if return_diagnostics:
        return zones, {
            "color_rgb": color_rgb,
            "tolerance": tolerance,
            "drawings_checked": num_drawings,
            "color_matches": matched,
            "zone_divider_y_coords": list(y_coords),
            "zones_list": zones,
        }
    return zones


def get_product_cells_grid(
    pdf_path: str, page_index: int, profile: dict, return_diagnostics: bool = False
) -> list | tuple:
    """
    Detect product cells on a page by finding short colored line segments that act as
    product header markers and computing a grid of rectangular cells from them.

    Reads color/size parameters from ``layout_structure.patterns_observed`` first, then
    falls back to ``zone_detection.color_rgb``.  Short segments (< half page width) are
    used; full-width bars are ignored.

    Returns a list of (x0, y0, x1, y1) in page coordinates, one per cell.
    If *return_diagnostics* is True, returns ``(cells, diagnostics_dict)``.
    """
    try:
        import fitz
    except ImportError:
        return [] if not return_diagnostics else ([], {})

    # --- resolve color and size parameters from profile ---
    color_rgb = None
    tol = 0.2
    w_hint = None
    h_hint = None

    ls = profile.get("layout_structure") or {}
    patterns = ls.get("patterns_observed") or []
    if patterns and isinstance(patterns[0], dict):
        seps = patterns[0].get("separator_elements") or []
        for s in seps:
            if not isinstance(s, dict) or s.get("spans_full_page_width"):
                continue
            stype = (s.get("type") or "").lower()
            if stype in ("line_segment", "line") or s.get("role") in ("product_cell_top_marker", "row_separator"):
                color_rgb = normalize_color_rgb(s.get("color_rgb") or [0.95, 0.47, 0.15])
                w_hint = float(s.get("typical_width_pts") or 0) or None
                h_hint = float(s.get("typical_height_pts") or 0) or None
                tol = float(s.get("color_tolerance") or 0.2)
                break

    if color_rgb is None:
        zd = profile.get("zone_detection") or {}
        zd_color = zd.get("color_rgb")
        if zd_color:
            color_rgb = normalize_color_rgb(zd_color)
            tol = float(zd.get("color_tolerance") or 0.2)
            w_hint = float(zd.get("min_width_pts") or 0) or None
            h_hint = float(zd.get("max_height_pts") or 0) or None

    if color_rgb is None:
        return [] if not return_diagnostics else ([], {"error": "no color information in profile"})

    # --- open the PDF page and extract drawings ---
    try:
        doc = fitz.open(pdf_path)
        if page_index < 0 or page_index >= len(doc):
            doc.close()
            return [] if not return_diagnostics else ([], {})
        page = doc.load_page(page_index)
        page_rect = page.rect
        page_height = page_rect.height
        page_width = page_rect.width
        drawings = page.get_drawings()
        doc.close()
    except Exception:
        return [] if not return_diagnostics else ([], {})

    half_page = page_width / 2.0
    w_min = (w_hint * 0.5) if w_hint else 20.0
    # Allow markers up to 70% of page width — wide columns produce wide markers.
    # The full-page category header bar is excluded by h_max instead.
    w_max = min((w_hint * 4.0) if w_hint else page_width * 0.7, page_width * 0.7)
    h_max = (h_hint * 3.0) if h_hint else 15.0

    def color_matches(c, tolerance):
        if not c or len(c) < 3:
            return False
        r, g, b = float(c[0]), float(c[1]), float(c[2])
        tr, tg, tb = color_rgb[0], color_rgb[1], color_rgb[2]
        if max(r, g, b) > 1.0:
            r, g, b = r / 255.0, g / 255.0, b / 255.0
        return abs(r - tr) <= tolerance and abs(g - tg) <= tolerance and abs(b - tb) <= tolerance

    segments = []
    for d in drawings:
        color = d.get("color")
        fill = d.get("fill")
        if not color_matches(color, tol) and not color_matches(fill, tol):
            continue
        rect = d.get("rect")
        if rect is None:
            continue
        if hasattr(rect, "x0"):
            w, h = rect.x1 - rect.x0, rect.y1 - rect.y0
            x0, y0, x1, y1 = rect.x0, rect.y0, rect.x1, rect.y1
        else:
            if len(rect) < 4:
                continue
            w = rect[2] - rect[0]
            h = rect[3] - rect[1]
            x0, y0, x1, y1 = rect[0], rect[1], rect[2], rect[3]
        if w_min <= w <= w_max and h <= h_max:
            segments.append((x0, y0, x1, y1))

    if not segments:
        if return_diagnostics:
            return [], {"segments_found": 0, "color_rgb": color_rgb}
        return []

    # --- group segments by row (y within 4 pts) ---
    y_key: dict[float, list] = {}
    for (x0, y0, x1, y1) in segments:
        yk = round(y0 / 4.0) * 4.0
        if yk not in y_key:
            y_key[yk] = []
        y_key[yk].append((x0, y0, x1, y1))
    row_ys = sorted(y_key.keys())

    def _merge_overlapping(segs):
        """Merge segments with overlapping x-ranges (handles duplicate draws)."""
        if len(segs) <= 1:
            return segs
        segs = sorted(segs, key=lambda s: s[0])
        merged = [list(segs[0])]
        for s in segs[1:]:
            last = merged[-1]
            if s[0] <= last[2] + 2.0:  # x-ranges overlap or nearly touch
                last[2] = max(last[2], s[2])
            else:
                merged.append(list(s))
        return [tuple(m) for m in merged]

    # Row bounds: row i spans from row_ys[i] to row_ys[i+1] (or page_height).
    # Column bounds: midpoint of the gap between adjacent segments (right edge
    # of the previous segment to left edge of the next). This is more accurate
    # than midpoints between centers when segments have varying widths.
    cells = []
    for i, ry in enumerate(row_ys):
        row_segs = _merge_overlapping(y_key[ry])
        y0_row = ry
        y1_row = row_ys[i + 1] if i + 1 < len(row_ys) else page_height
        for j in range(len(row_segs)):
            col_left = (row_segs[j - 1][2] + row_segs[j][0]) / 2.0 if j > 0 else 0.0
            col_right = (row_segs[j][2] + row_segs[j + 1][0]) / 2.0 if j < len(row_segs) - 1 else page_width
            cells.append((col_left, float(y0_row), col_right, float(y1_row)))

    page_num = page_index + 1
    print(f"[Page {page_num}] Grid layout: {len(segments)} marker segments -> {len(cells)} cells")
    if return_diagnostics:
        return cells, {"segments_found": len(segments), "rows": len(row_ys), "cells": len(cells), "color_rgb": color_rgb}
    return cells


def zone_for_y(y: float, zones):
    """Return the zone index (0-based) that contains the given y coordinate."""
    for i, (y0, y1) in enumerate(zones):
        if y0 <= y < y1:
            return i
    if zones and y >= zones[-1][1]:
        return len(zones) - 1
    return 0
