# Image–Product Assignment: Logic Review and Improvement Options

This document reviews how images are associated with products, where alignment goes wrong, and options to improve it—including whether the LLM (or vision) should interpret images and assignments.

---

## 1. Current Logic Summary

### Data model

- **products:** one row per product (source_id, page_number, manufacturer_part_number, product_name, description, …).
- **images:** one row per extracted image (source_id, page_number, image_index, file_path). Order on the page is defined by `image_index` (and in rebuild, images are sorted by bbox top-left before assigning index).
- **product_images:** many-to-many link (product_id, image_id, display_order). UNIQUE(product_id, image_id), so:
  - One product can have **multiple images**.
  - One image can be linked to **multiple products** (same image_id, different product_id).

### Where assignments are created

| Mechanism | Where | Behavior |
|-----------|--------|----------|
| **Build product listing** | `build_product_listing_for_page()` in `chat_server.py` | After inserting products for a page (from LLM text extraction), the code links **images to products by index only**: first image (image_index 0) → first product (by insert order), second image → second product, etc. No part-number or layout info is used. |
| **Assign part number to image** | Catalog setup UI → `POST /api/catalogs/<id>/assign-image` | User picks an image (page + image_index) and a part number. Backend creates/updates the product and adds one `product_images` row; also adds an `image_part_number` catalog sample. Does not remove existing links for that image (so one image can end up linked to several products). |
| **Assign image to product** | `POST /api/products/<id>/images` | User links an image to a product (e.g. by image_id or source_id/page_number/image_index). Adds one `product_images` row. Same image can be linked to multiple products by repeated calls. |

### Where assignments are used

- **Chat:** `get_product_image_refs_for_question()` and `get_product_cards_for_question()` resolve part numbers mentioned in the question to products, then to linked images via `product_images`. Those image refs are passed to the front end and included in context so the LLM can say “the image for NL1234 is below.”
- **Catalog setup:** Product list and image grid show links; user can correct by assigning part number to image or assigning image to product.

---

## 2. Why Alignment Goes Wrong

1. **Position-only linking in build**  
   Build uses a fixed rule: “image i → product i.” Page layout often does not match that (e.g. one image at top with three part numbers below, or images in a different order than the extracted product list). So the first image may not belong to the first product.

2. **No layout or geometry**  
   We do not store image (or chunk) bounding boxes in the DB. Rebuild uses bbox only to sort images into `image_index`; it is not persisted. So we cannot do “this image is closest to this product’s text” without schema and pipeline changes.

3. **Extraction has no image awareness**  
   Product extraction is text-only: the LLM sees page text and returns a list of products. It does not see image indices or “image 0 / image 1” and does not output which image(s) go with which product. So we have no semantic signal from the LLM for assignment.

4. **One image, many products**  
   Catalogs often use one photo for several variants (e.g. one image, part numbers NL1480, NL1481, NL1482). The current build links one image to one product (first image to first product, etc.), so the other products get no link to that image unless the user assigns it manually.

5. **Samples not used for linking**  
   `image_part_number` samples (from “Assign part number to image”) are used in the **field guide** for the LLM (extraction and chat) but are **not** used when creating `product_images` in `build_product_listing_for_page`. So re-running build wipes and recreates links by position only; it does not re-apply known correct associations from samples.

---

## 3. Options to Improve Association

### Option A: Use existing `image_part_number` samples when building (quick win)

- **Idea:** When building the product listing for a page, after inserting products and doing positional linking, **re-apply** any `image_part_number` samples for that (source_id, page_number).
- **Logic:** For each sample with `sample_type='image_part_number'`, same source_id and page_number, read `value_text` = part number and `notes` = `image_index:I`. Find the product on that page with that part number and the image with that (source_id, page_number, image_index); ensure `product_images` has that (product_id, image_id). Do not remove other links (so positional links plus sample-based links can coexist).
- **Benefit:** Manual “Assign part number to image” choices are persisted as samples and re-applied on rebuild; alignment improves for any page where the user has corrected at least some associations.
- **Limitation:** Only helps for pages that already have samples; does not fix initial assignment.

### Option B: Smarter positional heuristics (no new data)

- **Ideas:**
  - If there is **one image** and **N products** on the page, link that image to **all N products** (one image, many products).
  - If **N images** and **M products** with N < M, link each image to the next product in order, then link the last image also to the remaining products (or use a simple rule like “image 0 → products 0..k” if we want one image for a block of products).
- **Benefit:** Better handling of “one photo, many variants” without new APIs or vision.
- **Limitation:** Still position-based; wrong when layout order differs from extraction order.

### Option C: LLM outputs image indices per product (text-only extension)

