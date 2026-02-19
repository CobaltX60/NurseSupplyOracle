# Next Steps: Capturing Smaller Secondary Images (incl. xRef / Inline)

The application needs to capture **all** images on catalog pages, including smaller secondary images (e.g. detail views, thumbnails, **xRef icons**) that may live inside **Form XObjects**, compressed streams, **inline content (BI/ID/EI)**, or as **vector line art** (no image xref at all). The approach below follows: (1) use PyMuPDF to get all extractable image refs and inline bitmaps, (2) assign orphan xrefs to pages via stream/Resources, (3) rasterize small vector regions so xRef-style icons (vector drawings) are captured.

---

## What’s Implemented (Current Rebuild)

1. **XObject / ref images** – `page.get_images(full=True)` when supported (fallback: `page.get_images()`). `full=True` can expose more refs (e.g. from Forms).
2. **Inline bitmap images (BI/ID/EI)** – `page.get_text("dict", flags=TEXT_PRESERVE_IMAGES)`; blocks with `type == 1` contain image data and bbox. These are often missed by `get_images()`.
3. **Orphan image xrefs** – Full-doc xref scan finds image objects not in any `get_images()`; assignment to page via stream search and Form `/Resources/XObject`.
4. **Vector / xRef icons (region rasterization)** – Small “images” that are actually **vector line art** (m, l, c, re, S, f, etc.) have no image xref. We use `page.cluster_drawings()` (or `page.get_drawings()` and path `rect`) to get bounding boxes, filter by size (e.g. 8–220 pt), then `page.get_pixmap(matrix=Matrix(2,2), clip=rect)` to rasterize each region and add as PNG. Config in `rebuild.py`: `INCLUDE_VECTOR_REGIONS`, `MIN_VECTOR_REGION_PT`, `MAX_VECTOR_REGION_PT`, `VECTOR_REGION_DPI_SCALE`.
**Config (rebuild.py):**

- `INCLUDE_VECTOR_REGIONS = True` – add rasterized small vector regions (xRef-style icons).
- `MIN_VECTOR_REGION_PT` / `MAX_VECTOR_REGION_PT` – size filter for vector regions (points).
- `VECTOR_REGION_DPI_SCALE` – scale factor when rasterizing (e.g. 2 for sharper icons).

**Logs:** Rebuild prints `[orphans]`, `[inline images]` (on error), `[vector] Page N: rasterized M small vector region(s)` when vector regions are added.

---

## Option A: Verify with Diagnostic Script

Run the diagnostic on the same PDF and page:

```bash
python scripts/diagnose_pdf_images.py "path/to/catalog.pdf" 24
```

Check the **“Document-wide image xrefs”** section: you should still see 5 orphan xrefs. Then we can add a small script that, for each orphan xref, loops over every page and reports **which page** (if any) references it (using the same `_page_references_xref` logic). That will show whether assignment is failing or the orphans are never referenced by page 24.

---

## Option B: Assign Orphans to “Nearest” Page (Fallback)

If stream/Resources parsing still doesn’t attach an orphan to any page, we can add a **fallback**: e.g. assign each orphan to the page that has the **fewest** images so far, or to every page that has at least one Form XObject. That can create duplicates or wrong page associations but guarantees no orphan is dropped. You can then clean up in the UI (move/delete). This is a last resort if Option A shows “orphan never referenced by any page.”

---

## Option C: Full-page render (vector content) — **removed**

Full-page render has been **removed** from the build. The rebuild no longer produces one full-page image per page. Only extracted images (XObject, inline, orphans) and small vector regions are included. To capture large vector content (e.g. full-page diagrams) you would need to re-add a full-page render block in `rebuild.py` or use clip-renders (Option D).

---

## Option D: Clip-Render Regions (Synthetic Images) — **implemented**

If some “images” are actually **vector or mixed content** (no image xref), we can’t extract them as images. Alternative:
- Use **drawing/vector bboxes** (e.g. `page.get_drawings()` or similar) or a fixed layout to define regions (e.g. “left column of small images”).
- For each region, render with `page.get_pixmap(clip=rect)` and save as PNG.
- Insert those as extra “images” for that page (with a flag or naming so you know they’re synthetic). This captures everything visible in the clip (raster + vector) but requires knowing or detecting the regions.

---

## Option E: PyMuPDF / MuPDF Version or API

- **Upgrade PyMuPDF**: Newer versions sometimes improve `get_images()` or add APIs that expose more image refs (e.g. from Forms).
- **Check release notes** and the [PyMuPDF images recipe](https://pymupdf.readthedocs.io/en/latest/recipes-images.html) for any “get all images including from XObjects” option.

---

## Recommended Order

1. **Run a full rebuild** with the current code (decompressed stream search + Form Resources).
2. **Check** page 24 file count and DB rows; if you now have 9 images, **re-run Build product listing** for that catalog so the new images can be linked to products.
3. If still only 4: run **Option A** (diagnostic + “which page references this orphan” script) and share the result.
4. If orphans are never referenced by any page: consider **Option B** (fallback assignment) so they at least appear somewhere, then **Option C** or **D** if you need a different extraction strategy.

---

## Where Images Are Stored

- **Files**: `data/images/<source_id>/page_<page_number>_<image_index>.<ext>`
- **DB**: `images` (one row per image); **product_images** (links products to images; filled by Build product listing).
- **Doc**: See `documents/IMAGE_STORAGE.md` for full details.
