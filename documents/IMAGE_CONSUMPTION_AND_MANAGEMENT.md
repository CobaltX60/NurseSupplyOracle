# Image Consumption and Management

This document describes how **images extracted from PDF catalogs** can be consumed and managed in Instrument Oracle so the app can store, reference, and optionally display them (e.g. product photos, diagrams).

---

## Current implementation (rebuild.py)

**Rebuild** (`python scripts/rebuild.py`) already performs full image extraction and storage:

- **XObject / ref images:** `page.get_images(full=True)` (fallback: `get_images()`).
- **Inline bitmap images (BI/ID/EI):** `page.get_text("dict", flags=TEXT_PRESERVE_IMAGES)`; blocks with `type == 1` contain image data.
- **Orphan image xrefs:** Full-doc xref scan; assignment to page via stream search and Form `/Resources/XObject`.
- **Vector / xRef icons:** Small vector regions from `cluster_drawings()` or `get_drawings()`; rasterized with `page.get_pixmap(clip=rect)` and stored as PNGs.
Images are written to `data/images/<source_id>/page_<n>_<i>.<ext>` and metadata to the **images** table. Chat returns `image_refs` and `product_cards` (with image URLs); the UI shows product info cards or an image list. See [NEXT_STEPS_SECONDARY_IMAGES.md](NEXT_STEPS_SECONDARY_IMAGES.md) for config and options.

---

## 1. Where images come from

- **Source:** Embedded images inside the PDFs in `scripts/source_files/`, plus inline bitmaps, orphan xrefs, and rasterized vector regions (see above).
- **When:** During **rebuild**, in the same pass that extracts text. **PyMuPDF** (`fitz`) is used for all extraction and clip-renders.

---

## 2. Extracting images (rebuild step)

**Tool:** PyMuPDF already in use. For each page:

- `page.get_images()` returns a list of image references (xrefs).
- For each ref, open the image with `doc.extract_image(xref)`, get `bytes` and `ext` (e.g. `png`, `jpeg`).
- Write to a stable path so the same page/image always maps to the same file.

**Suggested path layout:**

```
data/
  images/
    {source_id}/           # one folder per ingested document
      page_{page_num}_{img_index}.{ext}
```

Example: `data/images/1/page_5_0.png`, `data/images/1/page_5_1.jpeg`. Use `source_id` from the `sources` table so rebuild can clear and repopulate per source.

**Rebuild behavior:**

- When rebuilding, either:
  - **Clear and repopulate** `data/images/` (or per–source subfolders) so legacy images from removed PDFs are gone, or  
  - Delete only images for the sources being re-ingested, then write new extractions.

---

## 3. Storing image metadata (SQLite)

So the app can “manage” and reference images, store minimal metadata in SQLite.

**Option A – Table `images`:**

```sql
CREATE TABLE images (
  id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL REFERENCES sources(id),
  page_number INTEGER NOT NULL,
  image_index INTEGER NOT NULL,   -- 0-based on page
  file_path TEXT NOT NULL,        -- relative to data/ or absolute
  width INTEGER,
  height INTEGER,
  created_at TEXT DEFAULT (datetime('now')),
  UNIQUE(source_id, page_number, image_index)
);
```

- **source_id** ties the image to an ingested PDF.
- **page_number** matches the PDF page (and can match chunks that reference the same page).
- **file_path** is how the app finds the file (e.g. `images/1/page_5_0.png`).

**Option B – On chunks:**

- Add a column to `chunks`, e.g. `image_ids TEXT` (JSON array of `images.id`), or `image_path TEXT` for a single “best” image per chunk.
- Use when you explicitly associate one image (or a few) to a text chunk (e.g. “this chunk describes this product image”).

Start with **Option A** so every extracted image is registered; you can add chunk–image links (Option B) later when you have rules (e.g. “chunk on page X gets images from page X”).

---

## 4. How the application “manages” images

- **Storage:** Files under `data/images/`; metadata in SQLite (`images` table).
- **Rebuild:** Rebuild script extracts images, writes files, and inserts/updates rows in `images`. Same rebuild that refreshes chunks and FAISS; no separate “image rebuild” unless you want a flag to skip image extraction for speed.
- **Lifecycle:** When a source is re-ingested or removed, delete its rows from `images` and its files under `data/images/{source_id}/` so the app doesn’t reference stale or removed images.

---

## 5. How the application exposes images to the user

**A. Serve image files (backend)**

- Add a route that returns image bytes, e.g. `GET /api/image/<source_id>/<page>/<index>` or `GET /api/image?path=images/1/page_5_0.png`.
- Resolve `path` or `(source_id, page, index)` to `data/images/...`, read file, return with correct `Content-Type` (e.g. `image/png`). Optional: check that `(source_id, page, index)` exists in `images` table for consistency.

**B. Reference in API responses**

- When returning chunk or product data, include an **image reference** the frontend can use to build a URL, e.g.:
  - `image_ref: "/api/image/1/5/0"` or  
  - `image_path: "images/1/page_5_0.png"` (frontend calls an endpoint that serves by path).
- Chat or search response can include `sources` that have an optional `image_ref` so the UI can show “View image” or a thumbnail next to a source.

**C. Frontend**

- For each source or chunk that has an `image_ref` (or `image_path`), render a link or `<img src="…/api/image/...">` so users can open or inline the catalog image.

---

## 6. Optional: linking chunks to images

- **Simple rule:** “Chunks from page N can show images from page N.” When building the response, look up `images` where `source_id` and `page_number` match the chunk; attach the first (or all) image refs to the chunk in the JSON.
- **Richer rule:** If you later parse structure (e.g. “product block” with one image), store `chunk_id` or `chunk_id + image_id` in a join table and use that to attach exactly one image per product chunk.

---

## 7. Summary

| Step | What |
|------|------|
| **Extract** | In rebuild, use PyMuPDF to get image bytes per page; write to `data/images/{source_id}/page_{n}_{i}.{ext}`. |
| **Store** | Insert rows into `images` (source_id, page_number, image_index, file_path, optional dimensions). |
| **Manage** | Clear/recreate image files and rows when (re)building or removing a source; keep paths and DB in sync. |
| **Serve** | Backend route (e.g. `GET /api/image/...`) streams file from `data/images/...`. |
| **Reference** | Include `image_ref` or `image_path` in chunk/product/source payloads so the UI can display or link to the image. |

Implementing this would mean: (1) extending `scripts/rebuild.py` to extract and save images and insert into `images`; (2) adding the `images` table and any chunk–image link you want; (3) adding an image-serving route in the Flask app; (4) optionally adding `image_ref` to the chat/response shape and the frontend. If you want to proceed, the next step is adding image extraction to the rebuild and the `images` table.
