# Testing the New Extraction Architecture

This guide describes how to test the **LLM-only product extraction** and **image association by catalog-number proximity** pipeline.

## Architecture Under Test

1. **Product extraction**: Chunks (from DB) + field guide (samples + profile instructions) + page images → **Gemini 2.0 Flash** → products saved to DB. LLM is the sole source for product names, descriptions, categories.
2. **Image association**: After products exist, PyMuPDF text spans + profile `catalog_number_patterns` (regex) find catalog number positions; each image is linked to the product whose MPN is the **nearest** on the page.

## Prerequisites

- **Flask server** running (`python scripts/chat_server.py` or your usual start), with **Gemini API key** set (e.g. in `.env`).
- **At least one catalog (source)** in the DB with:
  - **Chunks** for the pages you want to test (from a prior `rebuild`).
  - **Images** with `bbox_json` populated (rebuild extracts these from the PDF).
  - **Optional but recommended**: A **catalog profile** (from “Analyze catalog layout” in the UI, or from `catalog_profiles/<name>.yaml`). The profile supplies `catalog_number_patterns` for image association and instructions for the field guide.

## 1. Quick smoke test (one page via API)

From the project root, with the server running:

```bash
# Replace SOURCE_ID and PAGE_NUMBER with real values (e.g. 1 and 5).
curl -X POST "http://localhost:5001/api/catalogs/1/build-product-listing/page/5" \
  -H "Content-Type: application/json" \
  -d "{\"replace\": true}"
```

**Check:**

- Response has `created` ≥ 0 and `errors` empty (or expected messages).
- In the server console you should see:
  - `[Build listing] ... — starting (LLM-only extraction)`
  - `[Build listing] ... — LLM extraction with N images (vision)...` or `(text only)...`
  - `[Build listing] ... — LLM done in X.Xs`
  - `[Build listing] page=N — image association by catalog-number proximity: M image(s)` (if PDF + profile exist and images have bbox).

## 2. Test script (one page + DB validation)

Run the provided script to build one page and then inspect products and image links:

```bash
# From project root. Requires server running and GEMINI_API_KEY set.
python scripts/test_extraction_architecture.py --source-id 1 --page 5
```

Options:

- `--source-id` — catalog (source) id in the DB.
- `--page` — page number (1-based).
- `--no-replace` — append instead of replacing that page’s products (default: replace).

The script:

1. Calls `POST /api/catalogs/<id>/build-product-listing/page/<page>`.
2. Queries `products` and `product_images` for that (source_id, page).
3. Prints a short report: product count, sample rows, and how many images are linked.

## 3. Manual test via UI

1. Open **Catalog Setup** (or the catalog management page).
2. Select a catalog that has chunks (and ideally a profile and images).
3. Use **“Build product listing”** for the whole catalog, or **“Build this page”** for a single page.
4. After the run:
   - Check that products appear for the page(s) with realistic **product names**, **descriptions**, and **part numbers** (all from the LLM).
   - Check **image–product links**: open a product that should have an image and confirm the correct image is shown (image association is by proximity to catalog number, not by LLM `image_indices`).

## 4. What to validate

| Check | How |
|-------|-----|
| **Products from LLM** | Product name, description, category, and MPN look correct for the page content (no zone/column logic involved). |
| **Chunks used** | Page text sent to the LLM is the concatenation of chunks for that page (from DB). |
| **Field guide used** | Profile (if any) is converted to instructions and included in the prompt; samples (part numbers, product names, image–part links) are in the field guide. |
| **Image association** | Each image on the page is linked to the product whose catalog number is **nearest** in the PDF (text span positions). No zone/column rules. |
| **Fallback** | If PDF or profile is missing, image association falls back to `_apply_proximity_image_links` (page_blocks + text containing part number). |

## 5. Troubleshooting

- **`created: 0`**  
  - Ensure the page has chunks and the page isn’t skipped by page-type (e.g. section divider).  
  - Check server logs for LLM errors or empty parse.  
  - Increase logging: `LOG_PRODUCT_EXTRACTION_RAW=1` to see raw Gemini output.

- **No image association message**  
  - Confirm images have `bbox_json` (rebuild with image extraction).  
  - Confirm the source has a **file_path** pointing to the PDF and the profile has **catalog_number_patterns** (from analysis or YAML).

- **Wrong image linked to product**  
  - Proximity is by center-to-center distance. If layout is unusual, consider adding **image_part_number** samples (Assign part number to image) so `_apply_image_part_number_samples_for_page` overrides/corrects links.

## 6. Running a single page without the UI

If you prefer to drive the pipeline from Python (e.g. in a debugger) without HTTP:

```python
import sqlite3
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))
from chat_server import (
    load_models_once,
    build_field_guide_for_source,
    build_product_listing_for_page,
    DB_PATH,
)
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
load_models_once()
field_guide = build_field_guide_for_source(conn, source_id)
conn.close()
result = build_product_listing_for_page(source_id, page_number, field_guide, replace_page=True)
print(result)
```

Use your real `source_id` and `page_number`. The server’s `load_models_once()` must have been run (Gemini client, etc.) before calling `build_product_listing_for_page`.
