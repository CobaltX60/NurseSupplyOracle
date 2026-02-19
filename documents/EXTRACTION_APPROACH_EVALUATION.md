# Extraction Approach Evaluation

## Current Pipeline (Simplified)

1. **PyMuPDF** (rebuild): Extracts PDF structure → **chunks** (text per page/block), **images** (with bbox), **page_blocks**, drawings. Chunks are stored and used for search and for product extraction when we use the LLM path.

2. **Catalog analysis (Gemini 2.5 Pro)**: Looks at sample pages + supplementary data and produces a **profile** (layout_structure / zone_detection, column_detection, product_hierarchy, catalog_number_patterns, image_association, etc.). This profile is used in two ways today:
   - **A) As instructions**: `format_analysis_profile_for_llm(profile)` turns the profile into short text that is appended to the **field guide** (samples + config). So when Gemini 2.0 Flash runs for extraction, it sees “Catalog profile: zone delimiter …; part number patterns …; large photos associate to family; …”
   - **B) As layout code**: The same profile drives the **spatial path**—zone detection, column detection, grid cells—and **zone-based image association**, which can **override** Gemini’s image links.

3. **Build product listing (per page)**:
   - **Spatial path** (when profile has zone_detection and zones exist):  
     - Uses **PyMuPDF spans** (get_text with bbox), **not chunks**.  
     - Zones/columns/grid come from profile + PDF drawings.  
     - Products are extracted from spans (regex, hierarchy rules).  
     - Images are assigned by zone/column (or grid cell) **and** we can later **override** vision-based image links with `_apply_zone_based_image_links`.
   - **LLM path** (fallback when no zone_detection or no zones):  
     - Uses **chunks** (page_text) + **field_guide** (samples + **profile as instructions**) + optional **images**.  
     - **Gemini 2.0 Flash** extracts products and **image_indices**.  
     - No zone-based override; we keep Gemini’s product list and image association.

## The Tension

- **Spatial path**: More “deterministic” layout (zones, columns, grid) but (1) does **not** use chunks, (2) replaces or competes with Gemini for both **extraction** and **image association**, and (3) has required a lot of layout-specific code (zone/column/grid, edge cases). Experience: **data quality has gotten worse** and the **image issue has not been solved** by adding more layout logic.
- **LLM path**: Uses **chunks** and **Gemini 2.0 Flash** for both extraction and image association, with the profile used only as **instructions** in the field guide. Experience: **original data from Gemini 2.0 Flash was very good**.

So: the more we push the “final step” to interpret layout with custom code (and override Gemini), the worse quality gets without fixing images. The approach that worked best was **chunks + Gemini instructions + Gemini doing extraction and image grouping**.

## Agreed Principles (from your review)

1. **PyMuPDF** remains the source of PDF characteristics (text, structure, images, drawings) and of **chunked data**. We do **not** want to lose the role of chunks in extraction.
2. **Gemini 2.5 Pro** is for **understanding** the catalog (layout, patterns, hierarchy) and producing a **profile** that helps the system interpret the catalog—primarily as **instructions** for the extraction step, not as the driver of heavy layout programming.
3. **Final product creation** should rely on **chunks** and on **image association from Gemini** (2.0 Flash), not on “a lot of specific customized layout programming.”
4. **Quality bar**: Prefer the path that gave “very good” results—chunks + Gemini 2.0 Flash—and avoid layout logic that has hurt quality without solving the image problem.

## Recommended Direction

- **Keep**
  - PyMuPDF for extraction of PDF structure and for building **chunks**, images, page_blocks.
  - Catalog analysis (Gemini 2.5 Pro) to produce a **profile** that describes layout, part number patterns, hierarchy, and image-association rules in natural language / structured form.
  - **Chunks** as the main text input to the **final** product-extraction step.
  - **Gemini 2.0 Flash** for that final step: extract products from page text (chunks) and assign **image_indices** from the provided images, using the **field guide** (samples + **profile converted to instructions**).
- **Reduce / change**
  - **Do not** let the profile primarily drive a separate “spatial” extraction path that bypasses chunks and Gemini.
  - **Do not** override Gemini’s image association with zone-based (or grid-based) layout code when we have vision + chunks. Prefer **one** authoritative path: chunks + Gemini for both extraction and image grouping.
