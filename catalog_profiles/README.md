# Catalog profiles

Each catalog can have a **profile** (YAML) that describes its visual grammar: how product groups are delimited (e.g. orange horizontal rules), how images are associated (zone-based vs proximity), and optional extraction hints.

- **Matching:** A profile is used for a source when:
  1. The source has `profile_path` set in the database (explicit), or
  2. A file `catalog_profiles/<source_name>.yaml` exists (source name = PDF filename without `.pdf`).

- **Zone-based association:** If the profile defines `product_grouping.delimiter` (e.g. orange horizontal rule), the build will detect those lines on each page, divide the page into zones, and associate images to products only within the same zone. This fixes cases where proximity alone wrongly links an image to a different product family.

- **Example:** See `vmueller_example.yaml` for a V. Mueller–style catalog that uses orange rules as zone dividers.
