#!/usr/bin/env python3
"""
Catalog analysis (Phase 2): run once per catalog using Gemini 2.5 Pro to produce
a machine-readable profile. Profile loader: prefer catalog_profiles table, else default_profile.json.
"""
import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(ROOT, "data")
DEFAULT_PROFILE_PATH = os.path.join(ROOT, "default_profile.json")

# Model for analysis (expensive, smart). Processing uses gemini-2.0-flash.
GEMINI_ANALYSIS_MODEL = os.environ.get("GEMINI_ANALYSIS_MODEL", "gemini-2.5-pro").strip() or "gemini-2.5-pro"


def load_default_profile():
    """Load default_profile.json. Returns dict or empty dict on error."""
    if not os.path.isfile(DEFAULT_PROFILE_PATH):
        return {}
    try:
        with open(DEFAULT_PROFILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_analysis_profile_for_source(conn, source_id: int):
    """
    Load the analysis profile for a catalog. Uses catalog_profiles if status is
    'analyzed' or 'verified'; otherwise returns default profile.
    """
    try:
        row = conn.execute(
            "SELECT profile_json, status FROM catalog_profiles WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        if row and row[1] in ("analyzed", "verified"):
            try:
                return json.loads(row[0])
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
    except sqlite3.OperationalError:
        pass
    return load_default_profile()


def get_analysis_profile_status(conn, source_id: int):
    """
    Return profile status for UI: None (no row), 'pending', 'analyzed', 'verified'.
    Also return analyzed_at, analyzed_by_model, catalog_id, manufacturer for display.
    """
    try:
        row = conn.execute(
            "SELECT status, analyzed_at, analyzed_by_model, catalog_id, manufacturer FROM catalog_profiles WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        if row:
            return {
                "status": row[0],
                "analyzed_at": row[1],
                "analyzed_by_model": row[2],
                "catalog_id": row[3],
                "manufacturer": row[4],
            }
    except sqlite3.OperationalError:
        pass
    return None


def _get_page_metrics(page) -> dict:
    """Return block_count, image_count, drawing_count for a fitz page. Used for diversity-based sample selection."""
    metrics = {"block_count": 0, "image_count": 0, "drawing_count": 0, "dominant_large_rect": False}
    try:
        text_dict = page.get_text("dict")
        metrics["block_count"] = len(text_dict.get("blocks", []))
    except Exception:
        pass
    try:
        metrics["image_count"] = len(page.get_images(full=True))
    except Exception:
        pass
    try:
        drawings = page.get_drawings()
        metrics["drawing_count"] = len(drawings)
        # Heuristic: page dominated by one large colored rectangle (section divider)
        if drawings:
            page_rect = page.rect
            area = page_rect.width * page_rect.height
            for d in drawings:
                r = d.get("rect")
                if r is None:
                    continue
                if hasattr(r, "width"):
                    a = r.width * r.height
                else:
                    a = (r[2] - r[0]) * (r[3] - r[1]) if len(r) >= 4 else 0
                if area and a / area > 0.4:
                    metrics["dominant_large_rect"] = True
                    break
    except Exception:
        pass
    return metrics


def _looks_like_divider_or_title(metrics: dict, min_blocks_content: int = 3, min_images_content: int = 1) -> bool:
    """True if page likely section divider, title, or blank (exclude from product-page diversity)."""
    blocks = metrics.get("block_count", 0)
    images = metrics.get("image_count", 0)
    if metrics.get("dominant_large_rect") and blocks < 5 and images < 2:
        return True
    if blocks < min_blocks_content and images < min_images_content:
        return True
    return False


def get_page_metrics(pdf_path: str, page_index: int) -> dict:
    """Return block_count, image_count, drawing_count for a page. Used for page-type filtering."""
    try:
        import fitz
    except ImportError:
        return {"block_count": 0, "image_count": 0, "drawing_count": 0, "dominant_large_rect": False}
    try:
        doc = fitz.open(pdf_path)
        if page_index < 0 or page_index >= len(doc):
            doc.close()
            return {"block_count": 0, "image_count": 0, "drawing_count": 0, "dominant_large_rect": False}
        page = doc.load_page(page_index)
        m = _get_page_metrics(page)
        doc.close()
        return m
    except Exception:
        return {"block_count": 0, "image_count": 0, "drawing_count": 0, "dominant_large_rect": False}


def should_skip_page_for_products(pdf_path: str, page_index: int, profile: dict) -> bool:
    """
    Return True if this page should be skipped for product extraction (section divider, title, index).
    Uses profile.page_types (contains_products: false) and metrics-based heuristics when detection_rules are not machine-executable.
    """
    page_types = profile.get("page_types") or []
    non_product_types = [pt for pt in page_types if isinstance(pt, dict) and pt.get("contains_products") is False]
    if not non_product_types:
        return False
    metrics = get_page_metrics(pdf_path, page_index)
    # Heuristic: pages with very few blocks and few images are likely divider/title; dominant large rect supports divider
    if _looks_like_divider_or_title(metrics, min_blocks_content=4, min_images_content=2):
        return True
    return False


def select_diverse_sample_pages(doc, total_pages: int, min_pages: int = 8, max_pages: int = 12) -> list[int]:
    """
    Select 8-12 sample pages (1-based) maximizing layout diversity. Uses block count, image count,
    drawing count. Excludes likely section dividers/title pages. Always includes first and last product page.
    """
    if total_pages <= 0:
        return []
    # Compute metrics for every page
    page_metrics = []
    for i in range(total_pages):
        page = doc.load_page(i)
        m = _get_page_metrics(page)
        m["page_number_1based"] = i + 1
        m["page_index"] = i
        page_metrics.append(m)
    # Product-like pages: not divider/title
    product_like = [m for m in page_metrics if not _looks_like_divider_or_title(m)]
    first_product = product_like[0]["page_number_1based"] if product_like else 1
    last_product = product_like[-1]["page_number_1based"] if product_like else total_pages
    # With content = at least some blocks or images (for "fewest" we don't want completely empty)
    with_content = [m for m in page_metrics if m["block_count"] >= 1 or m["image_count"] >= 1]
    # Sort by block count: 2 with most, 2 with fewest (with content)
    by_blocks = sorted(with_content, key=lambda x: -x["block_count"])
    most_blocks = [by_blocks[i]["page_number_1based"] for i in range(min(2, len(by_blocks)))]
    fewest_blocks = [by_blocks[-(i + 1)]["page_number_1based"] for i in range(min(2, len(by_blocks))) if len(by_blocks) > i]
    # Sort by image count: 2 with most, 2 with fewest
    by_images = sorted(with_content, key=lambda x: -x["image_count"])
    most_images = [by_images[i]["page_number_1based"] for i in range(min(2, len(by_images)))]
    fewest_images = [by_images[-(i + 1)]["page_number_1based"] for i in range(min(2, len(by_images))) if len(by_images) > i]
    # 2-4 spread by page number (across catalog)
    step = max(1, (total_pages - 1) // 3) if total_pages > 1 else 0
    spread = [1 + (j * step) for j in range(4) if 1 + (j * step) <= total_pages][:4]
    if total_pages > 1:
        spread.append(total_pages)
    # Combine and dedupe; always include first and last product page
    candidates = list(dict.fromkeys([first_product, last_product] + most_blocks + fewest_blocks + most_images + fewest_images + spread))
    candidates = sorted(set(candidates))
    # Trim to max_pages, try to keep 8-12
    if len(candidates) > max_pages:
        # Keep first_product, last_product and spread the rest
        keep = {first_product, last_product}
        rest = [p for p in candidates if p not in keep]
        # Take evenly from rest
        step_r = len(rest) / (max_pages - len(keep)) if rest and (max_pages - len(keep)) > 0 else 1
        for j in range(max_pages - len(keep)):
            idx = min(int(j * step_r), len(rest) - 1)
            if 0 <= idx < len(rest):
                keep.add(rest[idx])
        candidates = sorted(keep)
    if len(candidates) < min_pages and total_pages >= min_pages:
        # Add more spread until we have at least min_pages
        for p in range(1, total_pages + 1):
            if len(candidates) >= min_pages:
                break
            if p not in candidates:
                candidates.append(p)
        candidates = sorted(candidates)
    return candidates[:max_pages]


def _extract_page_spatial_data(page, page_num: int):
    """Extract drawings, fonts, and image positions for one page. Returns dict."""
    out = {"page_number": page_num, "drawings": [], "fonts": [], "image_positions": []}
    try:
        import fitz
    except ImportError:
        return out
    try:
        drawings = page.get_drawings()
        for d in drawings:
            rect = d.get("rect")
            if rect is None:
                continue
            if hasattr(rect, "x0"):
                out["drawings"].append({
                    "rect": [rect.x0, rect.y0, rect.x1, rect.y1],
                    "color": d.get("color"),
                    "fill": d.get("fill"),
                    "width": getattr(rect, "width", rect.x1 - rect.x0),
                    "height": getattr(rect, "height", rect.y1 - rect.y0),
                })
            else:
                out["drawings"].append({
                    "rect": list(rect) if len(rect) >= 4 else [0, 0, 0, 0],
                    "color": d.get("color"),
                    "fill": d.get("fill"),
                    "width": rect[2] - rect[0] if len(rect) >= 4 else 0,
                    "height": rect[3] - rect[1] if len(rect) >= 4 else 0,
                })
    except Exception:
        pass
    try:
        text_dict = page.get_text("dict")
        fonts_found = set()
        for block in text_dict.get("blocks", []):
            if block.get("type") == 0:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        font = span.get("font", "")
                        size = round(span.get("size", 0), 1)
                        fonts_found.add((font, size))
        out["fonts"] = [{"font": f[0], "size": f[1]} for f in sorted(fonts_found)]
    except Exception:
        pass
    try:
        for img in page.get_images(full=True):
            xref = img[0]
            for rect in page.get_image_rects(xref):
                if hasattr(rect, "x0"):
                    out["image_positions"].append({
                        "bbox": [rect.x0, rect.y0, rect.x1, rect.y1],
                        "width": rect.width,
                        "height": rect.height,
                    })
                else:
                    out["image_positions"].append({
                        "bbox": list(rect) if len(rect) >= 4 else [0, 0, 0, 0],
                        "width": rect[2] - rect[0] if len(rect) >= 4 else 0,
                        "height": rect[3] - rect[1] if len(rect) >= 4 else 0,
                    })
    except Exception:
        pass
    return out


ANALYSIS_PROMPT = r"""You are analyzing sample pages from a surgical instrument catalog. Your job is to produce a comprehensive, machine-readable processing profile that a PDF parser can use to automatically extract products, associate images, and structure data from EVERY page in this catalog — not just the pages shown here.

I am showing you 8-12 sample pages as images, selected to represent the full range of layout variations in this catalog. I am also providing supplementary data extracted from these pages: vector drawing paths with colors, font information, and image positions with sizes.

Your profile must handle every layout variation visible across these samples. Study the pages carefully before answering.

A key role of this assessment is IMAGE EXTRACTION AND ASSOCIATION: you must describe exactly how images on the page (large photos, small detail drawings, mid-sized) should be linked to products. This description will be used to improve downstream image–product association. Be specific and actionable.

## SECTION 1: PAGE TYPES

Categorize every distinct page type you see. For each type, describe:
- What makes this page type visually distinct
- Whether it contains product data or should be skipped
- How to detect this page type programmatically

Common types to look for: product listing pages, section divider pages, index/table of contents pages, title pages, blank pages, pages with special layouts (single large product, comparison tables).

## SECTION 2: PAGE LAYOUT STRUCTURE

Look at each sample page and describe exactly how products are spatially organized.
Do NOT assume any specific layout model. Describe what you actually see.

For each distinct layout pattern you observe across the sample pages:

- How are products arranged? (grid, single column list, multi-column, free-form, table with headers, or something else)
- What visual elements separate one product from another? Describe each element precisely: its color (RGB), size, position, and whether it is a full-page-width line, a column-width line segment, a whitespace gap, a colored bar, or something else
- Are the separator elements continuous across the page or are they short segments repeated per product?
- How many products appear per page? Does this vary?
- Is there a consistent grid structure? If so, how many rows and columns, and what defines the cell boundaries?
- How would you programmatically determine which rectangular region of the page belongs to each product?

CRITICAL: If the visual separators are short line segments (e.g., 100-150pts wide) rather than full-page-width lines, do NOT describe them as "horizontal zone dividers." Instead describe them as what they are: per-product or per-column header markers that can be used to define a grid.

Provide your layout description as a structured object that a PDF parser can use to compute the bounding rectangle for each product on any page.

## SECTION 3: PRODUCT HIERARCHY

For each product group, describe the text hierarchy:

**Family/Product Name:**
- How is it formatted? (font, weight, size, case)
- Where does it appear relative to the product cell or layout top?
- Can the same family name appear in multiple zones on the same page with different variants?

**Shared/Family Attributes:**
- What are these? (material, overall length, general description)
- How are they formatted differently from the family name and variant text?
- Where do they appear relative to the family name?

**Catalog Numbers / MPNs:**
- List EVERY distinct format pattern you see across all sample pages
- Provide a regex for each pattern
- Are some displayed in boxes, pills, or rounded rectangles while others are plain text? What determines this?
- Do any have letter suffixes (e.g., -T for titanium)?
- Do any have sub-variant extensions (e.g., -001)?

**Variant-Specific Text:**
- What text belongs to a specific catalog number vs the family?
- How to determine where one variant's text ends and the next begins

## SECTION 4: IMAGE TYPES AND ASSOCIATION (CRITICAL)

This section is central to the layout assessment. Your output here directly improves how images are associated with products. Analyze every type of image on the sample pages and describe exactly how each type should be associated with products.

**Large Product Photos:**
- What qualifies as a large product photo? (minimum dimensions)
- Is a large photo associated with the product family or a specific variant?
- Where do large photos typically sit relative to their text? Does this vary?
- Can a large photo extend beyond its column's text boundaries?
- Can a product family have zero large photos?
- Can a product family have multiple large photos?

**Small Detail Drawings:**
- What are these? (tip profiles, cross-sections, blade shapes, spoon shapes)
- What qualifies as a small detail drawing? (maximum dimensions)
- Is each small drawing associated with a specific catalog number?
- How to determine which catalog number a small drawing belongs to — what spatial relationship do they have?
- Can one catalog number have multiple detail drawings?
- Can there be detail drawings that don't directly associate with a specific catalog number?

**Vector Drawings vs Embedded Images:**
- Are the small detail drawings typically embedded bitmap images or are they rendered as vector paths in the PDF content stream?
- How can the parser distinguish decorative elements (horizontal rules, borders, boxes around catalog numbers) from actual product drawings?

**Image Size Gap:**
- Is there a clear size threshold separating large photos from small drawings, or do some images fall in an ambiguous middle range?
- What should happen with mid-sized images?

**Image association instructions (required):** In the output JSON, set image_association.image_association_instructions to 2–4 short, actionable sentences that tell the extraction step exactly how to assign each image (Image 0, 1, 2…) to the correct product(s). These instructions will be passed to the model that links images to products; be specific to this catalog's layout.

## SECTION 5: SPECIAL ELEMENTS

**Symbols and Indicators:**
- List every symbol, icon, or marker that appears near products
- What does each mean?
- Where do they appear relative to catalog numbers?

**Badges and Labels:**
- Are there special text badges (e.g., "titanium", material callouts)?
- How are they formatted and where do they appear?

**Legends and Keys:**
- Is there a page legend/key explaining symbols?
- Where does it appear and how to detect it?

## SECTION 6: PAGE FURNITURE TO IGNORE

List every non-product element that appears on pages and should be excluded from extraction:
- Headers (describe format and position)
- Footers (describe format and position)
- Margin rulers or scales (which margin, dimensions)
- Section banners (position, color, content)
- Multilingual translations (position, how to detect)
- Page numbers (position, format)
- Any other repeated decorative or navigational elements

## SECTION 7: VARIABILITY AND EDGE CASES

This section is critical. Describe:
- What varies most between pages?
- What stays perfectly consistent?
- What are the hardest pages to parse and why?
- Are there any pages where the standard rules would fail? What alternative approach is needed?
- Can products span across the full page width with no columns?
- Can a single product take up an entire page?
- Are there any unusual layouts not covered by the above sections?

## OUTPUT FORMAT

Produce a single JSON object that is the profile itself. The root of your response must be this object — do not wrap it in another key (e.g. do not use a root key like "catalog_profile"). Every section below must be populated from your analysis of the sample pages. Do not omit sections or leave placeholder values; use the supplementary spatial data and images to fill every field.

{
  "catalog_id": "<suggested_id>",
  "manufacturer": "<detected manufacturer>",

  "page_types": [
    {
      "type": "<product_listing|section_divider|index|title|other>",
      "description": "<how to identify this page type>",
      "detection_rules": "<programmatic detection method>",
      "contains_products": true
    }
  ],

  "layout_structure": {
    "primary_pattern": "<grid|zones_and_columns|table|single_column|free_form>",
    "patterns_observed": [
      {
        "pattern_type": "<grid|zones_and_columns|table|etc>",
        "description": "<how this pattern works>",
        "separator_elements": [
          {
            "type": "<line_segment|full_width_line|whitespace|colored_bar>",
            "color_rgb": [0, 0, 0],
            "typical_width_pts": 0,
            "typical_height_pts": 0,
            "role": "<product_cell_top_marker|row_separator|column_separator|zone_divider>",
            "spans_full_page_width": false
          }
        ],
        "grid_detection": {
          "row_markers": "<description of how to find rows>",
          "column_markers": "<description of how to find columns>",
          "cell_computation": "<description of how to compute each product cell rectangle>"
        },
        "pages_using_this_pattern": [1, 2, 3],
        "typical_products_per_page": 0
      }
    ]
  },

  "product_hierarchy": {
    "family_name": {
      "detection": "<description>",
      "font_weight": "<bold|black|heavy>",
      "font_names": ["<specific font names observed>"],
      "min_font_size": 8.5,
      "text_case": "<uppercase|mixed|varies>",
      "position": "<relative to zone/column top>"
    },
    "shared_attributes": {
      "detection": "<description>",
      "font_weight": "<regular|light>",
      "typical_content": "<what kind of info appears here>"
    },
    "variants": {
      "detection": "<description>",
      "variant_text_scope": "<how to determine what text belongs to each variant>"
    },
    "duplicate_family_names": {
      "can_repeat_across_zones": true,
      "handling": "<treat each zone occurrence as independent product group>"
    }
  },

  "catalog_number_patterns": [
    {
      "regex": "<pattern>",
      "description": "<human readable description>",
      "examples": ["<actual examples seen>"],
      "display_style": "<boxed|plain_bold|plain_text>",
      "has_suffixes": false,
      "suffix_pattern": "<optional suffix regex if applicable>"
    }
  ],

  "image_association": {
    "large_photos": {
      "min_dimension_pts": 100,
      "association_level": "<family|variant>",
      "typical_positions": ["<right|below|left|interspersed|above>"],
      "can_cross_column_boundaries": false,
      "families_without_photos": false,
      "multiple_photos_per_family": false
    },
    "small_detail_drawings": {
      "max_dimension_pts": 100,
      "association_level": "<variant|family>",
      "spatial_relationship_to_mpn": "<description of typical position relative to catalog number>",
      "multiple_per_variant": false,
      "rendering_type": "<embedded_bitmap|vector_paths|both>",
      "how_to_distinguish_from_decorations": "<description>"
    },
    "ambiguous_mid_size_images": {
      "size_range_pts": [0, 0],
      "handling": "<description of how to classify>"
    },
    "primary_association_method": "zone_and_column_membership",
    "secondary_association_method": "y_proximity_within_column",
    "hard_rules": [
      "An image in zone N must never be associated with a product in zone M",
      "An image in column A must never be associated with a product in column B"
    ],
    "image_association_instructions": "<2-4 short sentences for the extraction step: how to assign each image (Image 0, 1, 2...) to the correct product(s) on the page. E.g. 'Large photos to the right of a product block apply to that product family. Small drawings below a part number apply to that variant. One photo can apply to multiple part numbers in the same row.'>"
  },

  "special_elements": {
    "symbols": {},
    "badges": [],
    "legend": {
      "exists": false,
      "position": "<where on the page>",
      "detection": "<how to identify it>"
    }
  },

  "ignore_regions": {
    "header": {"description": "<what to ignore>", "detection": "<how to detect>"},
    "footer": {"description": "<what to ignore>", "y_min_from_bottom_pts": 0},
    "left_margin": {"description": "<what to ignore>", "x_max_pts": 0, "present_on_all_pages": false},
    "right_margin": {"description": "<what to ignore>", "x_min_from_right_pts": 0, "present_on_all_pages": false},
    "translations": {"description": "<what to ignore>", "detection": "<how to detect>"}
  },

  "edge_cases": {
    "full_width_products": "<description>",
    "single_product_pages": "<description>",
    "unusual_layouts": [],
    "hardest_pages": "<description>"
  },

  "confidence_scores": {
    "layout_structure": 5,
    "catalog_numbers": 5,
    "image_association": 5,
    "hierarchy": 5,
    "edge_cases": 5
  }
}

Be thorough. Every field must reflect what you actually observe in the sample pages. If you are uncertain about any aspect, say so in the confidence scores and add a note in edge_cases.unusual_layouts explaining what needs manual verification.

Return ONLY valid JSON: the single root object with keys catalog_id, manufacturer, page_types, layout_structure, product_hierarchy, catalog_number_patterns, image_association, special_elements, ignore_regions, edge_cases, confidence_scores. No markdown code fence, no wrapping key, no explanation outside the JSON."""


def _unwrap_profile(profile: dict) -> dict:
    """
    If the model returned a wrapped object (e.g. { "catalog_profile": { ... } }), return the inner object.
    Ensures we save the full profile, not a minimal wrapper.
    """
    if not profile or not isinstance(profile, dict):
        return profile
    # Single top-level key "catalog_profile" or "profile" containing the real profile
    for key in ("catalog_profile", "profile", "analysis_profile"):
        if key in profile and isinstance(profile[key], dict):
            inner = profile[key]
            # If inner has pipeline keys (zone_detection, image_association, etc.), use it
            if any(k in inner for k in ("zone_detection", "layout_structure", "product_grouping", "image_association", "column_detection", "page_types")):
                return inner
    return profile


def _normalize_color_rgb(rgb) -> list[float]:
    """Return [r, g, b] in 0-1 range. If any value > 1.0, assume 0-255 and divide by 255."""
    if not rgb or len(rgb) < 3:
        return [0.95, 0.47, 0.15]
    r, g, b = float(rgb[0]), float(rgb[1]), float(rgb[2])
    if max(r, g, b) > 1.0:
        r, g, b = r / 255.0, g / 255.0, b / 255.0
    return [r, g, b]


def _normalize_analysis_profile(profile: dict) -> dict:
    """
    Ensure the analysis profile has pipeline-expected keys. Derive image_rules and flat
    product_hierarchy from the new schema (image_association, product_hierarchy.family_name).
    Map layout_structure.primary_pattern to layout_algorithm; when primary_pattern is
    zones_and_columns, derive zone_detection/column_detection from patterns_observed.
    Map product_grouping / delimiter_detection into zone_detection when present.
    Normalize zone_detection.color_rgb to 0-1 (Gemini may return 0-255).
    """
    if not profile or not isinstance(profile, dict):
        return profile

    # layout_structure: set layout_algorithm and derive zone_detection/column_detection when zones_and_columns
    ls = profile.get("layout_structure")
    if isinstance(ls, dict):
        primary = (ls.get("primary_pattern") or "zones_and_columns").strip().lower()
        primary = "zones_and_columns" if primary not in ("grid", "table", "single_column", "free_form") else primary
        profile["layout_algorithm"] = primary
        patterns = ls.get("patterns_observed") or []
        if primary == "zones_and_columns" and patterns:
            # Derive zone_detection from first pattern's full-width separator
            po = patterns[0] if isinstance(patterns[0], dict) else {}
            seps = po.get("separator_elements") or []
            for sep in seps:
                if not isinstance(sep, dict):
                    continue
                if sep.get("spans_full_page_width") and sep.get("role") in ("zone_divider", "row_separator"):
                    if "zone_detection" not in profile:
                        rgb = sep.get("color_rgb")
                        profile["zone_detection"] = {
                            "method": "colored_horizontal_rules",
                            "color_rgb": _normalize_color_rgb(rgb) if rgb else [0.95, 0.47, 0.15],
                            "color_tolerance": 0.15,
                            "min_width_pts": float(sep.get("typical_width_pts") or 100),
                            "max_height_pts": float(sep.get("typical_height_pts") or 5),
                            "fallback_method": "use_full_page",
                        }
                    break
            # column_detection: enable by default for zones_and_columns
            if "column_detection" not in profile:
                profile["column_detection"] = {
                    "enabled": True,
                    "method": "text_clustering",
                    "min_column_gap_pts": 30,
                    "trigger": "multiple_family_names_in_zone",
                    "image_column_assignment": "x_center_within_column_bounds",
                }
        elif primary == "grid":
            # Grid layout: do not assume full-width zone dividers; pipeline will use get_product_cells_grid
            if "zone_detection" not in profile:
                profile["zone_detection"] = {"method": "whitespace", "min_gap_pts": 30, "fallback_method": "use_full_page"}
    else:
        profile.setdefault("layout_algorithm", "zones_and_columns")

    # Map product_grouping (alternate schema) -> zone_detection so pipeline works
    pg = profile.get("product_grouping")
    if isinstance(pg, dict) and "zone_detection" not in profile:
        dd = pg.get("delimiter_detection") or {}
        if isinstance(dd, dict):
            color_rgb = dd.get("color_rgb")
            profile["zone_detection"] = {
                "method": "colored_horizontal_rules" if (pg.get("delimiter") or "").find("rule") >= 0 or (pg.get("delimiter") or "").find("horizontal") >= 0 else "colored_bars",
                "color_rgb": _normalize_color_rgb(color_rgb) if color_rgb else [0.95, 0.47, 0.15],
                "color_tolerance": dd.get("color_tolerance", 0.15),
                "min_width_pts": dd.get("min_width_pts", 100),
                "max_height_pts": dd.get("max_height_pts", 5),
                "fallback_method": "use_full_page",
            }
    # zone_detection (profile-driven; fallback for when no dividers found)
    if "zone_detection" not in profile:
        profile["zone_detection"] = {"method": "whitespace", "min_gap_pts": 30, "fallback_method": "use_full_page"}
    zd = profile["zone_detection"]
    if isinstance(zd, dict):
        zd.setdefault("fallback_method", "use_full_page")
        # Normalize color_rgb: Gemini may return 0-255; pipeline expects 0-1
        if zd.get("color_rgb"):
            zd["color_rgb"] = _normalize_color_rgb(zd["color_rgb"])
    # page_types (for page-type filtering; non-product pages skipped)
    if "page_types" not in profile:
        profile["page_types"] = []
    # catalog_number_patterns: ensure list of {regex, description}; new schema may add examples, display_style, etc.
    if "catalog_number_patterns" not in profile:
        profile["catalog_number_patterns"] = [{"regex": r"[A-Z]{1,4}[\-]?\d{3,6}", "description": "General"}]
    # image_rules: build from image_association (new schema) if image_rules missing
    if "image_rules" not in profile:
        ia = profile.get("image_association") or {}
        large = ia.get("large_photos") or {}
        small = ia.get("small_detail_drawings") or {}
        profile["image_rules"] = {
            "large_photo_min_dimension_pts": large.get("min_dimension_pts") or 150,
            "large_photo_association": large.get("association_level") or "family",
            "large_photo_typical_position": (large.get("typical_positions") or ["right"])[0] if isinstance(large.get("typical_positions"), list) else "right",
            "small_drawing_association": "nearest_catalog_number_in_zone",
            "small_drawing_max_dimension_pts": small.get("max_dimension_pts") or 100,
        }
    # product_hierarchy: ensure flat fields for chat_server (family_name_min_font_size, etc.) from new nested schema
    ph = profile.get("product_hierarchy") or {}
    if isinstance(ph, dict):
        ph = dict(ph)
        family = ph.get("family_name")
        if isinstance(family, dict):
            ph.setdefault("family_name_min_font_size", family.get("min_font_size") or 8.5)
            ph.setdefault("family_name_detection", family.get("detection") or "")
            ph.setdefault("family_name_font_bold", (family.get("font_weight") or "").lower() in ("bold", "black", "heavy"))
        shared = ph.get("shared_attributes")
        if isinstance(shared, dict) and "typical_content" in shared:
            ph.setdefault("shared_attributes", shared.get("typical_content"))
        elif not ph.get("shared_attributes"):
            ph.setdefault("shared_attributes", "")
        v = ph.get("variants")
        if isinstance(v, dict) and (v.get("variant_text_scope") or v.get("detection")):
            ph.setdefault("variant_detection", v.get("variant_text_scope") or v.get("detection"))
        elif not ph.get("variant_detection"):
            ph.setdefault("variant_detection", "")
        ph.setdefault("family_name_min_font_size", 8.5)
        profile["product_hierarchy"] = ph
    # column_detection
    if "column_detection" not in profile:
        profile["column_detection"] = {
            "enabled": False,
            "method": "text_clustering",
            "min_column_gap_pts": 30,
            "trigger": "multiple_family_names_in_zone",
            "image_column_assignment": "x_center_within_column_bounds",
        }
    cd = profile["column_detection"]
    if not isinstance(cd, dict):
        profile["column_detection"] = {"enabled": False, "method": "text_clustering", "min_column_gap_pts": 30}
    else:
        cd.setdefault("min_column_gap_pts", 30)
        cd.setdefault("enabled", bool(cd.get("enabled")))
    # confidence_scores
    if "confidence_scores" not in profile:
        profile["confidence_scores"] = {}
    for key in ("zone_detection", "column_detection", "catalog_numbers", "image_association", "hierarchy", "edge_cases"):
        profile["confidence_scores"].setdefault(key, 5)
    return profile


def _parse_json_from_response(text: str):
    """Extract JSON from model response (strip markdown code blocks if present)."""
    text = (text or "").strip()
    # Remove ```json ... ``` or ``` ... ```
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try to find first { ... } block
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    return None


def run_catalog_analysis(conn, source_id: int, sample_pages: list[int], progress_callback=None):
    """
    Run catalog analysis: render sample pages, extract spatial data, call Gemini 2.5 Pro,
    parse profile JSON, save to catalog_profiles. Raises on failure.
    progress_callback(message: str) is called with status strings.
    """
    import fitz

    row = conn.execute("SELECT name, file_path FROM sources WHERE id = ?", (source_id,)).fetchone()
    if not row:
        raise ValueError("Source not found")
    source_name, file_path = row[0], row[1]
    if not file_path or not os.path.isfile(file_path):
        raise ValueError("Source PDF not found: " + str(file_path))

    def progress(msg):
        if progress_callback:
            progress_callback(msg)

    progress("Opening PDF...")
    doc = fitz.open(file_path)
    total_pages = len(doc)
    if not sample_pages:
        # Auto-select 8-12 pages for layout diversity (block count, image count, spread; exclude dividers/title; include first/last product page)
        sample_pages = select_diverse_sample_pages(doc, total_pages, min_pages=8, max_pages=12)

    # Validate page numbers (1-based in UI)
    page_indices = []
    for p in sample_pages:
        if 1 <= p <= total_pages:
            page_indices.append(p - 1)
    page_indices = sorted(set(page_indices))
    if not page_indices:
        doc.close()
        raise ValueError("No valid sample pages selected")
    sample_pages = [p + 1 for p in page_indices]  # 1-based for storage and display

    progress("Rendering sample pages and extracting spatial data...")
    image_parts = []
    spatial_parts = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for i, page_num in enumerate(page_indices):
            page = doc.load_page(page_num)
            mat = fitz.Matrix(2, 2)
            pix = page.get_pixmap(matrix=mat)
            png_path = os.path.join(tmpdir, f"sample_page_{page_num + 1}.png")
            pix.save(png_path)
            with open(png_path, "rb") as f:
                image_bytes = f.read()
            image_parts.append((page_num + 1, image_bytes))
            spatial_parts.append(_extract_page_spatial_data(page, page_num + 1))
    doc.close()

    progress("Calling Gemini for layout analysis...")
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set")

    from google import genai
    client = genai.Client(api_key=api_key)

    # Build content: text with spatial data + images
    spatial_text = "Supplementary spatial data per page:\n\n" + json.dumps(spatial_parts, indent=2)
    user_text = ANALYSIS_PROMPT + "\n\n" + spatial_text
    user_text += "\n\nSample pages are attached in order (Page " + ", ".join(str(p) for p in sorted([p[0] for p in image_parts])) + ")."

    from google.genai import types
    parts = [types.Part.from_text(text=user_text)]
    for _page_num, img_bytes in image_parts:
        parts.append(types.Part.from_bytes(data=img_bytes, mime_type="image/png"))

    try:
        config = types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=16384,
        )
        response = client.models.generate_content(
            model=GEMINI_ANALYSIS_MODEL,
            contents=parts,
            config=config,
        )
    except Exception as e:
        raise RuntimeError("Gemini analysis request failed: " + str(e)) from e

    def _response_text(r):
        if getattr(r, "text", None):
            return r.text
        if getattr(r, "candidates", None) and r.candidates:
            for part in getattr(r.candidates[0], "content", {}).get("parts", []):
                if getattr(part, "text", None):
                    return part.text
        return ""

    text = _response_text(response)
    raw_response_length = len(text)

    profile = _parse_json_from_response(text)
    if not profile or not isinstance(profile, dict):
        raise RuntimeError("Could not parse profile JSON from model response")

    # Unwrap if Gemini returned { "catalog_profile": { ... } } or similar single-key wrapper
    profile = _unwrap_profile(profile)

    # Validation: expect at least 8 of the 12 required top-level sections
    EXPECTED_PROFILE_KEYS = (
        "catalog_id",
        "manufacturer",
        "page_types",
        "layout_structure",
        "product_hierarchy",
        "catalog_number_patterns",
        "image_association",
        "special_elements",
        "ignore_regions",
        "edge_cases",
        "confidence_scores",
    )
    present = sum(1 for k in EXPECTED_PROFILE_KEYS if k in profile)
    if present < 8:
        print(
            f"[Analysis] WARNING: Profile has only {present}/11 expected sections. "
            f"Model may have returned incomplete output. Raw response length: {raw_response_length} chars."
        )
        print("[Analysis] Raw response (first 500 chars):", repr(text[:500]))

    # Normalize profile: ensure pipeline-ready shape (image_rules, flat product_hierarchy) and map alternate keys
    profile = _normalize_analysis_profile(profile)

    progress("Saving profile...")
    source_filename = os.path.basename(file_path)
    profile_json = json.dumps(profile)
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        """
        INSERT INTO catalog_profiles (source_id, catalog_id, source_filename, manufacturer, profile_json, analyzed_at, analyzed_by_model, sample_pages, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'analyzed')
        ON CONFLICT(source_id) DO UPDATE SET
            catalog_id = excluded.catalog_id,
            source_filename = excluded.source_filename,
            manufacturer = excluded.manufacturer,
            profile_json = excluded.profile_json,
            analyzed_at = excluded.analyzed_at,
            analyzed_by_model = excluded.analyzed_by_model,
            sample_pages = excluded.sample_pages,
            status = 'analyzed'
        """,
        (
            source_id,
            profile.get("catalog_id") or source_name,
            source_filename,
            profile.get("manufacturer"),
            profile_json,
            now,
            GEMINI_ANALYSIS_MODEL,
            json.dumps(sample_pages),
        ),
    )
    conn.commit()
    progress("Done.")
    return profile
