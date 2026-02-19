# Profile consumption audit: column_detection and image_association

## 1. Where column_detection IS read and used

**File:** `scripts/chat_server.py`  
**Function:** `_spatial_extract_products_for_page`

```python
# Lines 742–746
# Column detection within each zone (when profile.column_detection.enabled): split by x-clusters (gap > min_column_gap_pts)
column_detection = profile.get("column_detection") or {}
column_enabled = column_detection.get("enabled", True)
column_gap_pts = float(column_detection.get("min_column_gap_pts") or COLUMN_GAP_PTS)
```

- **Used:** `enabled` → whether to run column detection per zone.  
- **Used:** `min_column_gap_pts` → passed to `_detect_columns_in_zone(zone_spans, min_font, column_gap_pts)`.

Column boundaries come from `_detect_columns_in_zone` (lines 609–639): it uses span x-positions and `gap_pts` (and `min_font` for “family-like” spans). It does **not** read any other `column_detection` fields from the profile.

Images are assigned to a column by x-position only (lines 869–876):

```python
# Assign each image to (zone, column) by y then x; link only within that zone-column
img_zone_column = []
for i, im in enumerate(images):
    z = img_zone_index[i]
    cols = zone_columns.get(z, [(0.0, 0.0)])
    col = _column_for_x(im["center"][0], cols)
    img_zone_column.append((z, col))
```

So: **only `column_detection.enabled` and `column_detection.min_column_gap_pts` are consumed.** Splitting is done by a fixed algorithm (gap + optional family-like spans), not by profile-driven column_identifier, boundary method, or wide_image rules.

---

## 2. column_detection fields NOT consumed

These profile fields are **never** read in the extraction pipeline:

| Profile field | Purpose (from analysis prompt) | Consumed? |
|---------------|---------------------------------|-----------|
| `column_identifier` | What defines a column (e.g. each product family name) | **No** |
| `sub_columns_exist` / `sub_column_description` | Sub-columns within a family | **No** |
| `zone_independent` | Column count varies per zone | **No** (we already run column detection per zone) |
| `wide_image_handling` | How to handle images wider than their column | **No** |
| `column_boundary_method` | e.g. midpoint_between_families vs text_cluster_edges | **No** |
| `variable_column_count` / `max_columns_observed` | Hints for column logic | **No** |

So the analysis can describe column layout and wide images in detail, but the pipeline does not use those instructions.

---

## 3. image_association.hard_rules — NOT consumed anywhere

**Search result:** `hard_rules` and `image_association` do **not** appear in `chat_server.py` or `catalog_profile.py` in any logic that runs during extraction.

So:

- **`image_association.hard_rules`** is **never** read.
- **`primary_association_method`** / **`secondary_association_method`** are **never** read.

The pipeline’s behavior happens to align with typical hard rules (e.g. “image in zone N never to product in zone M”, “image in column A never to product in column B”) because:

- We only consider products in the same `(zone, column)` as the image (lines 869–884, 879–883: `key = (z, col)`, `zone_col_mpn_to_id = zone_column_product_ids_by_mpn.get(key, {})`, and we only link within that key).

So the **effect** of those rules is implemented implicitly; the **profile text** for `hard_rules` is never loaded or enforced. If the analysis added different or extra rules, the code would not follow them.

---

## 4. Conclusion

- **column_detection:** Only `enabled` and `min_column_gap_pts` are used. Other column_detection fields (column_identifier, sub_columns, wide_image_handling, boundary_method, etc.) are not consumed.
- **image_association.hard_rules:** Not read or enforced; behavior is hardcoded (same zone-column only).
- **image_association** primary/secondary methods and size rules: Large/small thresholds come from **image_rules** (normalized from image_association in catalog_analysis), but the explicit “hard_rules” list and association method names are not used.

If the analysis produces correct rules but images are still misaligned, it is likely because:

1. Column logic ignores profile hints (column_identifier, wide_image_handling, etc.), and/or  
2. hard_rules are not read, so any custom or catalog-specific rule in `hard_rules` is never applied.

Next step: add explicit reading of `column_detection` (e.g. wide_image_handling, column_identifier) and `image_association.hard_rules` (and optionally primary/secondary_association_method) in the extraction pipeline so the code follows the analysis.