- **Idea:** Give the extraction prompt a short line such as: “This page has K images (image 0 = first, image 1 = second, …). For each product, output an optional `image_indices` array (e.g. [0] or [0,1]) indicating which image(s) show that product.”
- **Implementation:** Extend `parse_products_from_response()` to read `image_indices`; when writing `product_images`, use these indices instead of (or in addition to) positional mapping.
- **Benefit:** Lets the LLM use text/layout cues from the page text (e.g. “Image on the right … NL1480, NL1481 below”) to guess association, without sending pixels.
- **Limitation:** The LLM does not see the actual images; it infers from text only, so it can still be wrong when the text does not clearly state which image goes with which product.

### Option D: Layout-based association (schema + pipeline) — **Implemented**

- **Idea:** Persist image bbox (and optionally chunk/block bbox) so we can associate “image A is closest to the text block that contains product B’s part number.”
- **Implementation (current):** Rebuild stores `images.bbox_json` and populates `page_blocks`. When building the product listing, if both exist for the page, proximity linking runs (each image to product(s) in the nearest text block that contains their part number); otherwise positional linking is used. Catalog config layout hints feed the field guide but are not yet used by proximity.
- **Benefit:** Uses real page layout; one image can link to many products when their part numbers appear in the same nearby block.
- **Limitation:** Block-product matching relies on part number appearing in block text (word-boundary).

### Option E: Vision pass to assign images to products

- **Idea:** After text extraction, run a **vision-capable** model (e.g. Gemini with image input) on the page image(s) and optionally the product list: “Here are the product part numbers for this page: … Here are the extracted images (0, 1, 2). Which image index (or indices) corresponds to which part number? Output e.g. { part_number: [image_indices] }.”
- **Benefit:** Can use visual layout (position, labels in the image, diagrams) that text extraction does not see; can handle complex layouts and one-image-many-products.
- **Limitation:** Cost and latency; need to decide when to run (e.g. per page at build time, or on demand). Fallback (e.g. positional or sample-based) still needed when vision fails or is skipped.

### Option F: No automatic linking; require manual assignment

- **Idea:** In build, create products only; do not insert any `product_images` rows. Rely on “Assign part number to image” and “Assign image to product” for all links.
- **Benefit:** No wrong automatic links; user has full control.
- **Limitation:** More manual work; may be acceptable for small or high-value catalogs.

---

## 4. Do We Need the LLM (or Vision) to Interpret Images and Assignments?

### Current role of the LLM

- **Product extraction:** Text-only; input = page text, output = list of products (no image indices).
- **Chat:** Text-only; input = question + text context + a **text line** that says “The following image(s) are linked to product(s) X, Y.” The LLM does not see image pixels; it only uses that sentence to know which refs to mention.

### When vision would help

- **Association at build time:** If we send the page (or extracted image tiles) plus the list of part numbers to a vision model and ask “which image shows which part number?” we get a direct association signal that we do not have today. That could drive `product_images` (Option E).
- **Chat answers:** If we send the actual image to the model, it could describe what it sees (e.g. “the forceps in the image have …”) or confirm that the linked image matches the product. Today we only tell it “image X is linked to product Y” in text.

### When text-only LLM might be enough

- **Option C (LLM outputs image indices):** The LLM can infer from page text (“Image: … Item No. NL1480 …”) which image index goes with which product, without vision. Useful when the text explicitly or implicitly describes layout.
- **Option A (samples):** No LLM involved in assignment; we just apply user-provided (image_index, part_number) pairs.

### Recommendation

- **Short term:** Implement **Option A** so that `image_part_number` samples are applied when building the product listing for a page. This fixes wrong links after the user has corrected some assignments and keeps those corrections across rebuilds.
- **Medium term:** Consider **Option B** (one image → many products heuristic) and **Option C** (LLM outputs image_indices) to improve initial assignment without vision.
- **Vision (Option E):** Evaluate when layout is consistently wrong and user correction is costly; a single vision pass per page at build time could output (part_number → image_indices) and then we write `product_images` from that. Prefer a fallback to positional + samples when vision is unavailable or low-confidence.

---

## 5. Concrete Next Steps

1. **Code (done):** Samples are applied first; when `bbox_json` and `page_blocks` exist, proximity linking runs instead of positional.
2. **Docs:** Keep this document as the single place for assignment logic and options; reference it from `CATALOG_DATA_MODEL_AND_ASSOCIATION_PLAN.md` and `PAGE_IMAGES_AND_VISION.md`.
3. **Optional:** Add a short “Image–product alignment” section in the catalog setup UI or in-app help that points to “Assign part number to image” and “Assign image to product,” and mentions that re-running build will re-apply sample-based links (once Option A is in place).
4. **Do sample layouts provide instructions?** Yes: catalog_config and samples become the field guide for the LLM (extraction and chat). Layout hints in config help the model interpret the catalog. They do not yet change proximity linking; that uses only geometry. Future: use config (e.g. image_above_text) to prefer the block below an image when distances tie.
