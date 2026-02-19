# Catalog profiles (per-catalog image–product association)

When different catalogs use different **visual grammar** (e.g. orange horizontal rules to separate product groups), proximity alone can link the wrong images to products. **Catalog profiles** let you define rules per catalog so the build uses zone-based association when appropriate.

## How to set a profile (UI)

1. Open **Catalog setup** and select a catalog in the header.
2. Open the **Profile** tab.
3. Check **Zone-based image association** if this catalog uses divider lines to separate product groups.
4. Set **Page delimiter** to **Orange horizontal rule** if your catalog uses orange horizontal lines as zone dividers (or leave **None**).
5. If you chose Orange horizontal rule, set **Line color** (hex, e.g. `#F27926`), **Color tolerance**, **Min width (pt)**, and **Max height (pt)** to match your PDF.
6. Click **Save profile**.

The profile is stored with the catalog in the database. When you run **Build product listing**, the server uses it to detect zones and link images to products within the same zone.

## How it works (priority)

- **Profile** defines product grouping (how zones are delimited) and image association (`zone_based`).

- **Where the profile comes from (in order):**
  1. **Database** — The **Profile** tab saves to `catalog_config.catalog_profile` for that catalog. This is used first.
  2. **`sources.profile_path`** — If set (e.g. to a YAML file path), that file is loaded.
  3. **`catalog_profiles/<source_name>.yaml`** — File-based profile matched by source name (PDF filename without `.pdf`).

- **At build time:** When you run “Build product listing” for a page, if the catalog has a profile with `image_association.zone_based` and `product_grouping.delimiter`, the server opens the PDF, detects the delimiter lines (e.g. orange rules) on that page, divides the page into zones, and links each image only to products in the same zone (then by proximity within the zone).

## Example: V. Mueller–style (orange rules)

1. Copy the example profile and rename it to match your catalog’s source name:
   ```text
   copy catalog_profiles\vmueller_example.yaml catalog_profiles\<your_catalog_name>.yaml
   ```
   Example: if your PDF is `vmueller-snowdenpencer-armamentarium-catalogue-8.pdf`, the source name is `vmueller-snowdenpencer-armamentarium-catalogue-8`, so create `catalog_profiles/vmueller-snowdenpencer-armamentarium-catalogue-8.yaml` (you can start from `vmueller_example.yaml`).

2. Adjust the profile if needed (e.g. `delimiter_detection.color_rgb` or `min_width_pts`).

3. Run a rebuild (so `sources` and `page_blocks` are populated), then run **Build product listing** for that catalog. In the server log you should see:
   ```text
   [Build listing] page=N — using zone-based image association (catalog profile)
   ```

## Profile YAML schema (summary)

- **`product_grouping.delimiter`** — e.g. `orange_horizontal_rule`.
- **`product_grouping.delimiter_detection`** — `color_rgb`, `color_tolerance`, `min_width_pts`, `max_height_pts`.
- **`image_association.zone_based`** — `true` to use zones instead of whole-page proximity.

See **`catalog_profiles/vmueller_example.yaml`** and **`catalog_profiles/README.md`** for a concrete example and field notes.

## Database

- **`sources.profile_path`** — Optional path to the profile file for this source (if set, overrides name-based lookup). Added by `python scripts/init_db.py` if the column was missing.

## Dependencies

- **PyYAML** — Used to load profile YAML. Listed in `requirements.txt`; install with `pip install -r requirements.txt` if you use catalog profiles.
