# Catalog Data Model and Association Plan

This document proposes a plan to improve how Instrument Oracle parses catalog PDFs, builds a **structured data model**, and lets users **associate and correct** data (part numbers, descriptions, images) so the AI returns accurate product information instead of conflating phone numbers, page numbers, or wrong images with products.

---

## 1. Problem Summary

- **Part numbers are mis-identified:** The system or LLM picks up phone numbers, page numbers, or other numeric text as part numbers.
- **Wrong product–image association:** The AI links an image to the wrong product or description.
- **No catalog-specific rules:** Every catalog has different layout and conventions; one-size-fits-all parsing fails.
- **Foreign language:** PDFs may contain non-English text; we need to gather and associate it without assuming English-only patterns.
- **Need for user verification:** Automatic extraction will make mistakes; we need a way for users to confirm and correct associations and to teach the system per catalog.

---

## 2. Target Data Model

A **Product** (one row per logical product) with the following core fields. One product can have **multiple images**.

| Field | Description | Notes |
|-------|-------------|--------|
| **Manufacturer** | Brand/source (e.g. from catalog name or explicit field) | Often one per catalog |
| **Manufacturer Part Number** | Official part number | Must be distinguished from phone numbers, page numbers, other IDs |
| **Product Name** | Primary title/name | |
| **Product Description** | Main description text | May be long; keep full text |
| **Product Secondary Description** | Additional specs, features, or notes | Optional |
| **Image(s)** | One or more images for this product | Many-to-one: multiple images → one product |

**Additional useful fields:** Source catalog ID, page number(s), language tag, raw snippet (for audit), verification status (unverified / user-confirmed / user-corrected).

**Relations:**

- **products** — one row per product (manufacturer, mfr_part_number, product_name, description, secondary_description, source_id, page_number, language, verified, etc.).
- **product_images** — links a product to an image (product_id, image_id, display_order). One product → many images.

This gives a clean place to store user-corrected data and to drive chat/answers from **products** + **product_images** instead of raw chunks alone.

**Product groups / variants:** Many catalog pages show one product name and description once, then list multiple part numbers with only a variant-specific attribute (e.g. “Overall length 7in” vs “8in”). The system treats these as **variants of the same product**: the extraction prompt instructs the LLM to output one row per part number, each with the **same** product_name and description, and the variant-specific text in secondary_description. Chat then treats products that share the same product_name and description (and source) as a group and can mention “Other variants: NL1481 (8in)” when answering about NL1480.

---

## 3. Per-Catalog Instructions (Catalog Configuration)

Each catalog (PDF/source) should have a **configuration** that tells the system how to interpret that document. Store this in a table or JSON per source.

**Catalog configuration fields (conceptual):**