- **Use the profile as**
  - **Input to the field guide**: `format_analysis_profile_for_llm(profile)` (and any richer formatting we add) so Gemini 2.0 Flash sees “how this catalog works” in words (e.g. “grid with short orange lines per product,” “part numbers look like …,” “associate large photos to family”).
  - **Optional light hints** (e.g. “this catalog is grid-like”) without implementing full zone/column/grid pipelines for the final step.

## Concrete Option: “Prefer LLM extraction” mode

To align behavior with the above without rewriting everything at once:

- Add a **prefer_llm_extraction** (or “chunks + Gemini first”) mode:
  - When **on**: Build listing **always** uses the **LLM path** for product extraction (chunks + field_guide + images, Gemini 2.0 Flash). We **do not** run the spatial path for that page, and we **do not** override Gemini’s image_indices with zone-based (or grid-based) image links.
  - When **off**: Keep current behavior (spatial path when profile has zone_detection and zones; zone-based image override when has_zone_rules).
- The **field guide** already includes analysis profile instructions; we can extend `format_analysis_profile_for_llm` to include **layout_structure** in natural language (e.g. “Layout: grid with short orange line markers per product; associate images by position and part number.”) so Gemini still benefits from 2.5 Pro’s understanding without layout code.

This keeps:
- PyMuPDF and chunks central.
- Gemini 2.5 Pro’s role as “understand layout and inform instructions.”
- Gemini 2.0 Flash as the single place that does final product creation and image association from chunks + instructions.

and reduces:
- Reliance on spatial/zone/column/grid code and on overrides to Gemini’s image links.

---

## Rebuild completed: LLM-only extraction + proximity image association

The pipeline was rebuilt as follows:

**Product data extraction (single path):**
- PyMuPDF-derived **chunks** (per page) are loaded from the DB.
- Catalog profile (from Gemini 2.5 Pro analysis) is converted to natural language and included in the **field guide**.
- **Chunks + field guide + page images** are sent to **Gemini 2.0 Flash**.
- Flash returns structured product data (MPN, product name, description, secondary description, category).
- Products are saved to the database. **The LLM is the sole source of truth for product names, descriptions, and categories.**

**Image association (separate step, after products exist):**
- PyMuPDF supplies **image bounding boxes** (from the images table) and **text span bounding boxes** via `_get_page_text_spans_with_bbox`.
- Catalog numbers in text spans are found using **regex** from the profile’s `catalog_number_patterns`.
- Each image is linked to the **nearest catalog number** on the page by spatial proximity (center-to-center distance).
- Those catalog numbers are matched to products (by MPN); **product_images** is filled to link images to the products created in the extraction step.

**Removed:**
- All spatial product extraction (zone detection, column detection, span-based product building, grid path).
- Span merging, zone/column-based image assignment, and `_apply_zone_based_image_links`.
- Imports and helpers that were only used for the spatial path (`get_zone_boundaries`, `get_product_cells_grid`, `zone_for_y`, `_detect_columns_in_zone`, `_merge_same_line_spans`, etc.).

**Kept:**
- Catalog analysis (Gemini 2.5 Pro producing the profile JSON).
- Profile-to–field-guide conversion (`format_analysis_profile_for_llm`).
- PyMuPDF extraction utilities (`_get_page_text_spans_with_bbox` for image association).
- Database schema and `_apply_proximity_image_links` as a fallback when PDF/profile are not available (uses page_blocks).

---

## Update: Image association as a key role of 2.5 Pro

The Gemini 2.5 Pro layout assessment now explicitly treats **image extraction and association** as a key output:

- The analysis prompt states that image association is central and will be used to improve downstream association.
- Section 4 (Image Types and Association) is labeled critical and asks for **image_association_instructions**: 2–4 short, actionable sentences for the extraction step.
- The profile schema includes `image_association.image_association_instructions` for these sentences.
- `format_analysis_profile_for_llm` is enriched to pass into the field guide:
  - Layout context (layout_structure.primary_pattern),
  - Full image_association (large_photos, small_detail_drawings, hard_rules),
  - **image_association_instructions** when present,
  - Fallback to image_rules when the new schema is not used.
- The vision extraction prompt uses a longer field_guide slice (900 chars) so catalog-specific image rules reach Gemini 2.0 Flash.

This keeps image association driven by the 2.5 Pro layout assessment while using it to improve the extractor (2.0 Flash) via instructions rather than layout code.