- **Catalog/source identifier** (e.g. source_id or catalog name).
- **Part number rules**
  - Patterns: e.g. regex or “starts with letter + digits”, “no spaces”, “exclude patterns that look like phone numbers (e.g. ###-###-####)”, “exclude pure numbers that match page numbers (e.g. 1–3 digits)”.
  - Hints: “Part numbers appear under the heading ‘Item No.’” or “In the first column of the table.”
- **Product name / description rules**
  - Where they appear: “Product name is the first line in bold”, “Description is the paragraph below the image.”
- **Language**
  - Primary language (e.g. en, de, fr) and optionally “also include blocks in these languages.”
- **What to exclude**
  - e.g. “Ignore footer text”, “Do not treat page numbers as part numbers”, “Skip blocks that are only digits and punctuation.”

**Storage:** e.g. `catalog_config` table (source_id, config_json) or a `catalog_configs` folder with one JSON file per catalog. The **parsing and association** steps read this config when processing that catalog.

**Workflow:** Start with a default or empty config; as the user corrects associations (e.g. “this is the part number”, “this is not a part number”), the system can **update or suggest** config (e.g. “Part numbers in this catalog match pattern X”) so the next run or next page does better.

---

## 4. Gathering Information: Parsing Pipeline (Phased)

**Phase A – Extract (current + structure)**

1. **Keep current extract:** Text by page (PyMuPDF), images by page (already in place).
2. **Add structure detection per page:**
   - Run **layout/block detection** (e.g. headings, paragraphs, tables, captions) if available from the PDF or from simple heuristics (line breaks, font size from PyMuPDF).
   - Optionally use **language detection** on each block (e.g. langdetect or similar) and tag blocks with a language code.
   - Output: **page-level structure** — e.g. “block 1: heading, block 2: text (en), block 3: text (de), block 4: image, block 5: caption”.

**Phase B – Candidate extraction using catalog config**

3. **Apply per-catalog rules** to each page:
   - **Part number candidates:** From config (regex, position, “under heading X”), extract candidate strings. **Exclude** by config (e.g. phone pattern, pure integer 1–999 for page numbers).
   - **Product name / description candidates:** From config (e.g. “first bold block”, “paragraph after image”), extract text.
   - **Image candidates:** Already have images per page; optionally group “image + following caption” or “image + preceding heading” as one unit.
4. **Store candidates, not final products:** Write to **staging** tables, e.g.:
   - `extract_candidates` (source_id, page_number, block_index, candidate_type: 'part_number'|'product_name'|'description'|'secondary_description', value_text, image_id_if_any, language, confidence_or_rule_used).
   - Do **not** yet create `products` rows; we need user association to reduce false positives (e.g. phone numbers).

**Phase C – User association and correction**

5. **Association UI/workflow:**
   - For a given **catalog** (and optionally a **page**):
     - Show **images** for that page (or catalog).
     - Show **candidate** part numbers, names, descriptions for that page (or nearby).
   - User actions:
     - **Assign:** “This image + this part number + this name + this description = one Product.” (Creates or updates a product and product_images.)
     - **Reject:** “This candidate is not a part number” (or not a product name). Optionally “use this to improve rules” (e.g. add to exclude list or adjust regex).
     - **Correct:** “The part number for this product is actually X” (override candidate).
   - **Progressive:** As the user completes one page or one product, the system can suggest similar associations on the next page (e.g. “same layout: part number in same position”) and learn from corrections to update catalog config.

**Phase D – Completion per catalog**

6. **Catalog completion:** Track progress per catalog (e.g. “pages 1–20 reviewed”, “products created: 45”). User can mark catalog as “review complete” or “draft” so that:
   - **Chat/search** uses only **verified product** data (and optionally still falls back to raw chunks for unreviewed pages).
   - Re-running **rebuild** for that catalog can re-extract candidates but preserve user-created products and associations (merge strategy).

---

## 5. Associating Information Based on Observation

- **Observation 1 – Layout:** “On this page, part numbers appear in the left column, product name in the middle, image on the right.” → Config: part_number_region, product_name_region, image_region (or block indices).
- **Observation 2 – Patterns:** “Every part number we confirmed matches `[A-Z]{2,4}-[0-9]+`.” → Config: part_number_regex; exclude “looks like phone” and “single/double digit (page number)”.
- **Observation 3 – User corrections:** “User said this candidate is NOT a part number (it was a phone number).” → Config: add to exclude list or negative pattern.
- **Observation 4 – Image–text link:** “User linked image 2 to part number X and description Y.” → Create product row and product_images; optionally “same page layout” → suggest same for next product on same page.

**Progressive extension:** After each batch of user actions:
- **Persist** products and product_images.
- **Optionally** update catalog config (manual or semi-auto: “Apply this pattern to the rest of the catalog?”).
- **Re-run** candidate extraction for remaining pages with updated config, then repeat association until the catalog is done.

---

## 6. Foreign Language

- **Detection:** Tag text blocks (or pages) with language (e.g. `langdetect` or similar). Store `language` on products and on extract_candidates.
- **Storage:** Keep **original text** in the data model (product_name, description, etc.) so we never drop non-English content.
- **Search/retrieval:** Embeddings work across languages; keep indexing product name and description in original language. Optionally add a “translation” column later for display if desired.
- **Instructions:** In catalog config, allow “primary_language” and “other_languages”; part number and structure rules can be language-agnostic (e.g. regex, position) while description/name stay in original language.
- **UI:** Show original text in the association UI; if you add translations, show both.

---

## 7. Implementation Phases (Summary)

| Phase | What | Outcome |
|-------|------|--------|
| **1. Schema** | Add `products`, `product_images`; add `catalog_config` (or JSON per source); add staging table `extract_candidates` (or equivalent). | DB ready for structured products and config. |
| **2. Catalog config** | UI or file format to define per-catalog: part number rules (include/exclude), name/description rules, language. | Each catalog can have its own parsing instructions. |
| **3. Candidate extraction** | After text/image extract, run structure detection + config-driven extraction; write candidates to staging. | List of candidate part numbers, names, descriptions, linked to pages/images. |
| **4. Association UI** | Screen(s) to show candidates and images per catalog/page; user assigns or rejects; create/update products and product_images. | User can bind images + part numbers + descriptions into products. |
| **5. Chat uses products** | Chat/search uses `products` (+ product_images) for answers when available; cite product and part number; fall back to chunks for unreviewed content. | Answers use verified product data; fewer wrong part numbers or image associations. |
| **6. Progressive refinement** | Use corrections to update config; re-extract candidates for remaining pages; repeat until catalog is complete. | Each catalog can be “finished” with aligned data. |

---

## 8. Completing the Task for Each Catalog

- **Per-catalog workflow:**
  1. Add catalog PDF to `scripts/source_files/` (or register source).
  2. Create or load **catalog config** for that source (part number rules, name/description rules, language).
  3. **Run extract + candidate extraction** for that catalog only (or full rebuild with config).
  4. **Association:** User works through pages/products: assign image + part number + name + description → product; reject bad candidates; correct values.
  5. **Refine config** from corrections (e.g. add exclude pattern for phone numbers), then re-run candidate extraction for remaining pages if needed.
  6. **Mark catalog** as “review complete” when satisfied; chat then relies on verified products for that catalog.
- **Multi-catalog:** Repeat for each catalog; products table can hold products from many catalogs (distinguished by source_id / manufacturer).

---

## 9. Next Steps

1. **Implement schema** (products, product_images, catalog_config, extract_candidates) and document in this repo.
2. **Design catalog config format** (JSON schema or DB columns) and a minimal UI or script to edit it per source.
3. **Implement candidate extraction** (structure detection + config-driven part number/name/description extraction; write to staging).
4. **Build association UI** (by catalog and page: show images + candidates; assign → product; reject/correct).
5. **Wire chat** to use products (and product_images) for answers and citations.
6. **Add language detection** and language field to products/candidates; keep original text throughout.

This plan keeps your rough data model (Manufacturer, Mfr Part Number, Product Name, Descriptions, Image(s)), adds per-catalog instructions, and uses observation and user association to align data and complete each catalog progressively.

**Related:** For a review of how images are assigned to products, current limitations, and options (including using `image_part_number` samples and optional vision), see [IMAGE_PRODUCT_ASSIGNMENT_REVIEW.md](IMAGE_PRODUCT_ASSIGNMENT_REVIEW.md).
